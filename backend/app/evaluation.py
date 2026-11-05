"""Comparable, scoped performance measurements for source and revised BPMN models."""

from collections import defaultdict
from decimal import Decimal

from .domain import DomainError
from .simulation import simulate
from .verification import structured_certificate, verify

DEFINITIONS = [
    "Reachable states count distinct flow-place Petri-net markings, including initial and final markings. Exact compositional counts apply only to reducible single-entry/exit models. Bounded searches report lower bounds when interrupted.",
    "Deadlock count counts reachable non-final markings with no enabled transition. A truncated search gives a lower bound; zero found is not proof of zero. Structural proofs can establish zero without enumerating states.",
    "Bottleneck criterion: an activity waits more than 0.0000001 time units for an eligible resource. Activities and distinct role pools are counted separately. This queueing indicator does not detect every possible throughput constraint.",
    "Time wasted is reported as demonstrated avoidable waiting and demonstrated avoidable idle capacity, separately: positive reductions against the executable reference schedule under identical resources. Zero means no further reduction demonstrated, not global optimality. Total waiting and total idle capacity are also shown; neither is automatically all avoidable.",
    "Total execution time is makespan from process time zero to the last task completion. A source model with a verification counterexample is not assigned a successful execution time.",
    "Throughput is completed simulated cases divided by the observation period [0, makespan]. This is a single-case simulated completion rate, not a measured or steady-state business throughput estimate.",
    "Resource utilization is busy slot-time divided by available slot-time times 100. Availability assumes continuous capacity over [0, makespan]. Idle capacity is available minus busy slot-time, including unused role pools.",
    "Average waiting time is total resource queue waiting divided by executed task instances. Waiting uses original process dependencies, before resource-order constraints are encoded into the revised BPMN.",
    "Concurrency is the observed maximum and time-weighted average number of simultaneously running independent activities, using half-open intervals [start, finish). It is not the theoretical maximum permitted by the graph.",
    "Structural counts cover all source branch alternatives. A revised execution plan can cover only the recorded route; a smaller reachable-state count alone is not evidence of better performance or equivalent business behavior.",
]


def structural_counts(workflow, verification):
    evidence = verification
    method = evidence.get("method", "bounded_reachability")
    if method == "bounded_reachability" and not evidence["truncated"]:
        states = {"value": str(evidence["states"]), "status": "exact", "method": method}
    else:
        certificate = structured_certificate(workflow)
        if certificate:
            states = {
                "value": certificate["reachable_markings"],
                "status": "exact",
                "method": "compositional_count",
            }
        else:
            # Force enumeration rather than the proof fast path; keep its bounded scope explicit.
            if method != "bounded_reachability":
                evidence = verify(workflow, max_states=4999, seconds=0.5)
            states = {
                "value": str(evidence["states"]),
                "status": "lower_bound" if evidence["truncated"] else "exact",
                "method": "bounded_reachability",
            }
    deadlocks = {
        "value": verification["deadlock_count"],
        "status": "lower_bound" if verification["truncated"] else "exact",
        "method": method,
    }
    return {"reachable_states": states, "deadlocks": deadlocks}


def phase(workflow, config, verification, simulation=None, reason=None):
    result = {
        **structural_counts(workflow, verification),
        "verification_status": verification["status"],
        "available": simulation is not None,
        "unavailable_reason": reason,
        "metrics": None,
        "resources": [],
        "bottleneck_activities": [],
        "bottleneck_roles": [],
    }
    if simulation is None:
        return result
    rows = simulation["schedule"]
    duration = simulation["metrics"]["makespan"]
    busy = sum(row["duration"] for row in rows)
    wait = sum(row["wait"] for row in rows)
    changes = defaultdict(int)
    for row in rows:
        changes[row["start"]] += 1
        changes[row["finish"]] -= 1
    running = peak = 0
    times = sorted(changes)
    for i, time in enumerate(times):
        running += changes[time]
        if i + 1 < len(times) and times[i + 1] > time:
            peak = max(peak, running)
    queued = [row for row in rows if row["wait"] > 1e-7]
    for resource in config.resources:
        work = sum(row["duration"] for row in rows if row["role"] == resource.role)
        available = duration * resource.capacity
        result["resources"].append(
            {
                "role": resource.role,
                "slots": resource.capacity,
                "busy_time": work,
                "available_time": available,
                "idle_time": max(0, available - work),
                "utilization_pct": 100 * work / available if available else None,
            }
        )
    available = sum(r["available_time"] for r in result["resources"])
    result["bottleneck_activities"] = [
        {"id": row["id"], "name": row["name"], "role": row["role"], "wait": row["wait"]} for row in queued
    ]
    result["bottleneck_roles"] = sorted({row["role"] for row in queued})
    completed = simulation["metrics"].get("completed_cases", 1)
    result["metrics"] = {
        "bottleneck_activities": len(queued),
        "bottleneck_roles": len(result["bottleneck_roles"]),
        "total_wait": wait,
        "average_wait": wait / len(rows) if rows else None,
        "idle_capacity": max(0, available - busy),
        "avoidable_wait": None,
        "avoidable_idle": None,
        "makespan": duration,
        "throughput": completed / duration if duration else None,
        "completed_cases": completed,
        "observation_period": duration,
        "utilization_pct": 100 * busy / available if available else None,
        "max_concurrency": peak,
        "average_concurrency": busy / duration if duration else None,
        "task_instances": len(rows),
    }
    return result


def number(value):
    if value is None:
        return "N/A"
    if isinstance(value, str):
        return value if len(value) <= 18 else f"{Decimal(value):.4E}"
    if value and abs(value) < 0.0001:
        return f"{value:.4E}"
    return f"{value:,.4f}".rstrip("0").rstrip(".") if value != int(value) else f"{int(value):,}"


def count_text(count):
    return (">= " if count["status"] == "lower_bound" else "") + number(count["value"])


def comparison(initial, final=None, repaired_baseline=None, unit="time units"):
    reference = repaired_baseline or initial
    if final and reference["available"] and final["available"]:
        for key, total in (("avoidable_wait", "total_wait"), ("avoidable_idle", "idle_capacity")):
            reference["metrics"][key] = max(0, reference["metrics"][total] - final["metrics"][total])
            final["metrics"][key] = 0
    specs = [
        ("reachable_states", "Reachable states", "markings"),
        ("deadlocks", "Deadlock count", "states"),
        ("bottleneck_activities", "Bottleneck count: activities", "activities"),
        ("bottleneck_roles", "Bottleneck count: resource pools", "role pools"),
        ("avoidable_wait", "Time wasted: demonstrated avoidable waiting", unit),
        ("avoidable_idle", "Time wasted: demonstrated avoidable idle capacity", f"slot-{unit}"),
        ("total_wait", "Total resource waiting", unit),
        ("idle_capacity", "Total idle capacity", f"slot-{unit}"),
        ("makespan", "Total execution time", unit),
        ("throughput", "Throughput: simulated completion rate", f"cases / {unit}"),
        ("utilization_pct", "Resource utilization", "%"),
        ("average_wait", "Average waiting time", unit),
        ("max_concurrency", "Degree of concurrency: maximum", "activities"),
        ("average_concurrency", "Degree of concurrency: average", "activities"),
    ]
    rows = []
    for key, label, units in specs:
        structural = key in ("reachable_states", "deadlocks")

        def value(stage):
            if stage is None:
                return "N/A"
            return count_text(stage[key]) if structural else number((stage["metrics"] or {}).get(key))

        delta = "N/A"
        if final and not structural:
            a, b = (reference["metrics"] or {}).get(key), (final["metrics"] or {}).get(key)
            if a is not None and b is not None:
                delta = ("+" if b > a else "") + number(b - a)
                if key == "utilization_pct":
                    delta += " pp"
        if final and structural and initial[key]["status"] == final[key]["status"] == "exact":
            change = int(final[key]["value"]) - int(initial[key]["value"])
            delta = ("+" if change > 0 else "") + number(str(change))
        rows.append(
            {
                "key": key,
                "label": label,
                "unit": units,
                "initial": value(initial),
                "repaired_baseline": value(repaired_baseline),
                "final": value(final),
                "change": delta,
            }
        )
    return {
        "unit": unit,
        "initial": initial,
        "final": final,
        "repaired_baseline": repaired_baseline,
        "rows": rows,
        "definitions": DEFINITIONS,
        "change_reference": "Repaired baseline for timing; initial source for structural counts"
        if repaired_baseline
        else "Initial source",
        "notes": [
            "N/A means unavailable, not zero. Timing uses the recorded scenario and selected route; structural analysis explores all alternatives within its declared scope.",
            "Large counts use rounded scientific notation in the table; full exact decimal integers are preserved in results.json. Utilization changes use percentage points (pp).",
            "Changes are final minus reference; positive waiting changes are regressions even if makespan improves. Avoidable-time rows show demonstrated reductions, not a proof that all waste is eliminated.",
        ],
    }


def initial_evaluation(workflow, config):
    verification = verify(workflow)
    simulation, reason = None, None
    if verification["status"] == "counterexample":
        reason = (
            "Initial BPMN has a verification counterexample; no successful timing is assigned before repair."
        )
    else:
        try:
            simulation = simulate(workflow, config)
        except DomainError as exc:
            reason = str(exc)
    result = comparison(phase(workflow, config, verification, simulation, reason), unit=config.unit)
    result["scenario_mode"] = config.execution_mode
    result["assumptions"] = config.automatic_assumptions
    return result
