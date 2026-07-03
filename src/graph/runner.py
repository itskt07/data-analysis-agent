import logging
import time

from graph.agent import agentic_ai
from graph.state import AgentState
from db.session import create_db_session, init_db
from db.models import RunRow

logger = logging.getLogger("agent.runner")


def run_agent(file_bytes: bytes, filename: str) -> str:
    """Run the EDA pipeline synchronously and persist the outcome.

    Returns the run_id. The uploaded bytes are held in memory only for the
    duration of the run; raw rows are never persisted.
    """
    init_db()

    with create_db_session() as session:
        run = RunRow(filename=filename, status="pending")
        session.add(run)
        session.flush()
        run_id = run.id

    started = time.monotonic()
    initial: AgentState = {
        "run_id": run_id,
        "filename": filename,
        "csv_bytes": file_bytes,
        "status": "pending",
        "error": None,
    }
    final = agentic_ai.invoke(initial)

    status = final.get("status", "completed")
    if final.get("error"):
        status = "failed"

    with create_db_session() as session:
        run = session.get(RunRow, run_id)
        run.status = status
        run.narrative = final.get("narrative")
        run.report_html = final.get("report_html")
        run.error_message = final.get("error")

    logger.info(
        "run complete run_id=%s status=%s latency_ms=%d",
        run_id, status, int((time.monotonic() - started) * 1000),
    )
    return run_id
