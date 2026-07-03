from graph.state import AgentState


def after_ingest(state: AgentState) -> str:
    if state.get("error"):
        return "handle_error"
    return "profile"


def after_profile(state: AgentState) -> str:
    if state.get("error"):
        return "handle_error"
    return "narrate"
