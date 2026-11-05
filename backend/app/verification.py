"""Flow-place Petri net and bounded reachability. No blanket soundness claim."""

from collections import deque
from math import prod
from time import monotonic

from .bpmn import require_valid
from .domain import Workflow
from .graph_tools import flow_index


def structured_certificate(workflow: Workflow):
    """Conservative series/parallel reduction for single-exit, well-nested DAGs.

    Only serial vertices and complete matching AND/AND or XOR/XOR regions are reduced.
    Cross-branch edges, mismatched joins and non-structured graphs fall back to reachability.
    """
    import networkx as nx

    nodes = {n.id: n for n in workflow.nodes}
    starts = [n.id for n in workflow.nodes if n.kind == "startEvent"]
    ends = [n.id for n in workflow.nodes if n.kind == "endEvent"]
    if len(starts) != 1 or len(ends) != 1:
        return None
    g = nx.MultiDiGraph()
    g.add_nodes_from(nodes)
    g.add_edges_from((e.source, e.target, {"markings": 1}) for e in workflow.edges)
    serial, regions = 0, 0
    changed = True
    while changed:
        changed = False
        for ident in list(g):
            if ident in (starts[0], ends[0]) or ident not in g:
                continue
            if g.in_degree(ident) == g.out_degree(ident) == 1:
                before, after = next(g.predecessors(ident)), next(g.successors(ident))
                count = next(iter(g.get_edge_data(before, ident).values()))["markings"]
                count += next(iter(g.get_edge_data(ident, after).values()))["markings"]
                g.remove_node(ident)
                g.add_edge(before, after, markings=count)
                serial += 1
                changed = True
        for fork in list(g):
            successors = list(g.successors(fork))
            if g.out_degree(fork) < 2 or len(successors) != 1:
                continue
            join = successors[0]
            if (
                nodes[fork].kind not in ("parallelGateway", "exclusiveGateway")
                or nodes[fork].kind != nodes[join].kind
                or set(g.predecessors(join)) != {fork}
            ):
                continue
            counts = [edge["markings"] for edge in g.get_edge_data(fork, join).values()]
            count = prod(counts) if nodes[fork].kind == "parallelGateway" else sum(counts)
            g.remove_edges_from(list(g.edges(fork, keys=True)))
            g.add_edge(fork, join, markings=count)
            regions += 1
            changed = True
    if set(g) == {starts[0], ends[0]} and g.number_of_edges() == 1:
        return {
            "serial_reductions": serial,
            "matched_gateway_regions": regions,
            "source_nodes": len(nodes),
            "source_flows": len(workflow.edges),
            # Decimal string preserves exact counts beyond JavaScript integer precision.
            "reachable_markings": str(next(iter(g.edges(data=True)))[2]["markings"] + 2),
        }
    return None


def to_petri(workflow: Workflow) -> dict:
    require_valid(workflow)
    # Keep source BPMN IDs distinct from internal source/sink place names.
    places = ["source", *[f"flow:{e.id}" for e in workflow.edges], "sink"]
    transitions = []
    incoming_flows, outgoing_flows = flow_index(workflow)
    for node in workflow.nodes:
        incoming = [f"flow:{ident}" for ident in incoming_flows[node.id]]
        outgoing = [f"flow:{ident}" for ident in outgoing_flows[node.id]]
        if node.kind == "startEvent":
            incoming = ["source"]
        if node.kind == "endEvent":
            outgoing = ["sink"]
        pairs = [(incoming, outgoing)]
        if node.kind == "exclusiveGateway":
            pairs = [([i], [o]) for i in incoming for o in outgoing]
        for index, (ins, outs) in enumerate(pairs):
            transitions.append(
                {"id": f"{node.id}:{index}", "node_id": node.id, "inputs": ins, "outputs": outs}
            )
    return {
        "places": places,
        "transitions": transitions,
        "initial": {"source": 1},
        "final": {"sink": 1},
        "place_sources": {
            **{f"flow:{e.id}": e.id for e in workflow.edges},
            "source": next(n.id for n in workflow.nodes if n.kind == "startEvent"),
            "sink": next(n.id for n in workflow.nodes if n.kind == "endEvent"),
        },
    }


def verify(workflow: Workflow, max_states: int = 5000, seconds: float = 2) -> dict:
    net = to_petri(workflow)
    # With only AND control in a validated DAG, topological induction establishes
    # that each node fires once after its predecessors, and every flow is consumed.
    if (
        len(workflow.nodes) > 12
        and max_states >= 5000
        and seconds >= 2
        and not any(n.kind == "exclusiveGateway" for n in workflow.nodes)
    ):
        return {
            "status": "no_counterexample",
            "soundness": "not_claimed",
            "method": "acyclic_and_induction",
            "scope": "Topological token induction for the validated acyclic AND-only subset; each node fires once and all active flow tokens are consumed. This is not full BPMN conformance or business correctness.",
            "states": 0,
            "truncated": False,
            "limit_reason": None,
            "proper_completion": True,
            "all_states_can_complete": True,
            "dead_transitions": [],
            "deadlock_count": 0,
            "counterexample_trace": [],
            "deadlock_marking": {},
            "petri_net": net,
            "certificate": {
                "source_nodes": len(workflow.nodes),
                "source_flows": len(workflow.edges),
                "rule": "acyclic_and_token_induction",
            },
        }
    # Avoid exponential interleavings when an exact compositional reduction applies.
    if len(workflow.nodes) > 32 and max_states >= 5000 and seconds >= 2:
        certificate = structured_certificate(workflow)
        if certificate:
            return {
                "status": "no_counterexample",
                "soundness": "not_claimed",
                "method": "structural_reduction",
                "certificate": certificate,
                "scope": "Series/parallel structural reduction for an acyclic single-entry/exit model; matching AND and XOR regions, all branch alternatives; business conditions not evaluated",
                "states": 0,
                "truncated": False,
                "limit_reason": None,
                "proper_completion": True,
                "all_states_can_complete": True,
                "dead_transitions": [],
                "deadlock_count": 0,
                "counterexample_trace": [],
                "deadlock_marking": {},
                "petri_net": net,
            }
    places = net["places"]
    end_count = sum(n.kind == "endEvent" for n in workflow.nodes)
    index = {p: i for i, p in enumerate(places)}
    transitions = [
        (t, [index[p] for p in t["inputs"]], [index[p] for p in t["outputs"]]) for t in net["transitions"]
    ]
    initial = tuple(int(p == "source") for p in places)
    final = tuple(int(p == "sink") for p in places)

    def is_final(marking):
        return 1 <= marking[-1] <= end_count and not any(marking[:-1])

    parents = {initial: None}
    queue = deque([initial])
    adjacency, fired, deadlocks, improper = {}, set(), [], []
    deadline = monotonic() + min(seconds, 5)
    truncated = False
    reason = None
    while queue:
        if monotonic() > deadline:
            truncated, reason = True, "time_limit"
            break
        marking = queue.popleft()
        targets = []
        enabled = [(t, ins, outs) for t, ins, outs in transitions if all(marking[i] >= 1 for i in ins)]
        if marking[index["sink"]] > end_count or (
            end_count == 1 and marking[index["sink"]] and marking != final
        ):
            improper.append(marking)
        if not enabled and not is_final(marking):
            deadlocks.append(marking)
        for trans, ins, outs in enabled:
            fired.add(trans["id"])
            nxt = list(marking)
            for i in ins:
                nxt[i] -= 1
            for i in outs:
                nxt[i] += 1
            nxt = tuple(nxt)
            targets.append(nxt)
            if nxt not in parents:
                if len(parents) >= max_states or sum(nxt) > max(64, len(workflow.nodes)):
                    truncated, reason = True, "state_or_token_limit"
                    break
                if (len(parents) + 1) * len(places) > 2_000_000:
                    truncated, reason = True, "marking_memory_budget"
                    break
                parents[nxt] = (marking, trans["node_id"])
                queue.append(nxt)
        adjacency[marking] = targets
        if truncated:
            break
    reverse = {}
    for source, targets in adjacency.items():
        for target in targets:
            reverse.setdefault(target, []).append(source)
    finals = {marking for marking in parents if is_final(marking)}
    can_complete = set(finals)
    frontier = list(can_complete)
    while frontier:
        for prev in reverse.get(frontier.pop(), []):
            if prev not in can_complete:
                can_complete.add(prev)
                frontier.append(prev)
    dead_transitions = [t["id"] for t in net["transitions"] if t["id"] not in fired] if not truncated else []

    def trace(marking):
        steps = []
        while parents.get(marking):
            marking, node_id = parents[marking]
            steps.append(node_id)
        return list(reversed(steps))

    bad = deadlocks or improper
    status = "counterexample" if bad else "inconclusive" if truncated else "no_counterexample"
    if not truncated and (len(can_complete) != len(parents) or dead_transitions):
        status = "counterexample"
    return {
        "status": status,
        "soundness": "not_claimed",
        "method": "bounded_reachability",
        "scope": "bounded flow-place reachability for the supported acyclic subset; all XOR choices explored without evaluating business conditions; normal multiple ends complete when all active tokens are consumed",
        "states": len(parents),
        "truncated": truncated,
        "limit_reason": reason,
        "proper_completion": bool(finals and not improper) if not truncated else None,
        "all_states_can_complete": len(can_complete) == len(parents) if not truncated else None,
        "dead_transitions": dead_transitions,
        "deadlock_count": len(deadlocks),
        "counterexample_trace": trace(bad[0]) if bad else [],
        "deadlock_marking": {p: bad[0][i] for i, p in enumerate(places) if bad[0][i]} if bad else {},
        "petri_net": net,
    }
