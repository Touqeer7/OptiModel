"""Chronological, single-case discrete events using sequence-flow tokens."""

import heapq
import math
import random
from collections import defaultdict, deque
from time import monotonic

from .bpmn import require_valid
from .domain import DomainError, Scenario, TASK_KINDS, TaskSetting, Workflow
from .graph_tools import execution_graph, flow_index, task_predecessors


def settings(workflow: Workflow, config: Scenario) -> dict[str, TaskSetting]:
    tasks = {n.id: n for n in workflow.nodes if n.kind in TASK_KINDS}
    unknown = set(config.tasks) - set(tasks)
    if unknown:
        raise DomainError(f"Scenario contains unknown task IDs: {sorted(unknown)}")
    roles = {r.role for r in config.resources}
    result = {}
    for ident, node in tasks.items():
        setting = config.tasks.get(ident)
        if setting is None:
            if node.duration is None or node.role is None:
                raise DomainError(f"{ident}: provide an explicit duration and resource role.")
            duration = node.duration
            if workflow.time_unit != "time units":
                factors = {"minutes": 1, "hours": 60, "days": 1440}
                if config.unit not in factors:
                    raise DomainError(
                        "Choose minutes, hours or days for a model with explicit source timing units."
                    )
                duration *= factors[workflow.time_unit] / factors[config.unit]
            setting = TaskSetting(
                duration=duration,
                role=node.role,
                provenance=node.provenance if node.provenance != "unknown" else "source",
            )
        if setting.role not in roles:
            raise DomainError(f"{ident}: no resource capacity is configured for role {setting.role}.")
        result[ident] = setting
    return result


def choose_routes(workflow: Workflow, config: Scenario) -> dict[str, str]:
    rng = random.Random(config.seed)
    _, outgoing = flow_index(workflow)
    splits = {
        n.id: outgoing[n.id]
        for n in workflow.nodes
        if n.kind == "exclusiveGateway" and len(outgoing[n.id]) > 1
    }
    if (set(config.routes) | set(config.probabilities)) - set(splits):
        raise DomainError("Route settings reference an unknown exclusive split.")
    selected = {}
    for ident, edges in splits.items():
        if ident in config.routes and ident in config.probabilities:
            raise DomainError(f"{ident}: specify a selected route or probabilities, not both.")
        if ident in config.routes:
            choice = config.routes[ident]
            if choice not in edges:
                raise DomainError(f"{ident}: selected route is not an outgoing flow.")
            selected[ident] = choice
        elif ident in config.probabilities:
            probabilities = config.probabilities[ident]
            values = list(probabilities.values())
            if (
                set(probabilities) != set(edges)
                or not all(math.isfinite(p) and 0 <= p <= 1 for p in values)
                or abs(sum(values) - 1) > 1e-9
            ):
                raise DomainError(f"{ident}: supply a probability for every outgoing flow summing to one.")
            selected[ident] = rng.choices(edges, [probabilities[e] for e in edges])[0]
        else:
            raise DomainError(
                f"{ident}: explicitly select a branch or supply routing probabilities. Conditions are not executed."
            )
    return selected


def resource_slots(config: Scenario) -> dict[str, list[str]]:
    return {r.role: [f"{r.role} / {i + 1}" for i in range(r.capacity)] for r in config.resources}


def metrics(schedule: list[dict], config: Scenario) -> dict:
    makespan = max((s["finish"] for s in schedule), default=0)
    busy = defaultdict(float)
    for row in schedule:
        busy[row["role"]] += row["duration"]
    utilization = {
        r.role: busy[r.role] / (makespan * r.capacity) if makespan else 0 for r in config.resources
    }
    cost_known = all(r.cost_per_unit is not None for r in config.resources)
    labor = sum(busy[r.role] * (r.cost_per_unit or 0) for r in config.resources) if cost_known else None
    staffed = (
        sum(makespan * r.capacity * (r.cost_per_unit or 0) for r in config.resources) if cost_known else None
    )
    return {
        "makespan": makespan,
        "unit": config.unit,
        "completed_cases": 1,
        "observed_throughput": None,
        "total_wait": sum(s["wait"] for s in schedule),
        "mean_wait": sum(s["wait"] for s in schedule) / len(schedule) if schedule else 0,
        "utilization_by_role": utilization,
        "busy_labor_cost": labor,
        "staffed_capacity_cost": staffed,
        "cost_unit": "configured currency",
        "task_count": len(schedule),
    }


def simulate(workflow: Workflow, config: Scenario) -> dict:
    require_valid(workflow)
    task_settings = settings(workflow, config)
    routes = choose_routes(workflow, config)
    slots = resource_slots(config)
    free = {role: list(names) for role, names in slots.items()}
    incoming, outgoing = flow_index(workflow)
    nodes = {n.id: n for n in workflow.nodes}
    targets = {e.id: e.target for e in workflow.edges}
    pending = deque(n.id for n in workflow.nodes if n.kind == "startEvent")
    queued = set(pending)
    tokens, ready, running, started, completed, rows, events = {}, {}, [], set(), set(), [], []
    clock, serial = 0.0, 0
    end_ids = {n.id for n in workflow.nodes if n.kind == "endEvent"}
    deadline = monotonic() + 10

    def produce(ident):
        for edge in [routes[ident]] if ident in routes else outgoing[ident]:
            if edge in tokens:
                raise DomainError(f"{ident}: repeated token on a flow is unsupported.")
            tokens[edge] = clock
            if targets[edge] not in queued:
                pending.append(targets[edge])
                queued.add(targets[edge])

    while True:
        if monotonic() > deadline or len(events) > len(workflow.nodes) * 4:
            raise DomainError("Simulation exceeded its event/time budget.")
        while pending:
            ident = pending.popleft()
            queued.remove(ident)
            node = nodes[ident]
            ins = incoming[ident]
            available = [i for i in ins if i in tokens]
            if ident in started:
                if available:
                    raise DomainError(
                        f"{ident}: repeated activation is outside the single-activation subset; review merge gateways."
                    )
                continue
            enabled = node.kind == "startEvent" or (
                bool(available)
                if node.kind == "exclusiveGateway"
                else len(available) == len(ins) and bool(ins)
            )
            if not enabled:
                continue
            consumed = available[:1] if node.kind == "exclusiveGateway" else available
            ready_time = max((tokens.pop(i) for i in consumed), default=clock)
            started.add(ident)
            events.append({"time": clock, "node_id": ident, "event": "enabled"})
            if node.kind in TASK_KINDS:
                ready[ident] = (ready_time, node)
            else:
                completed.add(ident)
                events.append({"time": clock, "node_id": ident, "event": "completed"})
                produce(ident)
        for ident, (ready_time, node) in sorted(list(ready.items()), key=lambda x: (x[1][0], x[0])):
            setting = task_settings[ident]
            if not free[setting.role]:
                continue
            slot = free[setting.role].pop(0)
            row = {
                "id": ident,
                "name": node.name or ident,
                "role": setting.role,
                "resource": slot,
                "duration": setting.duration,
                "ready": ready_time,
                "start": clock,
                "finish": clock + setting.duration,
                "wait": clock - ready_time,
                "provenance": setting.provenance,
            }
            rows.append(row)
            serial += 1
            heapq.heappush(running, (row["finish"], serial, ident, slot, setting.role))
            del ready[ident]
            events.append({"time": clock, "node_id": ident, "event": "started", "resource": slot})
        if not running:
            if end_ids & completed and not tokens and not ready:
                break
            raise DomainError(
                "Selected route deadlocks or leaves residual tokens; review the gateway structure."
            )
        clock = running[0][0]
        while running and running[0][0] == clock:
            _, _, ident, slot, role = heapq.heappop(running)
            free[role].append(slot)
            free[role].sort()
            completed.add(ident)
            events.append({"time": clock, "node_id": ident, "event": "completed", "resource": slot})
            produce(ident)
    import networkx as nx

    trace_graph = execution_graph(workflow, routes)
    lengths, previous = {}, {}
    for ident in nx.topological_sort(trace_graph):
        pred = max(trace_graph.predecessors(ident), key=lambda p: lengths[p], default=None)
        lengths[ident] = (lengths[pred] if pred else 0) + (
            task_settings[ident].duration if ident in task_settings else 0
        )
        previous[ident] = pred
    last = max(end_ids & completed, key=lambda ident: lengths[ident])
    critical_path = []
    while last is not None:
        if last in task_settings:
            critical_path.append(last)
        last = previous[last]
    result = {
        "precedence_lower_bound": max(lengths[ident] for ident in end_ids & completed),
        "critical_path_task_ids": list(reversed(critical_path)),
        "critical_path_scope": "Precedence-only longest path for this selected trace, ignoring resource waits; a lower bound, not a resource-constrained critical-chain proof.",
        "metrics": metrics(rows, config),
        "schedule": sorted(rows, key=lambda s: (s["start"], s["id"])),
        "events": events,
        "selected_routes": routes,
        "seed": config.seed,
        "warnings": [
            "Single-case deterministic experiment; throughput and real-world savings are not measured.",
            "Resource slots are continuously available; no calendars, preemption, or multitasking.",
            "Branch conditions are labels. Explicit scenario choices determine the selected trace.",
        ],
    }
    validate_schedule(
        workflow,
        config,
        result["schedule"],
        expected_ids={ident for ident in trace_graph if ident in task_settings},
        control_times={e["node_id"]: e["time"] for e in events if e["event"] == "completed"},
    )
    return result


def validate_schedule(
    workflow: Workflow,
    config: Scenario,
    rows: list[dict],
    expected_ids: set[str],
    control_times: dict | None = None,
):
    """Independent task, resource, duration, and graph precedence checks for accepted schedules."""
    task_settings = settings(workflow, config)
    g = execution_graph(workflow, choose_routes(workflow, config))
    required = set(task_settings) & set(g)
    if expected_ids != required:
        raise DomainError("Candidate task coverage does not match the selected execution graph.")
    if len(rows) != len(expected_ids) or {s["id"] for s in rows} != expected_ids:
        raise DomainError("Candidate schedule has missing or duplicate tasks.")
    slots = resource_slots(config)
    by_id = {s["id"]: s for s in rows}
    for row in rows:
        setting = task_settings[row["id"]]
        if row["resource"] not in slots[setting.role] or row["role"] != setting.role:
            raise DomainError("Candidate assigns an ineligible resource.")
        if (
            not all(math.isfinite(row[k]) for k in ("start", "finish", "duration", "wait", "ready"))
            or row["start"] < 0
            or row["finish"] <= row["start"]
            or abs(row["duration"] - setting.duration) > 1e-7
            or abs(row["finish"] - row["start"] - setting.duration) > 1e-7
        ):
            raise DomainError("Candidate duration/start invariant failed.")
    for role_slots in slots.values():
        for slot in role_slots:
            assigned = sorted([s for s in rows if s["resource"] == slot], key=lambda s: s["start"])
            if any(a["finish"] > b["start"] + 1e-7 for a, b in zip(assigned, assigned[1:])):
                raise DomainError("Candidate exceeds resource capacity.")
    predecessors = task_predecessors(workflow, g)
    for ident, row in by_id.items():
        for prev in predecessors[ident]:
            if by_id[prev]["finish"] > row["start"] + 1e-7:
                raise DomainError("Candidate violates task precedence.")
    if control_times:
        for row in rows:
            for edge in workflow.edges:
                if (
                    edge.target == row["id"]
                    and edge.source in control_times
                    and control_times[edge.source] > row["start"] + 1e-7
                ):
                    raise DomainError("Candidate started before the required control token.")
