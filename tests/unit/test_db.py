"""DB layer tests — no LLM key required."""
from sqlalchemy.orm import Session
from db.models import RunRow


def test_run_row_roundtrip(_isolated_db):
    with Session(_isolated_db) as s:
        run = RunRow(filename="data.csv")
        s.add(run)
        s.commit()
        run_id = run.id

    with Session(_isolated_db) as s:
        fetched = s.get(RunRow, run_id)
        assert fetched is not None
        assert fetched.filename == "data.csv"
        assert fetched.status == "pending"
        assert fetched.narrative is None
        assert fetched.report_html is None


def test_run_row_outcome_update(_isolated_db):
    with Session(_isolated_db) as s:
        run = RunRow(filename="data.csv")
        s.add(run)
        s.commit()
        run_id = run.id

    with Session(_isolated_db) as s:
        run = s.get(RunRow, run_id)
        run.status = "completed"
        run.narrative = "A short summary."
        run.report_html = "<html>report</html>"
        s.commit()

    with Session(_isolated_db) as s:
        run = s.get(RunRow, run_id)
        assert run.status == "completed"
        assert run.narrative == "A short summary."
        assert run.report_html == "<html>report</html>"


def test_multiple_runs_independent(_isolated_db):
    with Session(_isolated_db) as s:
        for i in range(3):
            s.add(RunRow(filename=f"file_{i}.csv"))
        s.commit()
        ids = [r.id for r in s.query(RunRow).all()]

    assert len(ids) == 3
    assert len(set(ids)) == 3
