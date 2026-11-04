"""Indexed graph operations shared by simulation and independently checked schedules."""

from collections import defaultdict

import networkx as nx

from .domain import TASK_KINDS, Workflow


def flow_index(workflow: Workflow):
    incoming, outgoing = defaultdict(list), defaultdict(list)
    for edge in workflow.edges:
        incoming[edge.target].append(edge.id)
        outgoing[edge.source].append(edge.id)
    return incoming, outgoing


def execution_graph(workflow: Workflow, routes: dict[str, str] | None = None):
    g = nx.DiGraph()
    g.add_nodes_from(n.id for n in workflow.nodes)
    for edge in workflow.edges:
        if not routes or edge.source not in routes or routes[edge.source] == edge.id:
            g.add_edge(edge.source, edge.target)
    start = next(n.id for n in workflow.nodes if n.kind == "startEvent")
    return g.subgraph(nx.descendants(g, start) | {start}).copy()


def task_predecessors(workflow: Workflow, g: nx.DiGraph):
    """Nearest upstream tasks; their transitive closure enforces all task precedence."""
    task_ids = {n.id for n in workflow.nodes if n.kind in TASK_KINDS}
    frontier, predecessors = {}, {}
    for ident in nx.topological_sort(g):
        previous = set().union(*(frontier[p] for p in g.predecessors(ident)))
        if ident in task_ids:
            predecessors[ident] = previous
            frontier[ident] = {ident}
        else:
            frontier[ident] = previous
    return predecessors
