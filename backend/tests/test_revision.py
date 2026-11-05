"""Repair boundaries, independent replay, source identity and revised export contracts."""

import hashlib
import io
import json
import random
import time
import zipfile

import pytest
from lxml import etree as ET

from backend.app import revision as rev
from backend.app.automatic import prepare_scenario
from backend.app.bpmn import BPMN, parse, schema_check, serialize, validate
from backend.app.domain import (
    AutoScenarioInput,
    DomainError,
    Edge,
    Node,
    Resource,
    Scenario,
    TASK_KINDS,
    Workflow,
)
from backend.app.samples import sample
from backend.app.scheduling import optimize
from backend.app.simulation import metrics, simulate, validate_schedule
from backend.app.verification import verify


def data(key="operations"):
    source = sample(key)
    workflow = Workflow.model_validate(source["ir"])
    config = Scenario.model_validate(source["config"])
    return source["xml"], workflow, config


def build(key="operations"):
    xml, workflow, config = data(key)
    baseline = simulate(workflow, config)
    optimization = optimize(workflow, config, baseline)
    summary, documents = rev.build_revision(
        workflow, config, optimization, baseline, xml, [], verify(workflow)
    )
    return workflow, config, baseline, optimization, summary, documents


def ambiguous_deadlock():
    kinds = {
        "s": "startEvent",
        "e": "endEvent",
        "fork": "parallelGateway",
        "left": "exclusiveGateway",
        "right": "exclusiveGateway",
        "join_a": "parallelGateway",
        "join_b": "parallelGateway",
        "merge": "exclusiveGateway",
    }
    nodes = [Node(id=ident, kind=kind) for ident, kind in kinds.items()]
    nodes.extend(Node(id=ident, kind="task", duration=1, role="Worker") for ident in ("la", "lb", "ra", "rb"))
    pairs = [
        ("s", "fork"),
        ("fork", "left"),
        ("fork", "right"),
        ("left", "la"),
        ("left", "lb"),
        ("right", "ra"),
        ("right", "rb"),
        ("la", "join_a"),
        ("ra", "join_a"),
        ("lb", "join_b"),
        ("rb", "join_b"),
        ("join_a", "merge"),
        ("join_b", "merge"),
        ("merge", "e"),
    ]
    return Workflow(
        id="ambiguous_deadlock",
        nodes=nodes,
        edges=[Edge(id=f"f{i}", source=a, target=b) for i, (a, b) in enumerate(pairs)],
    )


def test_revised_execution_plan_reproduces_11_hours_and_preserves_task_facts():
    source, config, baseline, optimization, summary, documents = build()
    plan, _ = parse(documents["optimized.bpmn"])
    replay = simulate(plan, prepare_scenario(plan, AutoScenarioInput(produce_revised_bpmn=False)))
    assert baseline["metrics"]["makespan"] == 13
    assert optimization["selected"]["metrics"]["makespan"] == replay["metrics"]["makespan"] == 11
    assert summary["method"] == "resource_ordered_execution_plan"
    assert summary["optimality_proven"] and summary["relative_gap"] == 0
    assert summary["replay_makespan"] == 11
    assert not schema_check(documents["optimized.bpmn"])
    assert verify(plan)["status"] == "no_counterexample"
    assert plan.resource_pools == config.resources
    assert {n.id: (n.duration, n.role) for n in plan.nodes if n.kind in TASK_KINDS} == {
        n.id: (n.duration, n.role) for n in source.nodes if n.kind in TASK_KINDS
    }
    validate_schedule(
        source,
        config,
        optimization["selected"]["schedule"],
        {n.id for n in source.nodes if n.kind in TASK_KINDS},
    )
    assert summary["optimized_sha256"] == hashlib.sha256(documents["optimized.bpmn"].encode()).hexdigest()
    assert json.loads(documents["changes.json"]) == summary


def test_conditional_plan_is_scoped_and_full_process_keeps_unselected_work():
    source, config, _, _, summary, documents = build("loan")
    full, _ = parse(documents["corrected.bpmn"])
    plan, _ = parse(documents["optimized.bpmn"])
    selected = simulate(source, config)
    expected = {r["id"] for r in selected["schedule"]}
    assert {n.id for n in plan.nodes if n.kind in TASK_KINDS} == expected
    assert {n.id for n in full.nodes if n.kind in TASK_KINDS} == {"review", "approve", "decline"}
    assert set(summary["excluded_task_ids"]) == {"review", "approve", "decline"} - expected
    assert summary["selected_routes"] == selected["selected_routes"]
    assert "selected" in summary["scope"]
    assert any("routing alternatives" in note for note in plan.assumptions)


def test_exported_resource_rates_convert_with_explicit_units_on_reimport():
    _, _, _, _, _, documents = build()
    plan, _ = parse(documents["optimized.bpmn"])
    config = prepare_scenario(plan, AutoScenarioInput(unit="minutes"))
    assert config.resources[0].capacity == 2
    assert config.resources[0].cost_per_unit == 0.5
    assert simulate(plan, config)["metrics"]["makespan"] == 660


def test_closed_xor_split_and_join_deadlock_is_repaired_without_changing_tasks():
    _, workflow, _ = data("loan")
    next(n for n in workflow.nodes if n.id == "merge").kind = "parallelGateway"
    original = workflow.model_dump()
    before = verify(workflow)
    assert before["status"] == "counterexample"
    repaired, checked, changes = rev.repair_deadlocks(workflow, before)
    assert checked["status"] == "no_counterexample"
    assert changes[0]["paired_fork"] == "decision"
    assert changes[0]["before"] == "parallelGateway"
    assert changes[0]["after"] == "exclusiveGateway"
    assert workflow.model_dump() == original
    assert repaired.edges == workflow.edges
    assert [n.model_dump() for n in repaired.nodes if n.kind in TASK_KINDS] == [
        n.model_dump() for n in workflow.nodes if n.kind in TASK_KINDS
    ]


def test_closed_parallel_split_with_xor_join_is_repaired_to_synchronize():
    _, workflow, _ = data("order")
    split = next(n for n in workflow.nodes if n.kind == "parallelGateway")
    join = next(n for n in workflow.nodes if n.kind == "parallelGateway" and n.id != split.id)
    join.kind = "exclusiveGateway"
    before = verify(workflow)
    assert before["status"] == "counterexample"
    _, checked, changes = rev.repair_deadlocks(workflow, before)
    assert checked["status"] == "no_counterexample"
    assert changes[0]["after"] == "parallelGateway"


def test_repairs_preserve_original_vendor_extensions_and_patch_only_gateway_type():
    _, workflow, _ = data("loan")
    next(n for n in workflow.nodes if n.id == "merge").kind = "parallelGateway"
    root = ET.fromstring(serialize(workflow).encode())
    process = root.find(f"{{{BPMN}}}process")
    ext = process.find(f"{{{BPMN}}}extensionElements")
    if ext is None:
        ext = ET.SubElement(process, f"{{{BPMN}}}extensionElements")
    ET.SubElement(ext, "{urn:vendor}audit", protected="yes").text = "Keep vendor data"
    xml = ET.tostring(root, encoding="unicode")
    repaired, _, changes = rev.repair_deadlocks(workflow, verify(workflow))
    corrected = rev.corrected_source(xml, repaired, changes)
    restored_root = ET.fromstring(corrected.encode())
    assert restored_root.find(".//{urn:vendor}audit").text == "Keep vendor data"
    assert parse(corrected)[0].model_dump() == repaired.model_dump()
    assert root.find(f'.//{{{BPMN}}}parallelGateway[@id="merge"]') is not None
    assert restored_root.find(f'.//{{{BPMN}}}exclusiveGateway[@id="merge"]') is not None


def test_unstructured_deadlock_is_not_fixed_by_guessing_business_routing():
    workflow = ambiguous_deadlock()
    assert not validate(workflow)
    before = verify(workflow)
    assert before["status"] == "counterexample"
    with pytest.raises(DomainError, match="No verified automatic deadlock repair"):
        rev.repair_deadlocks(workflow, before)


def test_feasible_schedule_never_claims_proved_optimality_without_a_matching_bound():
    xml, workflow, config = data()
    baseline = simulate(workflow, config)
    optimization = optimize(workflow, config, baseline)
    optimization.update(status="feasible", best_bound=0, relative_gap=1)
    summary, documents = rev.build_revision(
        workflow, config, optimization, baseline, xml, [], verify(workflow)
    )
    assert documents["optimized.bpmn"]
    assert not summary["optimality_proven"]
    assert summary["optimization_status"] == "feasible"


def test_replay_can_tighten_a_feasible_schedule_and_attain_the_proved_bound():
    xml, workflow, config = data()
    baseline = simulate(workflow, config)
    optimization = optimize(workflow, config, baseline)
    delayed = [dict(row) for row in optimization["selected"]["schedule"]]
    for row in delayed:
        row["start"] += 1
        row["finish"] += 1
        row["wait"] += 1
    optimization["selected"] = {
        **optimization["selected"],
        "schedule": delayed,
        "metrics": metrics(delayed, config),
    }
    optimization["status"] = "feasible"
    assert optimization["selected"]["metrics"]["makespan"] == 12
    summary, _ = rev.build_revision(workflow, config, optimization, baseline, xml, [], verify(workflow))
    assert summary["selected_makespan"] == 11
    assert summary["optimality_proven"]
    assert optimization["method"] == "cp_sat_bound_and_replay"


def test_invalid_schedule_is_not_disguised_as_an_annotation_fallback():
    xml, workflow, config = data()
    baseline = simulate(workflow, config)
    optimization = optimize(workflow, config, baseline)
    optimization["selected"]["schedule"][0]["resource"] = "Nonexistent worker"
    with pytest.raises(DomainError, match="ineligible"):
        rev.build_revision(workflow, config, optimization, baseline, xml, [], verify(workflow))


def test_rewrite_budget_fallback_is_explicit_and_keeps_full_process(monkeypatch):
    monkeypatch.setattr(rev, "MAX_NODES", 3)
    source, _, _, _, summary, documents = build()
    plan, _ = parse(documents["optimized.bpmn"])
    assert summary["method"] == "schedule_annotations_only"
    assert "budget" in summary["fallback_reason"]
    assert summary["replay_makespan"] is None
    assert len(plan.nodes) == len(source.nodes)
    assert plan.edges == source.edges


def test_svg_escapes_task_names_and_contains_no_executable_markup():
    _, workflow, config = data("order")
    next(n for n in workflow.nodes if n.kind in TASK_KINDS).name = '<script>alert("test")</script>'
    baseline = simulate(workflow, config)
    plan, _ = rev.execution_plan(workflow, config, baseline)
    svg = rev.diagram_svg(plan)
    root = ET.fromstring(svg.encode())
    assert not root.findall(".//{http://www.w3.org/2000/svg}script")
    assert "&lt;script&gt;" in svg


@pytest.mark.parametrize("seed", range(6))
def test_generated_parallel_chain_plans_preserve_feasibility_and_resource_limits(seed):
    rng = random.Random(seed)
    nodes = [
        Node(id="s", kind="startEvent"),
        Node(id="fork", kind="parallelGateway"),
        Node(id="join", kind="parallelGateway"),
        Node(id="e", kind="endEvent"),
    ]
    pairs = [("s", "fork"), ("join", "e")]
    for branch in range(3):
        previous = "fork"
        for index in range(3):
            ident = f"task_{branch}_{index}"
            nodes.append(Node(id=ident, kind="task", duration=rng.randint(1, 5), role=rng.choice(["A", "B"])))
            pairs.append((previous, ident))
            previous = ident
        pairs.append((previous, "join"))
    workflow = Workflow(
        id=f"generated_{seed}",
        nodes=nodes,
        edges=[Edge(id=f"f{i}", source=a, target=b) for i, (a, b) in enumerate(pairs)],
    )
    config = Scenario(
        resources=[Resource(role="A", capacity=2), Resource(role="B", capacity=1)], solver_seconds=0.2
    )
    baseline = simulate(workflow, config)
    optimization = optimize(workflow, config, baseline)
    summary, documents = rev.build_revision(
        workflow, config, optimization, baseline, serialize(workflow), [], verify(workflow)
    )
    restored, _ = parse(documents["optimized.bpmn"])
    replay = simulate(restored, prepare_scenario(restored))
    assert summary["output_verification"]["status"] == "no_counterexample"
    assert replay["metrics"]["makespan"] == optimization["selected"]["metrics"]["makespan"]
    assert replay["metrics"]["makespan"] <= baseline["metrics"]["makespan"]
    validate_schedule(
        workflow, config, optimization["selected"]["schedule"], {n.id for n in nodes if n.kind == "task"}
    )


def test_acyclic_and_induction_agrees_with_small_bounded_enumeration():
    _, workflow, _ = data("operations")
    # Expand one parallel branch serially to exceed the proof threshold without extra choices.
    edge = next(e for e in workflow.edges if e.source == "start")
    target = edge.target
    edge.target = "padding0"
    for index in range(8):
        workflow.nodes.append(Node(id=f"padding{index}", kind="task", duration=1, role="Technician"))
        workflow.edges.append(
            Edge(
                id=f"padding_flow{index}",
                source=f"padding{index}",
                target=f"padding{index + 1}" if index < 7 else target,
            )
        )
    exact = verify(workflow)
    enumeration = verify(workflow, max_states=4999)
    assert exact["method"] == "acyclic_and_induction"
    assert enumeration["method"] == "bounded_reachability"
    assert exact["status"] == enumeration["status"] == "no_counterexample"


def wait(client, ident):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = client.get(f"/api/v1/runs/{ident}").json()
        if result["state"] not in ("queued", "running"):
            return result
        time.sleep(0.02)
    pytest.fail("Revision job exceeded test budget.")


def test_revision_artifacts_are_real_reimportable_and_in_bundle(client):
    xml, workflow, config = data()
    project = client.post("/api/v1/projects", json={"name": "Revised output"}).json()
    model = client.post(
        f"/api/v1/projects/{project['id']}/models", json={"name": "Source", "xml": xml}
    ).json()
    response = client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"model_id": model["id"], "mode": "optimize", "config": config.model_dump()},
    )
    assert response.status_code == 202, response.text
    run = wait(client, response.json()["id"])
    assert run["state"] == "succeeded", run
    paths = {a["name"]: a["url"] for a in run["result"]["artifacts"]}
    for name in ("corrected.bpmn", "optimized.bpmn", "optimized.svg", "changes.json"):
        assert client.get(paths[name]).status_code == 200
    assert client.get(paths["original.bpmn"]).text == xml
    plan_xml = client.get(paths["optimized.bpmn"]).text
    assert plan_xml != xml
    replay_model = client.post(
        f"/api/v1/projects/{project['id']}/models", json={"name": "Reimported plan", "xml": plan_xml}
    )
    assert replay_model.status_code == 201, replay_model.text
    loaded = Workflow.model_validate(replay_model.json()["ir"])
    assert simulate(loaded, prepare_scenario(loaded))["metrics"]["makespan"] == 11
    bundle = zipfile.ZipFile(io.BytesIO(client.get(paths["bundle.zip"]).content))
    assert set(paths) - {"bundle.zip"} == set(bundle.namelist())
    assert bundle.read("original.bpmn").decode() == xml
    assert json.loads(bundle.read("changes.json"))["optimality_proven"]


def test_unrepairable_automatic_run_publishes_no_fake_final_diagram(client):
    xml = serialize(ambiguous_deadlock())
    project = client.post("/api/v1/projects", json={"name": "Uncertain intent"}).json()
    model = client.post(
        f"/api/v1/projects/{project['id']}/models", json={"name": "Source", "xml": xml}
    ).json()
    response = client.post(f"/api/v1/projects/{project['id']}/runs/auto", json={"model_id": model["id"]})
    assert response.status_code == 202, response.text
    run = wait(client, response.json()["id"])
    assert run["state"] == "failed", run
    assert run["result"] is None
    assert "No verified automatic deadlock repair" in run["error"]
    assert client.get(f"/api/v1/runs/{run['id']}/artifacts/optimized.bpmn").status_code == 404
