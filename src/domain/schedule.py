from pydantic import BaseModel


class RunSummary(BaseModel):
    """Compact link object for a run produced by a schedule."""

    run_id: str
    status: str
    report_url: str | None = None
    created_at: str | None = None


class ScheduleResponse(BaseModel):
    """A schedule summary, optionally including its run history.

    `GET /schedules` (list) omits `runs`; `GET /schedules/{id}` and
    `POST /schedules` include it.
    """

    schedule_id: str
    name: str | None = None
    filename: str | None = None
    interval_minutes: int
    webhook_url: str | None = None
    active: bool
    last_run_at: str | None = None
    created_at: str | None = None
    runs: list[RunSummary] = []
