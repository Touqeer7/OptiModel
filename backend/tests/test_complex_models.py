"""Scale, semantic expansion and independent scheduling regressions."""

import pytest
from lxml import etree as ET

from backend.app.bpmn import BPMN, DomainError, complexity, parse, serialize, validate
from backend.app.domain import Edge, Node, Resource, Scenario, Workflow
from backend.app.samples import sample
from backend.app.scheduling import optimize
from backend.app.simulation import simulate, validate_schedule
from backend.app.verification import structured_certificate, verify


def chain(count):
    ids = ["s", *[f"t{i}" for i in range(count)], "e"]
    return Workflow(
        id="large_sequence",
        nodes=[
            Node(id="s", kind="startEvent"),
            *[
                Node(id=ident, kind="task", duration=1, role="Operator", provenance="example")
                for ident in ids[1:-1]
            ],
            Node(id="e", kind="endEvent"),
        ],
        edges=[Edge(id=f"f{i}", source=a, target=b) for i, (a, b) in enumerate(zip(ids, ids[1:]))],
    )


def wide(branches=64, gateway="parallelGateway", separate_ends=False):
    nodes = [Node(id="s", kind="startEvent"), Node(id="fork", kind=gateway)]
    pairs = [("s", "fork")]
    for i in range(branches):
        nodes.append(Node(id=f"t{i}", kind="task", duration=i % 3 + 1, role="Operator"))
        pairs.append(("fork", f"t{i}"))
        if separate_ends:
            nodes.append(Node(id=f"e{i}", kind="endEvent"))
            pairs.append((f"t{i}", f"e{i}"))
        else:
            pairs.append((f"t{i}", "join"))
    if not separate_ends:
        nodes.extend([Node(id="join", kind=gateway), Node(id="e", kind="endEvent")])
        pairs.append(("join", "e"))
    return Workflow(
        id="parallel",
        nodes=nodes,
        edges=[
            Edge(
                id=f"f{i}",
                source=a,
                target=b,
                condition=f"choice {b}" if a == "fork" and gateway == "exclusiveGateway" else None,
            )
            for i, (a, b) in enumerate(pairs)
        ],
    )


def scenario(capacity=2):
    return Scenario(resources=[Resource(role="Operator", capacity=capacity)], solver_seconds=0.2)


def embedded_xml(depth=2):
    def scope(level):
        activity = (
            f'<bpmn:subProcess id="sub{level}">{scope(level + 1)}</bpmn:subProcess>'
            if level < depth
            else '<bpmn:manualTask id="work" name="Inspect item"><bpmn:extensionElements>'
            '<studio:metadata duration="4" role="Operator" provenance="source"/>'
            "</bpmn:extensionElements></bpmn:manualTask>"
        )
        target = f"sub{level}" if level < depth else "work"
        return (
            f'<bpmn:startEvent id="s{level}"/>{activity}<bpmn:endEvent id="e{level}"/>'
            f'<bpmn:sequenceFlow id="in{level}" sourceRef="s{level}" targetRef="{target}"/>'
            f'<bpmn:sequenceFlow id="out{level}" sourceRef="{target}" targetRef="e{level}"/>'
        )

    return (
        f'<bpmn:definitions xmlns:bpmn="{BPMN}" xmlns:studio="urn:optimodel:studio:1" '
        'targetNamespace="urn:complex-tests"><bpmn:process id="embedded">'
        + scope(0)
        + "</bpmn:process></bpmn:definitions>"
    )


@pytest.mark.parametrize("count", [500, 1998])
def test_large_import_verify_simulate_round_trip(count):
    source = chain(count)
    xml = serialize(source)
    restored, _ = parse(xml)
    assert restored.model_dump() == source.model_dump()
    verification = verify(restored)
    assert verification["status"] == "no_counterexample"
    assert verification["method"] == "structural_reduction"
    baseline = simulate(restored, scenario())
    assert baseline["metrics"]["makespan"] == count
    assert len(baseline["schedule"]) == count
    assert len(baseline["critical_path_task_ids"]) == count


def test_thousand_task_solver_retains_feasible_baseline():
    workflow, config = chain(1000), scenario()
    baseline = simulate(workflow, config)
    result = optimize(workflow, config, baseline)
    assert result["status"] in ("optimal", "feasible", "timeout")
    assert result["selected"]["metrics"]["makespan"] == 1000
    validate_schedule(workflow, config, result["selected"]["schedule"], {f"t{i}" for i in range(1000)})


def test_wide_parallel_reduction_avoids_state_explosion():
    workflow = wide()
    limited = verify(workflow, max_states=100)
    assert limited["status"] == "inconclusive"
    result = verify(workflow)
    assert result["status"] == "no_counterexample"
    assert result["certificate"]["matched_gateway_regions"] == 1
    assert result["states"] == 0  # no fabricated state enumeration
    baseline = simulate(workflow, scenario(32))
    assert len(baseline["schedule"]) == 64
    assert baseline["metrics"]["makespan"] >= 3
    assert complexity(workflow)["max_layer_width"] == 64


@pytest.mark.parametrize("key", ["loan", "order", "operations"])
def test_structural_certificate_agrees_with_exhaustive_small_reference(key):
    workflow = Workflow.model_validate(sample(key)["ir"])
    assert structured_certificate(workflow) is not None
    assert verify(workflow)["status"] == "no_counterexample"


def test_mismatched_join_never_receives_structural_certificate():
    workflow = wide(35, gateway="exclusiveGateway")
    next(n for n in workflow.nodes if n.id == "join").kind = "parallelGateway"
    assert structured_certificate(workflow) is None
    result = verify(workflow)
    assert result["status"] == "counterexample"
    assert result["deadlock_count"] > 0


@pytest.mark.parametrize("gateway", ["parallelGateway", "exclusiveGateway"])
def test_multiple_normal_ends_complete_all_active_branches(gateway):
    workflow = wide(2, gateway=gateway, separate_ends=True)
    config = scenario()
    if gateway == "exclusiveGateway":
        config.routes = {
            "fork": next(e.id for e in workflow.edges if e.target == "t1" and e.source == "fork")
        }
    assert not validate(workflow)
    assert verify(workflow)["status"] == "no_counterexample"
    baseline = simulate(workflow, config)
    assert {r["id"] for r in baseline["schedule"]} == ({"t1"} if config.routes else {"t0", "t1"})
    assert baseline["metrics"]["makespan"] == 2
    selected = optimize(workflow, config, baseline)
    assert selected["status"] == "optimal"
    assert selected["selected"]["metrics"]["makespan"] == 2


def test_nested_embedded_subprocesses_preserve_source_task_identity():
    original = embedded_xml(3)
    workflow, diagnostics = parse(original)
    assert len([d for d in diagnostics if d.code == "flattened_subprocess"]) == 3
    assert [n.id for n in workflow.nodes if n.kind == "manualTask"] == ["work"]
    assert sum(n.kind == "intermediateThrowEvent" for n in workflow.nodes) == 6
    assert verify(workflow)["status"] == "no_counterexample"
    baseline = simulate(workflow, scenario())
    assert baseline["schedule"][0]["id"] == "work"
    assert baseline["metrics"]["makespan"] == 4
    assert parse(serialize(workflow))[0].model_dump() == workflow.model_dump()
    assert "subProcess" in original


@pytest.mark.parametrize(
    "insertion",
    [
        "<bpmn:standardLoopCharacteristics/>",
        "<bpmn:multiInstanceLoopCharacteristics/>",
        '<bpmn:boundaryEvent id="boundary" attachedToRef="work"/>',
    ],
)
def test_unsupported_subprocess_semantics_are_not_discarded(insertion):
    xml = embedded_xml(1).replace("</bpmn:subProcess>", insertion + "</bpmn:subProcess>")
    with pytest.raises(DomainError):
        parse(xml)


def test_subprocess_cross_scope_reference_rejected():
    xml = embedded_xml(1).replace('sourceRef="s1" targetRef="work"', 'sourceRef="s0" targetRef="work"')
    with pytest.raises(DomainError, match="scope"):
        parse(xml)


def test_subprocess_start_event_definition_is_not_lost():
    xml = embedded_xml(1).replace(
        '<bpmn:startEvent id="s1"/>',
        '<bpmn:startEvent id="s1"><bpmn:timerEventDefinition id="timer"/></bpmn:startEvent>',
    )
    with pytest.raises(DomainError) as error:
        parse(xml)
    assert any(d.element_id == "timer" for d in error.value.diagnostics)


@pytest.mark.parametrize("kind", ["manualTask", "sendTask", "receiveTask", "scriptTask", "businessRuleTask"])
def test_additional_tasks_are_timed_work_never_executable(kind):
    workflow = chain(1)
    workflow.nodes[1].kind = kind
    xml = serialize(workflow)
    if kind == "scriptTask":
        xml = xml.replace(
            "</bpmn:scriptTask>",
            '<bpmn:script>raise Exception("MUST NEVER RUN")</bpmn:script></bpmn:scriptTask>',
        )
    restored, _ = parse(xml)
    assert simulate(restored, scenario())["metrics"]["makespan"] == 1


def test_explicit_timing_units_round_trip_and_convert_in_scenario():
    workflow = chain(2)
    workflow.time_unit = "hours"
    restored, _ = parse(serialize(workflow))
    assert restored.time_unit == "hours"
    config = scenario()
    config.unit = "minutes"
    assert simulate(restored, config)["metrics"]["makespan"] == 120
    config.unit = "time units"
    with pytest.raises(DomainError, match="explicit source timing"):
        simulate(restored, config)


def test_schedule_validator_rejects_nan_and_missing_selected_tasks():
    workflow, config = chain(2), scenario()
    rows = simulate(workflow, config)["schedule"]
    with pytest.raises(DomainError, match="coverage"):
        validate_schedule(workflow, config, rows[:1], {"t0"})
    rows[0]["start"] = float("nan")
    with pytest.raises(DomainError, match="invariant"):
        validate_schedule(workflow, config, rows, {"t0", "t1"})


def test_nested_source_preserved_through_api_and_capabilities_match_limits(client):
    original = embedded_xml(2)
    project = client.post("/api/v1/projects", json={"name": "Complex import"}).json()
    imported = client.post(
        f"/api/v1/projects/{project['id']}/upload", files={"file": ("nested.bpmn", original.encode())}
    )
    assert imported.status_code == 201, imported.text
    model = imported.json()
    assert model["xml"] == original
    assert model["complexity"]["tasks"] == 1
    checked = client.post(f"/api/v1/models/{model['id']}/validate").json()
    assert checked["verification"]["status"] == "no_counterexample"
    assert client.get("/api/v1/capabilities").json()["limits"]["nodes"] == 2000


def test_import_above_old_one_megabyte_limit(client):
    xml = serialize(chain(1))
    root = ET.fromstring(xml.encode())
    doc = ET.SubElement(root.find(f"{{{BPMN}}}process"), f"{{{BPMN}}}documentation")
    doc.text = "Large model documentation. " * 45_000
    raw = ET.tostring(root)
    assert len(raw) > 1_000_000
    project = client.post("/api/v1/projects", json={"name": "Large source"}).json()
    response = client.post(f"/api/v1/projects/{project['id']}/upload", files={"file": ("large.xml", raw)})
    assert response.status_code == 201, response.text


def test_selected_xor_route_can_improve_parallel_schedule_without_changing_route():
    data = sample("operations")
    workflow = Workflow.model_validate(data["ir"])
    start = next(n for n in workflow.nodes if n.kind == "startEvent")
    end = next(n for n in workflow.nodes if n.kind == "endEvent")
    start.kind = end.kind = "intermediateThrowEvent"
    role = data["config"]["resources"][0]["role"]
    workflow.nodes.extend(
        [
            Node(id="outer_start", kind="startEvent"),
            Node(id="choice", kind="exclusiveGateway"),
            Node(id="bypass", kind="task", duration=1, role=role),
            Node(id="merge", kind="exclusiveGateway"),
            Node(id="outer_end", kind="endEvent"),
        ]
    )
    workflow.edges.extend(
        [
            Edge(id="entry", source="outer_start", target="choice"),
            Edge(id="operations_route", source="choice", target=start.id, condition="full calibration"),
            Edge(id="bypass_route", source="choice", target="bypass", is_default=True),
            Edge(id="exit_operations", source=end.id, target="merge"),
            Edge(id="exit_bypass", source="bypass", target="merge"),
            Edge(id="finish", source="merge", target="outer_end"),
        ]
    )
    config = Scenario.model_validate(data["config"])
    config.routes = {"choice": "operations_route"}
    baseline = simulate(workflow, config)
    assert baseline["metrics"]["makespan"] == 13
    result = optimize(workflow, config, baseline)
    assert result["status"] == "optimal"
    assert result["selected"]["metrics"]["makespan"] == 11
    assert result["selected"]["selected_routes"] == config.routes
    assert "bypass" not in {r["id"] for r in result["selected"]["schedule"]}
    assert not result["bpmn_changed"]


def test_nested_import_runs_and_exports_original_source(client):
    import time

    xml = embedded_xml(2)
    project = client.post("/api/v1/projects", json={"name": "Nested experiment"}).json()
    model = client.post(
        f"/api/v1/projects/{project['id']}/models", json={"name": "Nested", "xml": xml}
    ).json()
    run = client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={
            "model_id": model["id"],
            "mode": "optimize",
            "config": scenario().model_dump(),
        },
    ).json()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        run = client.get(f"/api/v1/runs/{run['id']}").json()
        if run["state"] not in ("queued", "running"):
            break
        time.sleep(0.02)
    assert run["state"] == "succeeded", run
    assert run["result"]["baseline"]["metrics"]["makespan"] == 4
    assert client.get(f"/api/v1/runs/{run['id']}/artifacts/original.bpmn").text == xml


@pytest.mark.parametrize("limit", ["depth", "elements"])
def test_large_xml_still_has_explicit_complexity_limits(limit):
    if limit == "elements":
        body = "<bpmn:documentation/>" * 100_001
    else:
        body = "<bpmn:extensionElements>" * 65 + "</bpmn:extensionElements>" * 65
    xml = f'<bpmn:definitions xmlns:bpmn="{BPMN}">{body}</bpmn:definitions>'
    with pytest.raises(DomainError, match="complexity|nesting"):
        parse(xml)


def test_unsupported_cyclic_file_still_has_a_read_only_graph_assessment(client):
    workflow = chain(2)
    xml = serialize(workflow).replace(
        "</bpmn:process>", '<bpmn:sequenceFlow id="retry" sourceRef="t1" targetRef="t0"/></bpmn:process>'
    )
    response = client.post("/api/v1/inspection", json={"xml": xml})
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["mode"] == "structural_inspection"
    assert not report["executable_analysis_supported"]
    assert report["cyclic_regions"] == 1
    assert report["nodes"] == 4
    assert not client.get("/api/v1/projects").json()


def test_inspection_handles_multiple_processes_and_invalid_references(client):
    xml = f'<definitions xmlns="{BPMN}"><process id="p"><startEvent id="s"/><task id="a"/><sequenceFlow id="f" sourceRef="s" targetRef="missing"/></process><process id="q"><task id="b"/></process></definitions>'
    report = client.post("/api/v1/inspection", json={"xml": xml}).json()
    assert report["processes"] == 2
    assert report["nodes"] == 3
    assert report["reference_issues"][0]["element_id"] == "f"
    assert not report["executable_analysis_supported"]


def test_inspection_uses_same_secure_xml_boundary(client):
    xml = '<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///secret">]><definitions/>'
    assert client.post("/api/v1/inspection", json={"xml": xml}).status_code == 422


@pytest.mark.parametrize("seed", range(16))
def test_nested_region_certificate_agrees_with_complete_token_enumeration(seed):
    import random

    rng = random.Random(seed)
    nodes = [Node(id="s", kind="startEvent"), Node(id="e", kind="endEvent")]
    edges = []

    def connect(a, b, conditional=False):
        edges.append(
            Edge(
                id=f"flow_{len(edges)}",
                source=a,
                target=b,
                condition=f"route to {b}" if conditional else None,
            )
        )

    def region(depth):
        if depth == 0:
            ident = f"task_{len(nodes)}"
            nodes.append(Node(id=ident, kind="task", duration=1, role="Operator"))
            return ident, ident
        kind = rng.choice(["parallelGateway", "exclusiveGateway"])
        fork, join = f"fork_{len(nodes)}", f"join_{len(nodes)}"
        nodes.extend([Node(id=fork, kind=kind), Node(id=join, kind=kind)])
        for _ in range(2):
            first, last = region(depth - 1)
            connect(fork, first, kind == "exclusiveGateway")
            connect(last, join)
        return fork, join

    first, last = region(2)
    connect("s", first)
    connect(last, "e")
    workflow = Workflow(id=f"nested_{seed}", nodes=nodes, edges=edges)
    assert structured_certificate(workflow) is not None
    result = verify(workflow, max_states=5000)
    assert result["method"] == "bounded_reachability"
    assert not result["truncated"]
    assert result["status"] == "no_counterexample"


def test_analytical_lower_bound_certifies_large_sequence_without_search():
    workflow, config = chain(1000), scenario()
    baseline = simulate(workflow, config)
    result = optimize(workflow, config, baseline)
    assert result["method"] == "analytical_lower_bound"
    assert result["status"] == "optimal"
    assert result["best_bound"] == 1000
    assert result["relative_gap"] == 0
    assert result["selected"] == baseline


def test_sub_millisecond_duration_is_not_rounded_to_zero_by_optimizer():
    workflow, config = chain(1), scenario()
    workflow.nodes[1].duration = 1e-12
    baseline = simulate(workflow, config)
    assert optimize(workflow, config, baseline)["status"] == "unsupported"
