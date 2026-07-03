"""Graph nodes for the EDA pipeline: ingest -> profile -> narrate -> render_report.

Each node catches its own exceptions. Fatal errors (invalid file, profiling or
rendering failure) set ``state["error"]`` and route to ``handle_error``. The
narrative (Gemini) step is the only non-fatal step: on any failure it falls back
to a templated summary and the run still completes.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from graph.state import AgentState
from llm.client import LLMClient
from tools.profiling import parse_dataset, profile_dataframe
from tools.charts import render_charts
from tools.report import render_report_html
from tools.narrative import build_stats_summary, templated_narrative

logger = logging.getLogger("agent.graph")

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "narrative.md"


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8").strip()


def ingest(state: AgentState) -> AgentState:
    """Validate + parse the uploaded CSV or Parquet file into a DataFrame."""
    try:
        df = parse_dataset(state.get("csv_bytes") or b"", state.get("filename"))
        logger.info(
            "ingest ok run_id=%s rows=%d cols=%d",
            state.get("run_id"), df.shape[0], df.shape[1],
        )
        return {**state, "dataframe": df}
    except Exception as exc:  # noqa: BLE001 - fatal, surface to handle_error
        logger.warning("ingest failed run_id=%s error=%s", state.get("run_id"), exc)
        return {**state, "error": str(exc)}


def profile(state: AgentState) -> AgentState:
    """Compute derived statistics and render the three charts."""
    try:
        df = state["dataframe"]
        profile_dict = profile_dataframe(df)
        charts = render_charts(df)
        logger.info(
            "profile ok run_id=%s numeric=%d charts=%s",
            state.get("run_id"),
            len(profile_dict.get("numeric_columns", [])),
            [k for k, v in charts.items() if v],
        )
        return {**state, "profile": profile_dict, "charts": charts}
    except Exception as exc:  # noqa: BLE001 - fatal, surface to handle_error
        logger.warning("profile failed run_id=%s error=%s", state.get("run_id"), exc)
        return {**state, "error": str(exc)}


def narrate(state: AgentState) -> AgentState:
    """Generate the narrative via Gemini; fall back to a template on any error.

    Never fatal — a narrative failure must not fail the run.
    """
    profile_dict = state.get("profile") or {}
    stats_summary = build_stats_summary(profile_dict)
    started = time.monotonic()
    try:
        system_prompt = _load_prompt()
        narrative = LLMClient().call_model(stats_summary, system=system_prompt)
        narrative = (narrative or "").strip()
        if not narrative:
            raise ValueError("Gemini returned an empty narrative")
        logger.info(
            "narrate ok run_id=%s latency_ms=%d chars=%d",
            state.get("run_id"), int((time.monotonic() - started) * 1000), len(narrative),
        )
        return {**state, "narrative": narrative}
    except Exception as exc:  # noqa: BLE001 - non-fatal, fall back to template
        logger.warning(
            "narrate fell back to template run_id=%s latency_ms=%d error=%s",
            state.get("run_id"), int((time.monotonic() - started) * 1000), exc,
        )
        return {**state, "narrative": templated_narrative(profile_dict)}


def render_report(state: AgentState) -> AgentState:
    """Assemble the self-contained HTML report."""
    try:
        html = render_report_html(
            profile=state.get("profile") or {},
            charts=state.get("charts") or {},
            narrative=state.get("narrative") or "",
            filename=state.get("filename"),
        )
        logger.info(
            "render_report ok run_id=%s bytes=%d",
            state.get("run_id"), len(html),
        )
        return {**state, "report_html": html, "status": "completed"}
    except Exception as exc:  # noqa: BLE001 - fatal, surface to handle_error
        logger.warning("render_report failed run_id=%s error=%s", state.get("run_id"), exc)
        return {**state, "error": str(exc)}


def handle_error(state: AgentState) -> AgentState:
    logger.error(
        "run failed run_id=%s error=%s", state.get("run_id"), state.get("error")
    )
    return {**state, "status": "failed"}
