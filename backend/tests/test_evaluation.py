"""Analytical marking counts, measurement units, and honest before/after evidence."""

import pytest

from backend.app.bpmn import parse
from backend.app.domain import Scenario, Workflow
from backend.app.evaluation import comparison, initial_evaluation, number, phase, structural_counts
from backend.app.revision import build_revision
from backend.app.samples import sample
from backend.app.scheduling import optimize
from backend.app.simulation import simulate
from backend.app.verification import structured_certificate, verify
from backend.tests.test_api import complete, model, project, start
from backend.tests.test_complex_models import chain, scenario, wide


@pytest.mark.parametrize("kind", ["parallelGateway", "exclusiveGateway"])
@pytest.mark.parametrize("branches", [2, 3, 5, 8])
def test_compositional_count_agrees_with_independent_enumeration(kind, branches):
    workflow = wide(branches, kind)
    expected = 2**branches + 4 if kind == "parallelGateway" else 2 * branches + 4
    assert structured_certificate(workflow)["reachable_markings"] == str(expected)
    enumeration = verify(workflow, max_states=4999, seconds=3)
    assert not enumeration["truncated"]
    assert enumeration["states"] == expected


def test_nested_regions_count_matches_enumeration():
    from backend.app.domain import Edge, Node

    workflow = wide(3)
    workflow.nodes.extend(
        [
            Node(id="x", kind="exclusiveGateway"),
            Node(id="y", kind="exclusiveGateway"),
            Node(id="a", kind="task"),
            Node(id="b", kind="task"),
        ]
    )
    workflow.edges = [e for e in workflow.edges if e.target != "t0"]
    workflow.edges.extend(
        Edge(id=f"nest{i}", source=a, target=b)
        for i, (a, b) in enumerate(
            [("fork", "x"), ("x", "a"), ("x", "b"), ("a", "y"), ("b", "y"), ("y", "t0")]
        )
    )
    assert structured_certificate(workflow)["reachable_markings"] == str(
        verify(workflow, max_states=4999)["states"]
    )


def test_large_counts_are_exact_strings_not_zero_or_float():
    workflow = wide(120)
    evidence = verify(workflow)
    assert evidence["states"] == 0  # proof, not enumeration
    result = structural_counts(workflow, evidence)
    assert result["reachable_states"]["value"] == str(2**120 + 4)
    assert result["reachable_states"]["status"] == "exact"
    assert result["deadlocks"]["value"] == 0
    assert "E+" in number(result["reachable_states"]["value"])
    assert structural_counts(chain(60), verify(chain(60)))["reachable_states"]["value"] == "63"


def test_truncated_counts_are_lower_bounds_not_proof_of_no_deadlocks():
    workflow = wide(3, separate_ends=True)
    result = structural_counts(workflow, verify(workflow, max_states=2))
    assert result["reachable_states"]["status"] == result["deadlocks"]["status"] == "lower_bound"


def test_schedule_metrics_report_actual_wait_tradeoff_not_invented_waste():
    source = sample("operations")
    workflow, config = Workflow.model_validate(source["ir"]), Scenario.model_validate(source["config"])
    baseline = simulate(workflow, config)
    optimization = optimize(workflow, config, baseline)
    _, docs = build_revision(workflow, config, optimization, baseline, source["xml"], [], verify(workflow))
    output = parse(docs["optimized.bpmn"])[0]
    initial = phase(workflow, config, verify(workflow), baseline)
    final = phase(output, config, verify(output), optimization["selected"])
    evaluation = comparison(initial, final, unit=config.unit)
    a, b = initial["metrics"], final["metrics"]
    assert (a["makespan"], b["makespan"]) == (13, 11)
    # Either optimal tie may be selected; the measurements must follow its actual rows.
    actual_wait = sum(row["wait"] for row in optimization["selected"]["schedule"])
    assert a["total_wait"] == 2 and b["total_wait"] == actual_wait
    assert a["avoidable_wait"] == b["avoidable_wait"] == 0
    assert (a["idle_capacity"], b["idle_capacity"], a["avoidable_idle"]) == (6, 2, 4)
    assert b["throughput"] == pytest.approx(1 / 11)
    assert a["utilization_pct"] == pytest.approx(20 / 26 * 100)
    assert b["average_concurrency"] == pytest.approx(20 / 11)
    assert a["max_concurrency"] == b["max_concurrency"] == 2
    assert b["average_wait"] == actual_wait / 4
    assert b["bottleneck_activities"] == 1 and b["bottleneck_roles"] == 1
    assert next(r for r in evaluation["rows"] if r["key"] == "total_wait")["change"] == (
        "+" if actual_wait > 2 else ""
    ) + number(actual_wait - 2)


def test_faster_feasible_schedule_can_increase_waiting():
    import copy
    from backend.app.simulation import metrics, validate_schedule

    source = sample("operations")
    workflow, config = Workflow.model_validate(source["ir"]), Scenario.model_validate(source["config"])
    baseline = simulate(workflow, config)
    selected = copy.deepcopy(baseline)
    timings = {
        "a_short": (7, 9, 0, "Technician / 1"),
        "b_independent": (0, 7, 0, "Technician / 1"),
        "c_chain": (0, 3, 0, "Technician / 2"),
        "d_finish": (3, 11, 3, "Technician / 2"),
    }
    for row in selected["schedule"]:
        row["start"], row["finish"], row["ready"], row["resource"] = timings[row["id"]]
        row["wait"] = row["start"] - row["ready"]
    validate_schedule(workflow, config, selected["schedule"], set(timings))
    selected["metrics"] = metrics(selected["schedule"], config)
    evidence = verify(workflow)
    evaluation = comparison(
        phase(workflow, config, evidence, baseline), phase(workflow, config, evidence, selected)
    )
    rows = {row["key"]: row for row in evaluation["rows"]}
    assert rows["makespan"]["change"] == "-2"
    assert rows["total_wait"]["change"] == "+5"
    assert rows["avoidable_wait"]["initial"] == "0"


def test_adjacent_tasks_do_not_count_as_concurrent_and_unused_capacity_is_idle():
    workflow = chain(2)
    config = scenario(1)
    result = initial_evaluation(workflow, config)
    assert result["initial"]["metrics"]["max_concurrency"] == 1
    assert result["initial"]["metrics"]["average_concurrency"] == 1
    assert result["initial"]["metrics"]["avoidable_wait"] is None


def test_read_only_evaluation_and_exported_comparison_are_consistent(client):
    import json

    p = project(client)
    m, config = model(client, p["id"])
    response = client.post(f"/api/v1/models/{m['id']}/evaluate", json={"config": config})
    assert response.status_code == 200, response.text
    assert response.json()["initial"]["metrics"]["makespan"] == 13
    assert client.get(f"/api/v1/projects/{p['id']}/runs").json() == []
    run = complete(client, start(client, p["id"], m["id"], config)["id"])
    evaluation = run["result"]["performance_evaluation"]
    assert len(evaluation["rows"]) == 14
    assert evaluation["initial"]["metrics"]["makespan"] == 13
    assert evaluation["final"]["metrics"]["makespan"] == 11
    exported = json.loads(client.get(f"/api/v1/runs/{run['id']}/artifacts/results.json").text)
    assert exported["performance_evaluation"] == evaluation
    assert client.get(f"/api/v1/runs/{run['id']}/artifacts/report.pdf").content.startswith(b"%PDF-")


def test_deadlocked_source_retains_na_timings_and_real_deadlock_count(client):
    from backend.app.bpmn import serialize
    from backend.tests.test_revision import ambiguous_deadlock

    p = project(client)
    xml = serialize(ambiguous_deadlock())
    m = client.post(f"/api/v1/projects/{p['id']}/models", json={"name": "Deadlock", "xml": xml}).json()
    evaluation = client.post(f"/api/v1/models/{m['id']}/evaluate", json={}).json()
    assert not evaluation["initial"]["available"]
    assert evaluation["initial"]["metrics"] is None
    assert evaluation["initial"]["deadlocks"]["value"] > 0
    assert next(r for r in evaluation["rows"] if r["key"] == "makespan")["initial"] == "N/A"


def test_repaired_run_never_assigns_repaired_timings_to_initial_source(client):
    from backend.tests.test_automatic import import_workflow, unknown_loan, wait_run

    workflow = unknown_loan()
    next(node for node in workflow.nodes if node.id == "merge").kind = "parallelGateway"
    p, m, _ = import_workflow(client, workflow)
    run = wait_run(
        client, client.post(f"/api/v1/projects/{p['id']}/runs/auto", json={"model_id": m["id"]}).json()["id"]
    )
    assert run["state"] == "succeeded", run
    evaluation = run["result"]["performance_evaluation"]
    assert evaluation["initial"]["metrics"] is None
    assert evaluation["initial"]["deadlocks"]["value"] > 0
    assert evaluation["final"]["deadlocks"]["value"] == 0
    assert evaluation["repaired_baseline"]["available"]
    makespan = next(row for row in evaluation["rows"] if row["key"] == "makespan")
    assert makespan["initial"] == "N/A" and makespan["final"] != "N/A"
