"""Pure-function tests for the profiling / charts / report tools — no LLM key."""
import base64

import pytest

from tools.profiling import parse_csv, profile_dataframe
from tools.charts import render_charts, correlation_heatmap
from tools.report import render_report_html
from tools.narrative import build_stats_summary, templated_narrative

IRIS = (
    b"a,b,label\n1.0,2.0,x\n2.0,4.0,y\n3.0,6.0,x\n4.0,8.0,z\n"
)


def _profile(csv: bytes):
    return profile_dataframe(parse_csv(csv))


def test_parse_csv_rejects_empty():
    with pytest.raises(ValueError):
        parse_csv(b"")


def test_parse_csv_rejects_header_only():
    with pytest.raises(ValueError):
        parse_csv(b"a,b,c\n")


def test_profile_shape_and_kinds():
    profile = _profile(IRIS)
    assert profile["shape"] == {"rows": 4, "columns": 3}
    assert set(profile["numeric_columns"]) == {"a", "b"}
    assert profile["categorical_columns"] == ["label"]
    assert profile["sample_rows"]["columns"] == ["a", "b", "label"]
    assert len(profile["sample_rows"]["rows"]) == 4


def test_profile_json_serializable():
    import json
    json.dumps(_profile(IRIS))  # must not raise on numpy types


def test_profile_numeric_stats_present():
    profile = _profile(IRIS)
    col_a = next(c for c in profile["columns"] if c["name"] == "a")
    assert col_a["kind"] == "numeric"
    assert col_a["min"] == 1
    assert col_a["max"] == 4
    assert col_a["missing"] == 0
    # Perfect correlation between a and b.
    assert profile["correlations"]
    assert abs(profile["correlations"][0]["r"]) == 1


def test_profile_all_missing_column():
    csv = b"id,notes\n1,\n2,\n3,\n"
    profile = _profile(csv)
    notes = next(c for c in profile["columns"] if c["name"] == "notes")
    assert notes["missing"] == 3
    assert notes["missing_pct"] == 100.0


def test_charts_three_for_numeric_data():
    df = parse_csv(IRIS)
    charts = render_charts(df)
    assert charts["histogram"]
    assert charts["boxplot"]
    assert charts["correlation_heatmap"]
    # Valid base64 PNG.
    assert base64.b64decode(charts["histogram"])[:4] == b"\x89PNG"


def test_charts_skip_when_no_numeric():
    df = parse_csv(b"color,shape\nred,circle\nblue,square\n")
    charts = render_charts(df)
    assert charts["histogram"] is None
    assert charts["boxplot"] is None
    assert charts["correlation_heatmap"] is None


def test_heatmap_needs_two_numeric_columns():
    df = parse_csv(b"value\n1\n2\n3\n")
    assert correlation_heatmap(df) is None


def test_report_is_self_contained():
    profile = _profile(IRIS)
    charts = render_charts(parse_csv(IRIS))
    html = render_report_html(profile, charts, "A narrative.", "iris.csv")
    assert "<!DOCTYPE html>" in html
    assert "Summary statistics" in html
    assert "Missingness" in html
    assert "Sample rows" in html
    assert html.count("data:image/png;base64,") == 3
    assert "A narrative." in html
    # No external asset references.
    assert "http://" not in html and "https://" not in html


def test_report_escapes_html():
    profile = _profile(b"name\n<script>alert(1)</script>\n")
    html = render_report_html(profile, {}, "n", "x.csv")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_stats_summary_excludes_raw_rows():
    summary = build_stats_summary(_profile(IRIS))
    assert "Dataset shape" in summary
    assert "Numeric column summaries" in summary


def test_templated_narrative_mentions_shape():
    text = templated_narrative(_profile(IRIS))
    assert "4 rows" in text
    assert "built-in template" in text
