"""Wire LangGraph nodes into a state machine."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from src.graph import nodes
from src.graph.state import AgentState


def build_graph():
    g = StateGraph(AgentState)

    g.add_node("contextualize", nodes.contextualize_node)
    g.add_node("clarify", nodes.clarify_node)
    g.add_node("router", nodes.router_node)
    g.add_node("refuse", nodes.refuse_node)
    g.add_node("persona_change", nodes.persona_change_node)
    g.add_node("decompose", nodes.decompose_node)
    g.add_node("run_compound", nodes.run_compound_node)
    g.add_node("synthesize", nodes.synthesize_node)
    g.add_node("retrieve", nodes.retrieve_node)
    g.add_node("sql_gen", nodes.sql_gen_node)
    g.add_node("validate", nodes.validate_node)
    g.add_node("execute", nodes.execute_node)
    g.add_node("mask", nodes.mask_node)
    g.add_node("report", nodes.report_node)
    g.add_node("graceful_fail", nodes.graceful_fail_node)

    g.add_edge(START, "contextualize")
    g.add_conditional_edges(
        "contextualize",
        nodes.route_after_contextualize,
        {"router": "router", "clarify": "clarify"},
    )
    g.add_edge("clarify", END)
    g.add_conditional_edges(
        "router",
        nodes.route_after_router,
        {
            "decompose": "decompose",
            "refuse": "refuse",
            "persona_change": "persona_change",
        },
    )
    g.add_edge("refuse", END)
    g.add_edge("persona_change", END)
    g.add_conditional_edges(
        "decompose",
        nodes.route_after_decompose,
        {"retrieve": "retrieve", "run_compound": "run_compound"},
    )
    g.add_edge("run_compound", "synthesize")
    g.add_edge("synthesize", END)
    g.add_edge("retrieve", "sql_gen")
    g.add_conditional_edges(
        "sql_gen",
        nodes.route_after_sql_gen,
        {"validate": "validate", "graceful_fail": "graceful_fail"},
    )
    g.add_conditional_edges(
        "validate",
        nodes.route_after_validate,
        {"execute": "execute", "sql_gen": "sql_gen", "graceful_fail": "graceful_fail"},
    )
    g.add_conditional_edges(
        "execute",
        nodes.route_after_execute,
        {"mask": "mask", "sql_gen": "sql_gen", "graceful_fail": "graceful_fail"},
    )
    g.add_edge("mask", "report")
    g.add_edge("report", END)
    g.add_edge("graceful_fail", END)

    return g.compile()
