"""Reproducible automatic demo planning; assumptions never become source facts."""

from .bpmn import require_valid
from .domain import AutoScenarioInput, DomainError, Resource, Scenario, TASK_KINDS, TaskSetting, Workflow
from .graph_tools import flow_index
from .simulation import choose_routes, settings

DEMO_NOTICE = "Automatic demo simulation. Missing inputs use disclosed assumptions; results are illustrative, not measured business performance."


def prepare_scenario(workflow: Workflow, supplied: AutoScenarioInput | None = None) -> Scenario:
    require_valid(workflow)
    supplied = supplied or AutoScenarioInput()
    tasks = {n.id: n for n in workflow.nodes if n.kind in TASK_KINDS}
    if set(supplied.tasks) - set(tasks):
        raise DomainError("Automatic scenario contains unknown task IDs.")
    if len({r.role for r in supplied.resources}) != len(supplied.resources):
        raise DomainError("Resource roles must be unique.")
    unit = supplied.unit or workflow.time_unit
    factors = {"minutes": 1, "hours": 60, "days": 1440}
    if workflow.time_unit in factors and unit == "time units":
        unit = workflow.time_unit
    notes = [DEMO_NOTICE]
    if unit == "time units":
        notes.append("No physical time unit was supplied. Durations are expressed in generic time units.")
    planned = {}
    for ident, node in tasks.items():
        override = supplied.tasks.get(ident)
        duration = override.duration if override and override.duration is not None else node.duration
        role = (override.role.strip() if override and override.role else None) or node.role
        assumed = []
        if duration is None:
            duration = 1.0
            assumed.append(f"duration = 1 {unit}")
        elif (
            not (override and override.duration is not None)
            and workflow.time_unit in factors
            and unit in factors
        ):
            duration *= factors[workflow.time_unit] / factors[unit]
        if not role:
            role = "Demo worker"
            assumed.append("role = Demo worker")
        provenance = override.provenance if override else node.provenance
        if assumed:
            notes.append(f"{ident}: assumed {', '.join(assumed)}.")
            provenance = "assumed"
        elif provenance == "assumed":
            notes.append(f"{ident}: retained demo setting, duration = {duration:g} {unit}, role = {role}.")
        elif provenance == "unknown":
            provenance = "source"
        planned[ident] = TaskSetting(duration=duration, role=role, provenance=provenance)
    resources = {r.role: r.model_copy() for r in [*workflow.resource_pools, *supplied.resources]}
    supplied_roles = {r.role for r in supplied.resources}
    if workflow.time_unit in factors and unit in factors:
        for role, resource in resources.items():
            if role not in supplied_roles and resource.cost_per_unit is not None:
                resource.cost_per_unit *= factors[unit] / factors[workflow.time_unit]
    for role in sorted({t.role for t in planned.values()} - set(resources)):
        resources[role] = Resource(role=role, capacity=1)
        notes.append(f"{role}: assumed one continuously available resource slot; cost is unknown.")
    if len(resources) > 64 or sum(r.capacity for r in resources.values()) > 64:
        raise DomainError(
            "Automatic simulation supports at most 64 resource slots. Reduce the configured roles/capacities before running."
        )
    for resource in supplied.resources:
        notes.append(f"Scenario capacity: {resource.role} has {resource.capacity} slot(s).")
    for resource in workflow.resource_pools:
        if resource.role not in {r.role for r in supplied.resources}:
            notes.append(f"Source scenario capacity: {resource.role} has {resource.capacity} slot(s).")
    _, outgoing = flow_index(workflow)
    edges = {e.id: e for e in workflow.edges}
    routes = dict(supplied.routes)
    for node in workflow.nodes:
        if node.kind != "exclusiveGateway" or len(outgoing[node.id]) < 2:
            continue
        if node.id in routes:
            notes.append(
                f"{node.id}: retained selected route {routes[node.id]}; conditions are not executed."
            )
        elif node.id in supplied.probabilities:
            notes.append(f"{node.id}: supplied route probabilities are sampled with seed {supplied.seed}.")
        else:
            choices = outgoing[node.id]
            selected = next((ident for ident in choices if edges[ident].is_default), choices[0])
            routes[node.id] = selected
            rule = (
                "declared default" if edges[selected].is_default else "first outgoing branch in source order"
            )
            notes.append(
                f"{node.id}: demo route {selected} selected using the {rule}; business conditions are not evaluated."
            )
    config = Scenario(
        produce_revised_bpmn=supplied.produce_revised_bpmn,
        unit=unit,
        seed=supplied.seed,
        solver_seconds=supplied.solver_seconds,
        execution_mode="automatic_demo",
        automatic_assumptions=notes,
        resources=list(resources.values()),
        tasks=planned,
        routes=routes,
        probabilities=supplied.probabilities,
    )
    settings(workflow, config)
    choose_routes(workflow, config)
    return config
