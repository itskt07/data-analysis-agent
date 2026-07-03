def test_graph_compiles():
    """Graph compiles without requiring any env vars."""
    from graph.agent import agentic_ai
    assert agentic_ai is not None


def test_graph_has_eda_nodes():
    """The compiled graph exposes the EDA pipeline nodes."""
    from graph.agent import agentic_ai
    nodes = set(agentic_ai.get_graph().nodes.keys())
    for expected in {"ingest", "profile", "narrate", "render_report", "handle_error"}:
        assert expected in nodes
