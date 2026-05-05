"""Wire LangGraph nodes into a state machine."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from src.graph import nodes
from src.graph.state import AgentState


def build_graph():
    g = StateGraph(AgentState)

    g.add_node("router", nodes.router_node)
    g.add_node("refuse", nodes.refuse_node)
    g.add_node("retrieve", nodes.retrieve_node)
    g.add_node("sql_gen", nodes.sql_gen_node)
    g.add_node("validate", nodes.validate_node)
    g.add_node("execute", nodes.execute_node)
    g.add_node("mask", nodes.mask_node)
    g.add_node("report", nodes.report_node)
    g.add_node("graceful_fail", nodes.graceful_fail_node)

    g.add_edge(START, "router")
    g.add_conditional_edges(
        "router",
        nodes.route_after_router,
        {"retrieve": "retrieve", "refuse": "refuse"},
    )
    g.add_edge("refuse", END)
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
