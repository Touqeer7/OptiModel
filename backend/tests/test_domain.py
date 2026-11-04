from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.bpmn import BPMN, DomainError, parse, schema_check, serialize, validate
from backend.app.domain import Edge, Node, Resource, Scenario, Workflow
from backend.app.samples import sample
from backend.app.scheduling import optimize
from backend.app.simulation import simulate, validate_schedule
from backend.app.verification import verify

ROOT = Path(__file__).resolve().parents[2]


def sequence():
    return Workflow(
        id="seq",
        name="Sequence 4 + 3",
        nodes=[
            Node(id="s", kind="startEvent"),
            Node(id="a", kind="task", duration=4, role="R", provenance="example"),
            Node(id="b", kind="task", duration=3, role="R", provenance="example"),
            Node(id="e", kind="endEvent"),
        ],
        edges=[
            Edge(id="f1", source="s", target="a"),
            Edge(id="f2", source="a", target="b"),
            Edge(id="f3", source="b", target="e"),
        ],
    )


def parallel():
    w = Workflow.model_validate(sample("order")["ir"])
    w.nodes = [n for n in w.nodes if n.id != "dispatch"]
    w.edges = [e for e in w.edges if e.source != "dispatch"]
    next(e for e in w.edges if e.target == "dispatch").target = "end"
    return w


def config(role="R", capacity=2):
    return Scenario(resources=[Resource(role=role, capacity=capacity)])


def test_sequence_reference_7():
    result = simulate(sequence(), config())
    assert result["metrics"]["makespan"] == 7
    assert [(r["id"], r["start"], r["finish"]) for r in result["schedule"]] == [("a", 0, 4), ("b", 4, 7)]
    assert result["metrics"]["observed_throughput"] is None


def test_bpmn_flow_ids_cannot_collide_with_internal_petri_places():
    workflow = sequence()
    workflow.edges[0].id = "source"
    workflow.edges[1].id = "sink"
    result = verify(workflow)
    assert result["status"] == "no_counterexample"
    net = result["petri_net"]
    assert len(net["places"]) == len(set(net["places"]))
    assert net["place_sources"]["flow:source"] == "source"
    assert net["place_sources"]["flow:sink"] == "sink"


@pytest.mark.parametrize("capacity,expected", [(2, 7), (1, 11)])
def test_parallel_reference(capacity, expected):
    result = simulate(parallel(), config("Operations", capacity))
    assert result["metrics"]["makespan"] == expected
    assert len(result["schedule"]) == 2


@pytest.mark.parametrize("choice,executed,completion", [("flow_3", "approve", 7), ("flow_4", "decline", 5)])
def test_xor_executes_only_selected_branch(choice, executed, completion):
    w = Workflow.model_validate(sample("loan")["ir"])
    c = Scenario(resources=[Resource(role="Analyst", capacity=1)], routes={"decision": choice})
    result = simulate(w, c)
    assert {r["id"] for r in result["schedule"]} == {"review", executed}
    assert result["metrics"]["makespan"] == completion
    optimized = optimize(w, c, result)
    assert optimized["status"] == "optimal"
    assert optimized["selected"]["selected_routes"] == {"decision": choice}
    assert {r["id"] for r in optimized["selected"]["schedule"]} == {"review", executed}


def test_xor_has_no_invented_probabilities_or_business_rule_execution():
    w = Workflow.model_validate(sample("loan")["ir"])
    with pytest.raises(DomainError, match="explicitly select"):
        simulate(w, config("Analyst"))
    c = Scenario(
        resources=[Resource(role="Analyst", capacity=1)],
        probabilities={"decision": {"flow_3": 0.4, "flow_4": 0.6}},
        seed=17,
    )
    assert simulate(w, c) == simulate(w, c)


@pytest.mark.parametrize("branch_metadata", ["unnamed", "named", "default"])
def test_xor_without_conditions_imports_with_warnings_and_requires_routing(branch_metadata):
    workflow = Workflow.model_validate(sample("loan")["ir"])
    branches = [e for e in workflow.edges if e.source == "decision"]
    for edge in branches:
        edge.condition = None
        edge.is_default = False
        edge.name = ""
    if branch_metadata == "named":
        branches[0].name, branches[1].name = "Yes", "No"
    if branch_metadata == "default":
        branches[1].is_default = True
    assert not validate(workflow)
    restored, findings = parse(serialize(workflow))
    warnings = [d for d in findings if d.code == "missing_condition"]
    assert len(warnings) == (1 if branch_metadata == "default" else 2)
    assert all(d.severity == "warning" for d in warnings)
    assert [e.model_dump() for e in restored.edges] == [e.model_dump() for e in workflow.edges]
    assert verify(restored)["status"] == "no_counterexample"
    config = Scenario(resources=[Resource(role="Analyst", capacity=1)])
    with pytest.raises(DomainError, match="explicitly select"):
        simulate(restored, config)
    config.routes = {"decision": "flow_4"}
    baseline = simulate(restored, config)
    assert baseline["metrics"]["makespan"] == 5
    assert optimize(restored, config, baseline)["status"] == "optimal"


@pytest.mark.parametrize(
    "probabilities",
    [
        {"flow_3": 0.5},
        {"flow_3": 0.5, "flow_4": 0.8},
        {"flow_3": -1, "flow_4": 2},
        {"flow_3": float("nan"), "flow_4": 1},
    ],
)
def test_bad_probabilities_rejected(probabilities):
    w = Workflow.model_validate(sample("loan")["ir"])
    with pytest.raises((DomainError, ValidationError)):
        c = Scenario(
            resources=[Resource(role="Analyst", capacity=1)], probabilities={"decision": probabilities}
        )
        simulate(w, c)


def test_missing_durations_and_skills_are_not_filled():
    w = sequence()
    w.nodes[1].duration = None
    with pytest.raises(DomainError, match="explicit duration"):
        simulate(w, config())
    w.nodes[1].duration = 4
    with pytest.raises(DomainError, match="no resource capacity"):
        simulate(w, config("Unavailable"))


@pytest.mark.parametrize("key", ["order", "loan", "operations"])
def test_examples_round_trip_schema_and_seed(key):
    s = sample(key)
    w, warnings = parse(s["xml"])
    assert [n.model_dump() for n in w.nodes] == s["ir"]["nodes"]
    assert [e.model_dump() for e in w.edges] == s["ir"]["edges"]
    assert not schema_check(s["xml"])
    c = Scenario.model_validate(s["config"])
    assert simulate(w, c) == simulate(w, c)
    assert verify(w)["status"] == "no_counterexample"
    assert verify(w)["soundness"] == "not_claimed"


def test_truncation_is_inconclusive():
    result = verify(parallel(), max_states=1)
    assert result["status"] == "inconclusive"
    assert result["truncated"]
    assert result["all_states_can_complete"] is None


def test_xor_join_does_not_become_and_join():
    w = Workflow.model_validate(sample("loan")["ir"])
    net = verify(w)["petri_net"]
    assert len([t for t in net["transitions"] if t["node_id"] == "merge"]) == 2
    next(n for n in w.nodes if n.id == "merge").kind = "parallelGateway"
    result = verify(w)
    assert result["status"] == "counterexample"
    assert result["deadlock_count"] > 0
    assert result["counterexample_trace"][0] == "start"
    assert result["all_states_can_complete"] is False
    with pytest.raises(DomainError, match="deadlocks"):
        simulate(w, Scenario.model_validate(sample("loan")["config"]))


def test_independent_schedule_validator_rejects_overlap_and_precedence():
    w = sequence()
    c = config()
    rows = simulate(w, c)["schedule"]
    rows[1]["start"] = 1
    rows[1]["finish"] = 4
    with pytest.raises(DomainError, match="capacity|precedence"):
        validate_schedule(w, c, rows, {"a", "b"})
    rows[1]["resource"] = "magical worker"
    with pytest.raises(DomainError, match="ineligible"):
        validate_schedule(w, c, rows, {"a", "b"})


def test_real_fixed_resource_solver_improvement():
    s = sample("operations")
    w = Workflow.model_validate(s["ir"])
    c = Scenario.model_validate(s["config"])
    before = c.model_dump()
    baseline = simulate(w, c)
    result = optimize(w, c, baseline)
    assert baseline["metrics"]["makespan"] == 13
    assert result["status"] == "optimal"
    assert result["selected"]["metrics"]["makespan"] == 11
    assert result["best_bound"] == 11
    assert result["relative_gap"] == 0
    assert c.model_dump() == before
    assert result["resources"] == before["resources"]
    assert not result["bpmn_changed"]
    assert {r["id"]: r["duration"] for r in baseline["schedule"]} == {
        r["id"]: r["duration"] for r in result["selected"]["schedule"]
    }
    validate_schedule(w, c, result["selected"]["schedule"], {r["id"] for r in baseline["schedule"]})


def test_no_improvement_retains_baseline():
    w = sequence()
    c = config()
    b = simulate(w, c)
    result = optimize(w, c, b)
    assert result["status"] == "optimal"
    assert result["selected"] == b
    assert result["improvement_pct"] == 0


def test_solver_precision_limit_does_not_change_durations():
    w = sequence()
    w.nodes[1].duration = 1.12345
    c = config()
    b = simulate(w, c)
    assert optimize(w, c, b)["status"] == "unsupported"
    assert b["schedule"][0]["duration"] == 1.12345


@pytest.mark.parametrize(
    "xml,match",
    [
        ("<broken>", "Malformed"),
        ('<!DOCTYPE x [<!ENTITY x SYSTEM "file:///secret">]><definitions/>', "DTD"),
        ('<definitions xmlns="other"/>', "BPMN 2.0"),
        ("x" * 10_000_001, "10 MB"),
    ],
)
def test_hostile_xml(xml, match):
    with pytest.raises(DomainError, match=match):
        parse(xml)


@pytest.mark.parametrize(
    "kind",
    [
        "inclusiveGateway",
        "eventBasedGateway",
        "complexGateway",
        "subProcess",
        "boundaryEvent",
        "intermediateCatchEvent",
    ],
)
def test_unsupported_elements_have_ids(kind):
    xml = serialize(sequence()).replace("</bpmn:process>", f'<bpmn:{kind} id="unsupported"/></bpmn:process>')
    with pytest.raises(DomainError) as exc:
        parse(xml)
    assert any(d.element_id == "unsupported" for d in exc.value.diagnostics)


def test_loop_duplicate_and_dangling_diagnostics():
    w = sequence()
    w.edges[1].target = "missing"
    assert validate(w)[0].code == "dangling_flow"
    w = sequence()
    w.nodes[1].id = "s"
    assert validate(w)[0].code == "duplicate_id"
    w = sequence()
    w.edges.append(Edge(id="loop", source="b", target="a"))
    assert any(d.code == "unsupported_loop" for d in validate(w))


def test_declared_flow_mismatch_rejected():
    xml = serialize(sequence()).replace(
        "<bpmn:incoming>f1</bpmn:incoming>", "<bpmn:incoming>f3</bpmn:incoming>"
    )
    with pytest.raises(DomainError, match="declarations"):
        parse(xml)


def test_unknown_duration_is_not_extracted_from_task_name():
    xml = serialize(sequence()).replace('<studio:task duration="4.0" role="R" provenance="example"/>', "")
    # Attribute order is implementation-defined; remove metadata with lxml explicitly.
    from lxml import etree as ET

    root = ET.fromstring(xml.encode())
    task = root.find(f".//{{{BPMN}}}task")
    for ext in list(task):
        if ext.tag == f"{{{BPMN}}}extensionElements":
            task.remove(ext)
    task.set("name", "Work (4 minutes)")
    parsed, warnings = parse(ET.tostring(root, encoding="unicode"))
    assert parsed.nodes[1].duration is None
    assert any(d.code == "missing_assumptions" for d in warnings)


@pytest.mark.parametrize("filename", ["frontend/1.xml", "frontend/2.xml", "diagram_1.bpmn"])
def test_original_samples_are_preserved_and_importable(filename):
    xml = (ROOT / filename).read_text(encoding="utf-8")
    w, _ = parse(xml)
    assert len(w.nodes) >= 3
    if filename.endswith(".bpmn"):
        assert all(n.duration is None for n in w.nodes if n.kind == "task")


def test_resource_limits_and_nonfinite_duration():
    with pytest.raises(ValidationError):
        Node(id="t", kind="task", duration=float("inf"))
    with pytest.raises(ValidationError):
        Scenario(resources=[Resource(role="R", capacity=1), Resource(role="R", capacity=1)])


def test_cost_definitions_and_idle_not_waste():
    c = Scenario(resources=[Resource(role="R", capacity=2, cost_per_unit=10)])
    result = simulate(sequence(), c)
    assert result["metrics"]["busy_labor_cost"] == 70
    assert result["metrics"]["staffed_capacity_cost"] == 140
    assert result["metrics"]["utilization_by_role"]["R"] == 0.5
    assert "time_wasted" not in result["metrics"]


def test_solver_timeout_falls_back_without_fabricated_improvement(monkeypatch):
    from types import SimpleNamespace
    from ortools.sat.python import cp_model

    class TimedOut:
        parameters = SimpleNamespace()
        wall_time = 0.01

        def solve(self, model):
            return cp_model.UNKNOWN

    monkeypatch.setattr(cp_model, "CpSolver", TimedOut)
    data = sample("operations")
    w = Workflow.model_validate(data["ir"])
    c = Scenario.model_validate(data["config"])
    baseline = simulate(w, c)
    result = optimize(w, c, baseline)
    assert result["status"] == "timeout"
    assert result["selected"] == baseline
    assert result["improvement_pct"] == 0
    assert result["best_bound"] is None
