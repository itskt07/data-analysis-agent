from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    # Identity
    run_id: str

    # Input
    filename: str
    csv_bytes: bytes                 # raw uploaded CSV, in-memory only (never persisted)

    # Pipeline data (populated progressively by nodes)
    dataframe: Any                   # parsed pandas DataFrame (in-process only)
    profile: dict[str, Any] | None   # derived, aggregated statistics (never raw rows)
    charts: dict[str, Any] | None    # base64 PNG chart images
    narrative: str | None            # Gemini narrative, or templated fallback

    # Output
    report_html: str | None          # final self-contained HTML report

    # Control
    status: str                      # "pending" | "completed" | "failed"
    error: str | None                # set by any node on fatal failure
