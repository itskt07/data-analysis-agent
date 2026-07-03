from pydantic import BaseModel


class RunResponse(BaseModel):
    run_id: str
    status: str
    report_url: str | None = None
    narrative: str | None = None
    error: str | None = None
