from langgraph.graph import StateGraph, END

from graph.state import AgentState
from graph.nodes import ingest, profile, narrate, render_report, handle_error
from graph.edges import after_ingest, after_profile


def _build_graph() -> StateGraph:
    g = StateGraph(AgentState)
    g.add_node("ingest", ingest)
    g.add_node("profile", profile)
    g.add_node("narrate", narrate)
    g.add_node("render_report", render_report)
    g.add_node("handle_error", handle_error)

    g.set_entry_point("ingest")
    g.add_conditional_edges(
        "ingest",
        after_ingest,
        {"profile": "profile", "handle_error": "handle_error"},
    )
    g.add_conditional_edges(
        "profile",
        after_profile,
        {"narrate": "narrate", "handle_error": "handle_error"},
    )
    g.add_edge("narrate", "render_report")
    g.add_edge("render_report", END)
    g.add_edge("handle_error", END)
    return g.compile()


agentic_ai = _build_graph()
