"""Self-contained HTML report renderer.

Assembles the profile dict, chart images (base64 PNG), and narrative into a
single HTML document with inline CSS and inline base64 ``<img>`` charts. No
external assets are referenced, so the report opens offline.
"""
from __future__ import annotations

from html import escape
from typing import Any

_CHART_TITLES = {
    "histogram": "Histogram",
    "boxplot": "Boxplot",
    "correlation_heatmap": "Correlation heatmap",
}

_STYLE = """
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       margin: 0; padding: 2rem; color: #1a1a1a; background: #f7f8fa; }
.container { max-width: 1000px; margin: 0 auto; background: #fff; padding: 2rem 2.5rem;
             border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
h1 { margin-top: 0; font-size: 1.7rem; }
h2 { margin-top: 2.2rem; font-size: 1.25rem; border-bottom: 2px solid #eee; padding-bottom: 0.35rem; }
.meta { color: #555; font-size: 0.9rem; }
.narrative { background: #f0f5ff; border-left: 4px solid #4c72b0; padding: 1rem 1.2rem;
             border-radius: 6px; white-space: pre-wrap; line-height: 1.5; }
table { border-collapse: collapse; width: 100%; margin-top: 0.6rem; font-size: 0.85rem; }
th, td { border: 1px solid #e2e2e2; padding: 6px 9px; text-align: left; }
th { background: #f0f1f4; position: sticky; top: 0; }
tr:nth-child(even) td { background: #fafbfc; }
.table-wrap { overflow-x: auto; max-height: 460px; overflow-y: auto; border: 1px solid #eee; border-radius: 6px; }
.charts { display: flex; flex-wrap: wrap; gap: 1.5rem; margin-top: 0.8rem; }
.chart { flex: 1 1 300px; text-align: center; }
.chart img { max-width: 100%; height: auto; border: 1px solid #eee; border-radius: 6px; }
.chart h3 { font-size: 1rem; margin-bottom: 0.4rem; }
.note { color: #a15c00; background: #fff8e6; border: 1px solid #ffe0a3;
        padding: 0.7rem 1rem; border-radius: 6px; font-size: 0.9rem; }
""".strip()


def _num(value: Any) -> str:
    if value is None:
        return "—"
    return escape(str(value))


def _summary_table(columns: list[dict[str, Any]]) -> str:
    header = (
        "<tr><th>Column</th><th>Type</th><th>Count</th><th>Missing</th>"
        "<th>Missing %</th><th>Mean</th><th>Std</th><th>Min</th><th>Max</th>"
        "<th>25%</th><th>50%</th><th>75%</th><th>Unique</th><th>Top</th></tr>"
    )
    rows = []
    for col in columns:
        rows.append(
            "<tr>"
            f"<td>{escape(str(col['name']))}</td>"
            f"<td>{escape(str(col['dtype']))}</td>"
            f"<td>{_num(col['count'])}</td>"
            f"<td>{_num(col['missing'])}</td>"
            f"<td>{_num(col['missing_pct'])}</td>"
            f"<td>{_num(col['mean'])}</td>"
            f"<td>{_num(col['std'])}</td>"
            f"<td>{_num(col['min'])}</td>"
            f"<td>{_num(col['max'])}</td>"
            f"<td>{_num(col['q25'])}</td>"
            f"<td>{_num(col['q50'])}</td>"
            f"<td>{_num(col['q75'])}</td>"
            f"<td>{_num(col['unique'])}</td>"
            f"<td>{_num(col['top'])}</td>"
            "</tr>"
        )
    return f"<div class='table-wrap'><table>{header}{''.join(rows)}</table></div>"


def _missingness_table(missingness: list[dict[str, Any]]) -> str:
    header = "<tr><th>Column</th><th>Missing count</th><th>Missing %</th></tr>"
    rows = [
        "<tr>"
        f"<td>{escape(str(m['name']))}</td>"
        f"<td>{_num(m['missing'])}</td>"
        f"<td>{_num(m['missing_pct'])}</td>"
        "</tr>"
        for m in missingness
    ]
    return f"<div class='table-wrap'><table>{header}{''.join(rows)}</table></div>"


def _sample_table(sample_rows: dict[str, Any]) -> str:
    cols = sample_rows.get("columns", [])
    header = "<tr>" + "".join(f"<th>{escape(str(c))}</th>" for c in cols) + "</tr>"
    body = []
    for row in sample_rows.get("rows", []):
        body.append("<tr>" + "".join(f"<td>{escape(str(v))}</td>" for v in row) + "</tr>")
    if not body:
        return "<p class='note'>No data rows to display.</p>"
    return f"<div class='table-wrap'><table>{header}{''.join(body)}</table></div>"


def _charts_section(charts: dict[str, Any]) -> str:
    blocks = []
    for key, title in _CHART_TITLES.items():
        image = charts.get(key)
        if image:
            blocks.append(
                f"<div class='chart'><h3>{escape(title)}</h3>"
                f"<img alt='{escape(title)}' src='data:image/png;base64,{image}'/></div>"
            )
    if not blocks:
        return "<p class='note'>No numeric columns were found, so charts could not be generated.</p>"

    missing = [t for k, t in _CHART_TITLES.items() if not charts.get(k)]
    note = ""
    if missing:
        note = (
            f"<p class='note'>Some charts were omitted (insufficient numeric data): "
            f"{escape(', '.join(missing))}.</p>"
        )
    return f"<div class='charts'>{''.join(blocks)}</div>{note}"


def render_report_html(
    profile: dict[str, Any],
    charts: dict[str, Any],
    narrative: str,
    filename: str | None = None,
) -> str:
    """Assemble the full self-contained HTML report document."""
    shape = profile.get("shape", {})
    rows = shape.get("rows", 0)
    n_cols = shape.get("columns", 0)
    title = escape(filename or "Dataset")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>EDA Report — {title}</title>
<style>{_STYLE}</style>
</head>
<body>
<div class="container">
<h1>Exploratory Data Analysis Report</h1>
<p class="meta"><strong>File:</strong> {title} &nbsp;·&nbsp;
   <strong>Rows:</strong> {escape(str(rows))} &nbsp;·&nbsp;
   <strong>Columns:</strong> {escape(str(n_cols))}</p>

<h2>Executive summary</h2>
<div class="narrative">{escape(narrative or "No narrative available.")}</div>

<h2>Summary statistics</h2>
{_summary_table(profile.get("columns", []))}

<h2>Missingness</h2>
{_missingness_table(profile.get("missingness", []))}

<h2>Sample rows</h2>
{_sample_table(profile.get("sample_rows", {}))}

<h2>Charts</h2>
{_charts_section(charts)}
</div>
</body>
</html>"""
