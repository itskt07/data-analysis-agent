from langgraph.graph import StateGraph, END

from graph.train_state import TrainState
from graph.train_nodes import (
    ingest_train,
    train,
    evaluate,
    summarize,
    persist,
    handle_error,
)
from graph.train_nodes import after_ingest_train, after_train, after_evaluate


def _build_graph() -> StateGraph:
    g = StateGraph(TrainState)
    g.add_node("ingest_train", ingest_train)
    g.add_node("train", train)
    g.add_node("evaluate", evaluate)
    g.add_node("summarize", summarize)
    g.add_node("persist", persist)
    g.add_node("handle_error", handle_error)

    g.set_entry_point("ingest_train")
    g.add_conditional_edges(
        "ingest_train",
        after_ingest_train,
        {"train": "train", "handle_error": "handle_error"},
    )
    g.add_conditional_edges(
        "train",
        after_train,
        {"evaluate": "evaluate", "handle_error": "handle_error"},
    )
    g.add_conditional_edges(
        "evaluate",
        after_evaluate,
        {"summarize": "summarize", "handle_error": "handle_error"},
    )
    g.add_edge("summarize", "persist")
    g.add_edge("persist", END)
    g.add_edge("handle_error", END)
    return g.compile()


training_ai = _build_graph()
