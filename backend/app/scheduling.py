"""Fixed-resource RCPSP with CP-SAT over an explicitly selected execution trace."""

from collections import defaultdict

from .domain import Scenario, Workflow
from .graph_tools import execution_graph, task_predecessors
from .simulation import choose_routes, metrics, resource_slots, settings, validate_schedule


def optimize(workflow: Workflow, config: Scenario, baseline: dict) -> dict:
    base = {
        "status": "unsupported",
        "intervention": "fixed_resource_scheduling",
        "selected": baseline,
        "improvement_pct": 0.0,
        "best_bound": None,
        "relative_gap": None,
        "time_limit_seconds": config.solver_seconds,
        "seed": config.seed,
        "resources": [r.model_dump() for r in config.resources],
        "bpmn_changed": False,
    }
    routes = choose_routes(workflow, config)
    g = execution_graph(workflow, routes)
    task_settings = {ident: s for ident, s in settings(workflow, config).items() if ident in g}
    predecessors = task_predecessors(workflow, g)
    base["scope"] = (
        "Fixed-resource scheduling for the same selected trace; routing alternatives are not optimized."
    )
    if baseline.get("selected_routes", {}) != routes:
        raise ValueError("Baseline routing does not match the optimization scenario.")
    validate_schedule(workflow, config, baseline["schedule"], expected_ids=set(task_settings))
    if any(
        round(s.duration * 1000) < 1 or abs(s.duration * 1000 - round(s.duration * 1000)) > 1e-7
        for s in task_settings.values()
    ):
        return {
            **base,
            "explanation": "CP-SAT supports durations with up to three decimal places; durations were not rounded.",
        }
    scale = 1000
    durations = {t: round(s.duration * scale) for t, s in task_settings.items()}
    longest, workloads = {}, defaultdict(int)
    for ident in predecessors:  # predecessor map is in topological order
        longest[ident] = durations[ident] + max((longest[p] for p in predecessors[ident]), default=0)
        workloads[task_settings[ident].role] += durations[ident]
    bound = max(
        [*longest.values(), *[(workloads[r.role] + r.capacity - 1) // r.capacity for r in config.resources]]
    )
    if bound == round(baseline["metrics"]["makespan"] * scale):
        return {
            **base,
            "status": "optimal",
            "method": "analytical_lower_bound",
            "best_bound": bound / scale,
            "relative_gap": 0.0,
            "explanation": "The independently validated baseline attains a proven precedence/resource lower bound for this selected trace. No schedule can finish earlier under these assumptions; solver search was unnecessary.",
        }
    base["method"] = "cp_sat"
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    horizon = sum(durations.values())
    starts, ends, choices, intervals = {}, {}, {}, {}
    slots = resource_slots(config)
    baseline_rows = {s["id"]: s for s in baseline["schedule"]}
    for ident, setting in task_settings.items():
        starts[ident] = model.new_int_var(0, horizon, f"s_{ident}")
        ends[ident] = model.new_int_var(0, horizon, f"e_{ident}")
        model.add(ends[ident] == starts[ident] + durations[ident])
        assignments = []
        for slot in slots[setting.role]:
            present = model.new_bool_var(f"{ident}@{slot}")
            interval = model.new_optional_interval_var(
                starts[ident], durations[ident], ends[ident], present, f"i_{ident}@{slot}"
            )
            intervals.setdefault(slot, []).append(interval)
            choices[ident, slot] = present
            assignments.append(present)
            model.add_hint(present, int(baseline_rows[ident]["resource"] == slot))
        model.add_exactly_one(assignments)
        model.add_hint(starts[ident], round(baseline_rows[ident]["start"] * scale))
        model.add_hint(ends[ident], round(baseline_rows[ident]["finish"] * scale))
    for ident in task_settings:
        for pred in predecessors[ident]:
            model.add(starts[ident] >= ends[pred])
    for slot_intervals in intervals.values():
        model.add_no_overlap(slot_intervals)
    makespan = model.new_int_var(0, horizon, "makespan")
    model.add_max_equality(makespan, list(ends.values()))
    model.add(makespan <= round(baseline["metrics"]["makespan"] * scale))
    model.minimize(makespan)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = config.solver_seconds
    solver.parameters.random_seed = config.seed
    solver.parameters.num_search_workers = 1
    status_code = solver.solve(model)
    status = {
        cp_model.OPTIMAL: "optimal",
        cp_model.FEASIBLE: "feasible",
        cp_model.INFEASIBLE: "infeasible",
        cp_model.UNKNOWN: "timeout",
        cp_model.MODEL_INVALID: "invalid",
    }.get(status_code, "invalid")
    base.update(status=status, wall_seconds=solver.wall_time)
    if status not in ("optimal", "feasible"):
        return {
            **base,
            "explanation": "No validated solver candidate was returned; the baseline is retained.",
        }
    nodes = {n.id: n for n in workflow.nodes}
    rows = []
    for ident, setting in task_settings.items():
        start, finish = solver.value(starts[ident]) / scale, solver.value(ends[ident]) / scale
        ready = max((solver.value(ends[p]) / scale for p in predecessors[ident]), default=0)
        slot = next(slot for slot in slots[setting.role] if solver.value(choices[ident, slot]))
        rows.append(
            {
                "id": ident,
                "name": nodes[ident].name or ident,
                "role": setting.role,
                "resource": slot,
                "duration": setting.duration,
                "ready": ready,
                "start": start,
                "finish": finish,
                "wait": start - ready,
                "provenance": setting.provenance,
            }
        )
    validate_schedule(workflow, config, rows, expected_ids=set(task_settings))
    candidate = {
        "metrics": metrics(rows, config),
        "schedule": sorted(rows, key=lambda r: (r["start"], r["id"])),
        "seed": config.seed,
        "selected_routes": routes,
        "warnings": baseline["warnings"],
    }
    improved = candidate["metrics"]["makespan"] < baseline["metrics"]["makespan"] - 1e-7
    selected = candidate if improved else baseline
    objective = solver.objective_value / scale
    bound = solver.best_objective_bound / scale
    return {
        **base,
        "selected": selected,
        "candidate": candidate,
        "best_bound": bound,
        "relative_gap": max(0, (objective - bound) / objective) if objective else 0,
        "improvement_pct": 100
        * (baseline["metrics"]["makespan"] - selected["metrics"]["makespan"])
        / baseline["metrics"]["makespan"],
        "explanation": "A validated schedule reduced simulated completion time with identical durations, roles and capacities."
        if improved
        else "No makespan improvement found. The baseline is retained; the BPMN is unchanged.",
    }
