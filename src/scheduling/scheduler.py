"""In-process scheduler for recurring EDA runs (Phase 3).

A single module-level APScheduler ``BackgroundScheduler`` fires each active
schedule on its interval, reusing the existing synchronous EDA pipeline
(``run_agent``). The same ``execute_schedule`` function is invoked synchronously
by the "Run now" endpoint. No external broker — jobs run in a background thread
inside the same uvicorn process. Schedules only fire while the process is
running; on startup all ``active`` schedules are re-registered from the DB.
"""
import json
import logging
import time
import urllib.request
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.base import JobLookupError

from db.session import create_db_session
from db.models import RunRow, ScheduleRow
from graph.runner import run_agent

logger = logging.getLogger("agent.scheduler")

_WEBHOOK_TIMEOUT_S = 5

_scheduler: BackgroundScheduler | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
    return _scheduler


def start() -> None:
    """Idempotently start the background scheduler.

    Safe to call from the FastAPI lifespan on every startup. If a previous
    scheduler was shut down (e.g. a prior TestClient context), a fresh one is
    created and started; ``reregister_active()`` re-adds the jobs afterwards.
    """
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return
    _scheduler = BackgroundScheduler()
    _scheduler.start()
    logger.info("scheduler started")


def shutdown() -> None:
    """Stop the background scheduler if running (clean lifespan shutdown)."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("scheduler shut down")


def register(schedule: ScheduleRow) -> None:
    """Add (or replace) an interval job for a schedule."""
    sched = _get_scheduler()
    sched.add_job(
        execute_schedule,
        trigger="interval",
        minutes=schedule.interval_minutes,
        id=schedule.id,
        args=[schedule.id],
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info(
        "schedule registered schedule_id=%s interval_minutes=%s",
        schedule.id, schedule.interval_minutes,
    )


def unregister(schedule_id: str) -> None:
    """Remove a schedule's job if present (no-op if absent)."""
    sched = _get_scheduler()
    try:
        sched.remove_job(schedule_id)
        logger.info("schedule unregistered schedule_id=%s", schedule_id)
    except JobLookupError:
        pass


def reregister_active() -> None:
    """Re-add an interval job for every active schedule (startup recovery)."""
    with create_db_session() as session:
        rows = session.query(ScheduleRow).filter(ScheduleRow.active.is_(True)).all()
        for row in rows:
            register(row)
    logger.info("reregistered %d active schedule(s)", len(rows))


def _post_webhook(url: str, payload: dict) -> None:
    """Best-effort webhook POST — any error is logged and swallowed."""
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_WEBHOOK_TIMEOUT_S) as resp:
            resp.read()
        logger.info(
            "webhook delivered schedule_id=%s run_id=%s url=%s",
            payload.get("schedule_id"), payload.get("run_id"), url,
        )
    except Exception as exc:  # noqa: BLE001 - delivery is non-fatal by design
        logger.warning(
            "webhook delivery failed schedule_id=%s run_id=%s url=%s error=%s",
            payload.get("schedule_id"), payload.get("run_id"), url, exc,
        )


def execute_schedule(schedule_id: str) -> str | None:
    """Run a schedule's EDA pipeline once and record the result.

    Loads the stored CSV bytes, runs the (synchronous) EDA pipeline to create a
    normal ``runs`` row, links that run back to the schedule, updates
    ``last_run_at``, and — if a ``webhook_url`` is set — POSTs a small JSON
    payload (non-fatal). Safe to call from the scheduler thread and from the
    Run-now endpoint. Returns the created ``run_id`` (or ``None`` if the
    schedule no longer exists).
    """
    started = time.monotonic()

    with create_db_session() as session:
        schedule = session.get(ScheduleRow, schedule_id)
        if schedule is None:
            logger.warning("execute_schedule: unknown schedule_id=%s", schedule_id)
            return None
        csv_bytes = schedule.csv_bytes
        filename = schedule.filename or "schedule.csv"
        webhook_url = schedule.webhook_url

    # Reuse the Phase-1 EDA pipeline; this creates + persists a normal runs row.
    run_id = run_agent(csv_bytes, filename)

    with create_db_session() as session:
        run = session.get(RunRow, run_id)
        status = run.status if run is not None else "failed"
        has_report = bool(run is not None and run.report_html)
        if run is not None:
            run.schedule_id = schedule_id
        schedule = session.get(ScheduleRow, schedule_id)
        if schedule is not None:
            schedule.last_run_at = _now()

    report_url = f"/runs/{run_id}/report" if has_report else None

    if webhook_url:
        _post_webhook(
            webhook_url,
            {
                "schedule_id": schedule_id,
                "run_id": run_id,
                "status": status,
                "report_url": report_url,
            },
        )

    logger.info(
        "schedule executed schedule_id=%s run_id=%s status=%s latency_ms=%d",
        schedule_id, run_id, status, int((time.monotonic() - started) * 1000),
    )
    return run_id
