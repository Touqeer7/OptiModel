"""Flow-place Petri net and bounded reachability. No blanket soundness claim."""

from collections import deque
from time import monotonic

from .bpmn import require_valid
from .domain import Workflow


def to_petri(workflow: Workflow) -> dict:
    require_valid(workflow)
    # Keep source BPMN IDs distinct from internal source/sink place names.
    places = ["source", *[f"flow:{e.id}" for e in workflow.edges], "sink"]
    transitions = []
    for node in workflow.nodes:
        incoming = [f"flow:{e.id}" for e in workflow.edges if e.target == node.id]
        outgoing = [f"flow:{e.id}" for e in workflow.edges if e.source == node.id]
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
    places = net["places"]
    index = {p: i for i, p in enumerate(places)}
    transitions = [
        (t, [index[p] for p in t["inputs"]], [index[p] for p in t["outputs"]]) for t in net["transitions"]
    ]
    initial = tuple(int(p == "source") for p in places)
    final = tuple(int(p == "sink") for p in places)
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
        if marking[index["sink"]] and marking != final:
            improper.append(marking)
        if not enabled and marking != final:
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
                if len(parents) >= max_states or sum(nxt) > 64:
                    truncated, reason = True, "state_or_token_limit"
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
    can_complete = {final} if final in parents else set()
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
        "scope": "bounded flow-place reachability for the supported acyclic subset; all XOR choices explored without evaluating business conditions",
        "states": len(parents),
        "truncated": truncated,
        "limit_reason": reason,
        "proper_completion": bool(final in parents and not improper) if not truncated else None,
        "all_states_can_complete": len(can_complete) == len(parents) if not truncated else None,
        "dead_transitions": dead_transitions,
        "deadlock_count": len(deadlocks),
        "counterexample_trace": trace(bad[0]) if bad else [],
        "deadlock_marking": {p: bad[0][i] for i, p in enumerate(places) if bad[0][i]} if bad else {},
        "petri_net": net,
    }
