from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from api._common import ok, api_error
from config.settings import get_settings
from db.session import get_session
from db.models import RunRow
from domain.run import RunResponse
from graph.runner import run_agent

router = APIRouter()


def _report_url(run_id: str) -> str:
    return f"/runs/{run_id}/report"


def _to_response(run: RunRow) -> dict:
    return RunResponse(
        run_id=run.id,
        status=run.status,
        report_url=_report_url(run.id) if run.report_html else None,
        narrative=run.narrative,
        error=run.error_message,
    ).model_dump()


def _is_csv_upload(file: UploadFile) -> bool:
    name = (file.filename or "").lower()
    content_type = (file.content_type or "").lower()
    if name.endswith(".csv"):
        return True
    # Accept generic text/CSV content types when the extension is absent.
    return content_type in {"text/csv", "application/csv", "text/plain"}


@router.post("/runs")
async def create_run(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict:
    if not _is_csv_upload(file):
        raise api_error("BAD_REQUEST", "Upload must be a CSV file.", 400)

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

    run_id = run_agent(file_bytes, file.filename or "upload.csv")
    run = session.get(RunRow, run_id)
    if run is None:
        raise api_error("NOT_FOUND", "Run not found after creation", 500)
    return ok(_to_response(run))


@router.get("/runs/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_session)) -> dict:
    run = session.get(RunRow, run_id)
    if run is None:
        raise api_error("NOT_FOUND", f"Run {run_id} not found", 404)
    return ok(_to_response(run))


@router.get("/runs/{run_id}/report", response_class=HTMLResponse)
def get_report(run_id: str, session: Session = Depends(get_session)) -> HTMLResponse:
    run = session.get(RunRow, run_id)
    if run is None or not run.report_html:
        raise api_error("NOT_FOUND", f"Report for run {run_id} not found", 404)
    return HTMLResponse(content=run.report_html)
