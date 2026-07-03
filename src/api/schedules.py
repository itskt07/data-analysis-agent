from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from api._common import ok, api_error
from config.settings import get_settings
from db.session import create_db_session, get_session
from db.models import RunRow, ScheduleRow
from domain.run import RunResponse
from domain.schedule import RunSummary, ScheduleResponse
from scheduling import scheduler

router = APIRouter()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _is_csv_upload(file: UploadFile) -> bool:
    name = (file.filename or "").lower()
    content_type = (file.content_type or "").lower()
    if name.endswith(".csv"):
        return True
    return content_type in {"text/csv", "application/csv", "text/plain"}


def _run_summaries(session: Session, schedule_id: str) -> list[RunSummary]:
    rows = (
        session.query(RunRow)
        .filter(RunRow.schedule_id == schedule_id)
        .order_by(RunRow.created_at.desc())
        .all()
    )
    return [
        RunSummary(
            run_id=r.id,
            status=r.status,
            report_url=f"/runs/{r.id}/report" if r.report_html else None,
            created_at=_iso(r.created_at),
        )
        for r in rows
    ]


def _to_response(row: ScheduleRow, runs: list[RunSummary]) -> ScheduleResponse:
    return ScheduleResponse(
        schedule_id=row.id,
        name=row.name,
        filename=row.filename,
        interval_minutes=row.interval_minutes,
        webhook_url=row.webhook_url,
        active=row.active,
        last_run_at=_iso(row.last_run_at),
        created_at=_iso(row.created_at),
        runs=runs,
    )


def _run_response(run: RunRow) -> dict:
    return RunResponse(
        run_id=run.id,
        status=run.status,
        report_url=f"/runs/{run.id}/report" if run.report_html else None,
        narrative=run.narrative,
        error=run.error_message,
    ).model_dump()


@router.post("/schedules")
async def create_schedule(
    file: UploadFile = File(...),
    interval_minutes: str | None = Form(None),
    webhook_url: str | None = Form(None),
    name: str | None = Form(None),
    session: Session = Depends(get_session),
) -> dict:
    if not _is_csv_upload(file):
        raise api_error("BAD_REQUEST", "Upload must be a CSV file.", 400)

    # interval_minutes is required, must be an integer >= 1.
    if interval_minutes is None or not str(interval_minutes).strip():
        raise api_error("BAD_REQUEST", "interval_minutes is required.", 400)
    try:
        interval = int(str(interval_minutes).strip())
    except (ValueError, TypeError):
        raise api_error("BAD_REQUEST", "interval_minutes must be an integer.", 400)
    if interval < 1:
        raise api_error("BAD_REQUEST", "interval_minutes must be >= 1.", 400)

    file_bytes = await file.read()

    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise api_error(
            "FILE_TOO_LARGE",
            f"File exceeds the {get_settings().max_upload_mb} MB limit.",
            413,
        )
    if not file_bytes or not file_bytes.strip():
        raise api_error("BAD_REQUEST", "The uploaded CSV is empty.", 400)

    filename = file.filename or "schedule.csv"
    label = (name or "").strip() or filename
    hook = (webhook_url or "").strip() or None

    row = ScheduleRow(
        name=label,
        filename=filename,
        csv_bytes=file_bytes,
        interval_minutes=interval,
        webhook_url=hook,
        active=True,
    )
    session.add(row)
    session.flush()

    # Register the interval job with the in-process scheduler.
    scheduler.register(row)

    return ok(_to_response(row, []).model_dump())


@router.get("/schedules")
def list_schedules(session: Session = Depends(get_session)) -> dict:
    rows = session.query(ScheduleRow).order_by(ScheduleRow.created_at.desc()).all()
    # List omits run history (per api.md).
    return ok([_to_response(r, []).model_dump(exclude={"runs"}) for r in rows])


@router.get("/schedules/{schedule_id}")
def get_schedule(schedule_id: str, session: Session = Depends(get_session)) -> dict:
    row = session.get(ScheduleRow, schedule_id)
    if row is None:
        raise api_error("NOT_FOUND", f"Schedule {schedule_id} not found", 404)
    runs = _run_summaries(session, schedule_id)
    return ok(_to_response(row, runs).model_dump())


@router.post("/schedules/{schedule_id}/run")
def run_schedule_now(
    schedule_id: str, session: Session = Depends(get_session)
) -> dict:
    row = session.get(ScheduleRow, schedule_id)
    if row is None:
        raise api_error("NOT_FOUND", f"Schedule {schedule_id} not found", 404)

    run_id = scheduler.execute_schedule(schedule_id)
    if run_id is None:
        raise api_error("NOT_FOUND", f"Schedule {schedule_id} not found", 404)

    # execute_schedule commits the run in its own session; read it back from a
    # fresh session to guarantee visibility of that commit.
    with create_db_session() as read_session:
        run = read_session.get(RunRow, run_id)
        if run is None:
            raise api_error("NOT_FOUND", "Run not found after execution", 500)
        return ok(_run_response(run))


@router.delete("/schedules/{schedule_id}")
def delete_schedule(
    schedule_id: str, session: Session = Depends(get_session)
) -> dict:
    row = session.get(ScheduleRow, schedule_id)
    if row is None:
        raise api_error("NOT_FOUND", f"Schedule {schedule_id} not found", 404)

    # Unregister the job, retain produced runs (null their schedule_id link).
    scheduler.unregister(schedule_id)
    produced = session.query(RunRow).filter(RunRow.schedule_id == schedule_id).all()
    for run in produced:
        run.schedule_id = None
    session.delete(row)

    return ok({"schedule_id": schedule_id, "deleted": True})
