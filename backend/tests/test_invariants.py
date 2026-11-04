"""Independent invariants over generated acyclic parallel chains and role assignments."""

import random

import pytest

from backend.app.bpmn import DomainError, parse, serialize
from backend.app.domain import Edge, Node, Resource, Scenario, Workflow
from backend.app.scheduling import optimize
from backend.app.simulation import simulate, validate_schedule


@pytest.mark.parametrize("seed", range(12))
def test_parallel_chains_preserve_tasks_roles_and_resource_intervals(seed):
    rng = random.Random(seed)
    nodes = [
        Node(id="s", kind="startEvent"),
        Node(id="fork", kind="parallelGateway"),
        Node(id="join", kind="parallelGateway"),
        Node(id="e", kind="endEvent"),
    ]
    pairs = [("s", "fork"), ("join", "e")]
    for branch in range(4):
        previous = "fork"
        for index in range(rng.randint(1, 4)):
            ident = f"t_{branch}_{index}"
            nodes.append(
                Node(
                    id=ident,
                    name=ident,
                    kind="task",
                    duration=rng.randint(1, 9),
                    role=rng.choice(["A", "B"]),
                    provenance="example",
                )
            )
            pairs.append((previous, ident))
            previous = ident
        pairs.append((previous, "join"))
    workflow = Workflow(
        id="property_case",
        nodes=nodes,
        edges=[Edge(id=f"f{i}", source=a, target=b) for i, (a, b) in enumerate(pairs)],
    )
    config = Scenario(
        seed=seed,
        resources=[Resource(role="A", capacity=2), Resource(role="B", capacity=1)],
        solver_seconds=0.1,
    )
    baseline = simulate(workflow, config)
    selected = optimize(workflow, config, baseline)
    expected = {n.id for n in nodes if n.kind == "task"}
    assert {r["id"] for r in baseline["schedule"]} == expected
    validate_schedule(workflow, config, baseline["schedule"], expected)
    validate_schedule(workflow, config, selected["selected"]["schedule"], expected)
    assert selected["status"] in ("optimal", "feasible", "timeout")
    assert selected["selected"]["metrics"]["makespan"] <= baseline["metrics"]["makespan"]
    assert baseline["precedence_lower_bound"] <= baseline["metrics"]["makespan"]
    assert simulate(workflow, config) == baseline


def test_nested_tasks_are_not_silently_flattened():
    xml = '<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"><process id="p"><extensionElements/><laneSet id="lanes"><task id="hidden"/></laneSet></process></definitions>'
    with pytest.raises(DomainError) as exc:
        parse(xml)
    assert any(d.code == "nested_scope" and d.element_id == "hidden" for d in exc.value.diagnostics)


def test_serializer_generated_ids_do_not_collide():
    from backend.app.samples import sample

    workflow = Workflow.model_validate(sample("order")["ir"])
    workflow.id = "StudioDefinitions"
    workflow.nodes[2].id = "DI_start"
    for edge in workflow.edges:
        if edge.source == "inventory":
            edge.source = "DI_start"
        if edge.target == "inventory":
            edge.target = "DI_start"
    restored, _ = parse(serialize(workflow))
    assert restored.id == "StudioDefinitions"
