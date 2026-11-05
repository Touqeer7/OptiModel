"""Automatic runs are reproducible, disclosed demonstrations and retain source identity."""

import time

import pytest

from backend.app.automatic import prepare_scenario
from backend.app.bpmn import serialize
from backend.app.domain import AutoScenarioInput, DomainError, Resource, TASK_KINDS, Workflow
from backend.app.samples import sample
from backend.app.simulation import simulate


def unknown_loan():
    workflow = Workflow.model_validate(sample("loan")["ir"])
    for node in workflow.nodes:
        if node.kind in TASK_KINDS:
            node.duration, node.role, node.provenance = None, None, "unknown"
    return workflow


def wait_run(client, ident):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        run = client.get(f"/api/v1/runs/{ident}").json()
        if run["state"] not in ("queued", "running"):
            return run
        time.sleep(0.02)
    pytest.fail("Automatic run exceeded test time budget.")


def import_workflow(client, workflow):
    project = client.post("/api/v1/projects", json={"name": "Automatic demonstration"}).json()
    xml = serialize(workflow)
    response = client.post(
        f"/api/v1/projects/{project['id']}/models", json={"name": "Automatic model", "xml": xml}
    )
    assert response.status_code == 201, response.text
    return project, response.json(), xml


def test_missing_inputs_are_filled_with_recorded_demo_assumptions():
    workflow = unknown_loan()
    original = workflow.model_dump()
    config = prepare_scenario(workflow)
    assert config.execution_mode == "automatic_demo"
    assert config.unit == "time units"
    assert all(
        t.duration == 1 and t.role == "Demo worker" and t.provenance == "assumed"
        for t in config.tasks.values()
    )
    assert config.resources == [Resource(role="Demo worker", capacity=1)]
    assert all(r.cost_per_unit is None for r in config.resources)
    assert any("not measured" in note for note in config.automatic_assumptions)
    assert workflow.model_dump() == original
    assert prepare_scenario(workflow) == config
    assert simulate(workflow, config)["metrics"]["task_count"] == 2


def test_automatic_routing_uses_declared_default_then_first_source_branch():
    workflow = unknown_loan()
    branches = [e for e in workflow.edges if e.source == "decision"]
    for edge in branches:
        edge.is_default, edge.condition = False, None
    config = prepare_scenario(workflow)
    assert config.routes == {"decision": branches[0].id}
    assert any("first outgoing branch" in note for note in config.automatic_assumptions)
    branches[1].is_default = True
    config = prepare_scenario(workflow)
    assert config.routes == {"decision": branches[1].id}
    assert any("declared default" in note for note in config.automatic_assumptions)


def test_supplied_values_are_preserved_including_incomplete_task_role():
    workflow = unknown_loan()
    data = AutoScenarioInput.model_validate(
        {
            "unit": "minutes",
            "resources": [{"role": "Reviewer", "capacity": 2, "cost_per_unit": 3}],
            "tasks": {"review": {"duration": 5, "role": "Reviewer"}, "approve": {"duration": 4, "role": ""}},
            "routes": {"decision": "flow_3"},
        }
    )
    config = prepare_scenario(workflow, data)
    assert config.tasks["review"].duration == 5
    assert config.tasks["review"].role == "Reviewer"
    assert config.tasks["review"].provenance == "user"
    assert config.tasks["approve"].duration == 4
    assert config.tasks["approve"].role == "Demo worker"
    assert config.tasks["approve"].provenance == "assumed"
    assert config.resources[0].capacity == 2
    assert config.resources[0].cost_per_unit == 3
    assert config.routes["decision"] == "flow_3"
    assert simulate(workflow, config)["metrics"]["makespan"] == 9


def test_known_source_timings_convert_once_and_capacities_are_retained():
    workflow = Workflow.model_validate(sample("order")["ir"])
    workflow.time_unit = "hours"
    config = prepare_scenario(
        workflow,
        AutoScenarioInput.model_validate(
            {
                "unit": "minutes",
                "resources": [{"role": "Operations", "capacity": 2}],
            }
        ),
    )
    assert sorted(t.duration for t in config.tasks.values()) == [120, 240, 420]
    assert simulate(workflow, config)["metrics"]["makespan"] == 540
    assert all(t.provenance == "example" for t in config.tasks.values())


def test_supplied_seeded_probabilities_are_not_replaced_with_a_demo_route():
    workflow = unknown_loan()
    data = AutoScenarioInput(probabilities={"decision": {"flow_3": 0.4, "flow_4": 0.6}}, seed=17)
    config = prepare_scenario(workflow, data)
    assert not config.routes
    assert config.probabilities == data.probabilities
    assert simulate(workflow, config) == simulate(workflow, config)


@pytest.mark.parametrize(
    "overrides",
    [
        {"tasks": {"unknown": {"duration": 1}}},
        {"routes": {"decision": "unknown"}},
        {"routes": {"not_a_split": "flow_3"}},
        {"resources": [{"role": "Duplicate", "capacity": 1}, {"role": "Duplicate", "capacity": 1}]},
    ],
)
def test_invalid_explicit_overrides_are_not_silently_replaced(overrides):
    with pytest.raises(DomainError):
        prepare_scenario(unknown_loan(), AutoScenarioInput.model_validate(overrides))


def test_automatic_api_creates_real_persistent_run_and_preserves_original_xml(client):
    project, model, xml = import_workflow(client, unknown_loan())
    response = client.post(f"/api/v1/projects/{project['id']}/runs/auto", json={"model_id": model["id"]})
    assert response.status_code == 202, response.text
    run = wait_run(client, response.json()["id"])
    assert run["state"] == "succeeded", run
    assert run["config"]["execution_mode"] == "automatic_demo"
    assert run["result"]["baseline"]["metrics"]["makespan"] == 2
    assert run["result"]["assumptions"] == [
        *model["ir"]["assumptions"],
        *run["config"]["automatic_assumptions"],
        run["result"]["revision"]["scope"],
    ]
    assert client.get(f"/api/v1/runs/{run['id']}/artifacts/original.bpmn").text == xml
    exported = client.get(f"/api/v1/runs/{run['id']}/artifacts/results.json").json()
    assert exported["config"]["automatic_assumptions"] == run["config"]["automatic_assumptions"]
    assert "assumed" in client.get(f"/api/v1/runs/{run['id']}/artifacts/schedule.csv").text
    assert client.get(f"/api/v1/runs/{run['id']}/artifacts/report.pdf").status_code == 200


def test_auto_endpoint_preserves_sample_capacity_and_13_hour_baseline(client):
    data = sample("operations")
    project, model, _ = import_workflow(client, Workflow.model_validate(data["ir"]))
    supplied = {
        k: v for k, v in data["config"].items() if k not in ("execution_mode", "automatic_assumptions")
    }
    response = client.post(
        f"/api/v1/projects/{project['id']}/runs/auto", json={"model_id": model["id"], "config": supplied}
    )
    assert response.status_code == 202, response.text
    run = wait_run(client, response.json()["id"])
    assert run["state"] == "succeeded", run
    assert run["config"]["resources"][0]["capacity"] == 2
    assert run["result"]["baseline"]["metrics"]["makespan"] == 13


def test_automatic_run_repairs_a_verified_closed_xor_and_join_mismatch(client):
    workflow = unknown_loan()
    next(n for n in workflow.nodes if n.id == "merge").kind = "parallelGateway"
    project, model, _ = import_workflow(client, workflow)
    response = client.post(f"/api/v1/projects/{project['id']}/runs/auto", json={"model_id": model["id"]})
    assert response.status_code == 202, response.text
    run = wait_run(client, response.json()["id"])
    assert run["state"] == "succeeded", run
    assert run["result"]["source_verification"]["status"] == "counterexample"
    assert run["result"]["verification"]["status"] == "no_counterexample"
    assert run["result"]["revision"]["repaired_deadlock"]
    assert run["result"]["revision"]["changes"][0]["node_id"] == "merge"


def test_automatic_endpoint_enforces_model_project_ownership(client):
    _, model, _ = import_workflow(client, unknown_loan())
    other = client.post("/api/v1/projects", json={"name": "Other"}).json()
    response = client.post(f"/api/v1/projects/{other['id']}/runs/auto", json={"model_id": model["id"]})
    assert response.status_code == 404
    assert not client.get(f"/api/v1/projects/{other['id']}/runs").json()


def test_optional_edits_refresh_automatic_run_notes(client):
    project, model, _ = import_workflow(client, unknown_loan())
    automatic = client.post(
        f"/api/v1/projects/{project['id']}/runs/auto", json={"model_id": model["id"]}
    ).json()
    assert wait_run(client, automatic["id"])["state"] == "succeeded"
    edited = automatic["config"]
    edited["tasks"]["review"]["duration"] = 7
    edited["tasks"]["review"]["provenance"] = "user"
    response = client.post(
        f"/api/v1/projects/{project['id']}/runs", json={"model_id": model["id"], "config": edited}
    )
    assert response.status_code == 202, response.text
    run = wait_run(client, response.json()["id"])
    assert run["state"] == "succeeded", run
    assert run["result"]["baseline"]["metrics"]["makespan"] == 8
    assert not any(
        note.startswith("review:") and "duration = 1" in note
        for note in run["config"]["automatic_assumptions"]
    )
