"""Validated join repairs and resource-ordered BPMN execution plans.

No task is removed from the full corrected process. The execution plan is explicitly
for one selected route; its additional dependencies encode the chosen resource order.
"""

import hashlib
import json
from collections import defaultdict
from html import escape
from time import monotonic

import networkx as nx
from lxml import etree as ET

from .bpmn import BPMN, STUDIO, graph, layout, parse, read_xml, require_valid, schema_check, serialize
from .domain import DomainError, Edge, Node, Scenario, TASK_KINDS, Workflow
from .graph_tools import execution_graph, task_predecessors
from .limits import MAX_EDGES, MAX_NODES
from .simulation import choose_routes, metrics, settings, simulate, validate_schedule
from .verification import verify


def _dominates(mapping, ancestor, child):
    while child in mapping:
        if child == ancestor:
            return True
        parent = mapping[child]
        if parent == child:
            break
        child = parent
    return False


def _mismatched_regions(workflow):
    g = graph(workflow)
    nodes = {n.id: n for n in workflow.nodes}
    start = next(n.id for n in workflow.nodes if n.kind == "startEvent")
    dom = nx.immediate_dominators(g, start)
    exit_node = object()
    extended = g.copy()
    for node in workflow.nodes:
        if node.kind == "endEvent":
            extended.add_edge(node.id, exit_node)
    post = nx.immediate_dominators(extended.reverse(copy=False), exit_node)
    for join, node in nodes.items():
        if node.kind not in ("parallelGateway", "exclusiveGateway") or g.in_degree(join) < 2:
            continue
        fork = dom.get(join)
        while fork in nodes and fork != dom.get(fork):
            if nodes[fork].kind in ("parallelGateway", "exclusiveGateway") and g.out_degree(fork) > 1:
                break
            fork = dom.get(fork)
        if fork not in nodes or g.out_degree(fork) < 2 or nodes[fork].kind == node.kind:
            continue
        if not _dominates(post, join, fork):
            continue
        region = (nx.descendants(g, fork) & nx.ancestors(g, join)) | {fork, join}
        if any(set(g.predecessors(v)) - region for v in region - {fork}):
            continue
        if any(set(g.successors(v)) - region for v in region - {join}):
            continue
        visited = set()
        disjoint = True
        for branch in g.successors(fork):
            interior = ((nx.descendants(g, branch) | {branch}) & region) - {join}
            if visited & interior:
                disjoint = False
                break
            visited.update(interior)
        if disjoint and visited == region - {fork, join}:
            yield join, fork, nodes[fork].kind


def repair_deadlocks(workflow: Workflow, original_verification: dict):
    """Only repair closed, disjoint, dominating/postdominating fork/join mismatches."""
    if original_verification["status"] != "counterexample":
        return workflow, original_verification, []
    candidate = workflow.model_copy(deep=True)
    changes = []
    deadline = monotonic() + 8
    checked = original_verification
    for _ in range(8):
        if monotonic() > deadline:
            break
        found = list(_mismatched_regions(candidate))
        if not found:
            break
        for join, fork, kind in found[: 8 - len(changes)]:
            node = next(n for n in candidate.nodes if n.id == join)
            before = node.kind
            node.kind = kind
            changes.append(
                {
                    "code": "matched_join_repair",
                    "node_id": join,
                    "paired_fork": fork,
                    "before": before,
                    "after": kind,
                    "message": f"{join}: changed {before} to {kind} to match {fork}. The disjoint branches form a closed region; the split determines whether one or all branches run.",
                }
            )
        require_valid(candidate)
        checked = verify(candidate)
        if checked["status"] == "no_counterexample":
            return candidate, checked, changes
        if len(changes) >= 8:
            break
    raise DomainError(
        "No verified automatic deadlock repair was found within the supported split/join rules. The original is preserved; no corrected BPMN or completion metrics were fabricated."
    )


def corrected_source(original_xml: str, candidate: Workflow, changes: list[dict]):
    if not changes:
        return original_xml
    root = read_xml(original_xml)
    elements = {e.get("id"): e for e in root.iter() if e.get("id")}
    for change in changes:
        elem = elements.get(change["node_id"])
        if elem is None or elem.tag != f"{{{BPMN}}}{change['before']}":
            raise DomainError("Repair could not be mapped back to the original source gateway.")
        elem.tag = f"{{{BPMN}}}{change['after']}"
    xml = ET.tostring(root, encoding="unicode", pretty_print=True)
    restored, _ = parse(xml)
    if restored.model_dump() != candidate.model_dump():
        raise DomainError("Corrected source failed semantic round-trip validation.")
    return xml


def execution_plan(workflow: Workflow, config: Scenario, schedule: dict):
    routes = choose_routes(workflow, config)
    active = execution_graph(workflow, routes)
    predecessors = task_predecessors(workflow, active)
    validate_schedule(workflow, config, schedule["schedule"], set(predecessors))
    if not predecessors:
        raise DomainError(
            "The selected route contains no work tasks; an execution-plan rewrite is unnecessary."
        )
    dependencies = nx.DiGraph()
    dependencies.add_nodes_from(predecessors)
    dependencies.add_edges_from(
        (prev, ident) for ident, previous in predecessors.items() for prev in previous
    )
    by_slot = defaultdict(list)
    for row in schedule["schedule"]:
        by_slot[row["resource"]].append(row)
    for rows in by_slot.values():
        rows.sort(key=lambda r: (r["start"], r["id"]))
        dependencies.add_edges_from((a["id"], b["id"]) for a, b in zip(rows, rows[1:]))
    if not nx.is_directed_acyclic_graph(dependencies):
        raise DomainError("Resource-ordered plan introduced a cycle; candidate rejected.")
    dependencies = nx.transitive_reduction(dependencies)
    roots = [n for n in dependencies if dependencies.in_degree(n) == 0]
    leaves = [n for n in dependencies if dependencies.out_degree(n) == 0]
    extra = sum(dependencies.in_degree(n) > 1 for n in dependencies) + sum(
        dependencies.out_degree(n) > 1 for n in dependencies
    )
    if len(dependencies) + extra + 2 + (len(roots) > 1) + (len(leaves) > 1) > MAX_NODES:
        raise DomainError(
            "The resource-ordered rewrite exceeds the node budget; use the full-process annotated output."
        )
    used = {workflow.id, *[n.id for n in workflow.nodes], *[e.id for e in workflow.edges]}
    serial = 0

    def ident(prefix):
        nonlocal serial
        while True:
            serial += 1
            value = f"plan_{prefix}_{serial}"
            if value not in used:
                used.add(value)
                return value

    task_settings = settings(workflow, config)
    sources = {n.id: n for n in workflow.nodes}
    nodes = []
    for task in dependencies:
        node = sources[task].model_copy(deep=True)
        setting = task_settings[task]
        node.duration, node.role, node.provenance = setting.duration, setting.role, setting.provenance
        nodes.append(node)
    start, end = ident("start"), ident("end")
    nodes.extend(
        [
            Node(id=start, kind="startEvent", name="Start selected execution"),
            Node(id=end, kind="endEvent", name="Selected work complete"),
        ]
    )
    pairs = []
    heads, tails = {}, {}
    for task in dependencies:
        heads[task], tails[task] = task, task
        if dependencies.in_degree(task) > 1:
            heads[task] = ident("join")
            nodes.append(Node(id=heads[task], kind="parallelGateway"))
            pairs.append((heads[task], task))
        if dependencies.out_degree(task) > 1:
            tails[task] = ident("fork")
            nodes.append(Node(id=tails[task], kind="parallelGateway"))
            pairs.append((task, tails[task]))
    pairs.extend((tails[a], heads[b]) for a, b in dependencies.edges)
    root, leaf = start, end
    if len(roots) > 1:
        root = ident("fork")
        nodes.append(Node(id=root, kind="parallelGateway"))
        pairs.append((start, root))
    if len(leaves) > 1:
        leaf = ident("join")
        nodes.append(Node(id=leaf, kind="parallelGateway"))
        pairs.append((leaf, end))
    pairs.extend((root, heads[n]) for n in roots)
    pairs.extend((tails[n], leaf) for n in leaves)
    if len(pairs) > MAX_EDGES:
        raise DomainError("The resource-ordered rewrite exceeds the flow budget.")
    plan = Workflow(
        id=ident("process"),
        name=(workflow.name[:450] + " — selected optimized execution"),
        nodes=nodes,
        edges=[Edge(id=ident("flow"), source=a, target=b) for a, b in pairs],
        time_unit=config.unit,
        resource_pools=[r.model_copy() for r in config.resources],
        assumptions=[
            "Selected-route execution plan, not a replacement for all business routing alternatives. See corrected.bpmn for the full process.",
            "Task IDs, selected work, durations, roles and capacities are unchanged. Additional dependencies preserve the selected resource-slot task order.",
            f"Selected source routes: {json.dumps(routes, sort_keys=True)}.",
            *config.automatic_assumptions[:95],
        ],
    )
    require_valid(plan)
    replay_config = Scenario(unit=config.unit, resources=config.resources, seed=config.seed)
    replay = simulate(plan, replay_config)
    validate_schedule(workflow, config, replay["schedule"], set(predecessors))
    if replay["metrics"]["makespan"] > schedule["metrics"]["makespan"] + 1e-7:
        raise DomainError(
            "The rewritten plan replay was slower than the selected schedule; candidate rejected."
        )
    return plan, replay


def _annotate(xml, config, schedule):
    root = read_xml(xml)
    process = root.find(f"{{{BPMN}}}process")
    ext = process.find(f"{{{BPMN}}}extensionElements")
    if ext is None:
        ext = ET.Element(f"{{{BPMN}}}extensionElements")
        process.insert(0, ext)
    for previous in list(ext):
        if previous.tag == f"{{{STUDIO}}}executionPlan":
            ext.remove(previous)
    meta = ET.SubElement(
        ext,
        f"{{{STUDIO}}}executionPlan",
        unit=config.unit,
        scope="selected_route",
        businessConditionsEvaluated="false",
    )
    for gateway, flow in schedule["selected_routes"].items():
        ET.SubElement(meta, f"{{{STUDIO}}}selectedRoute", gatewayRef=gateway, flowRef=flow)
    for row in schedule["schedule"]:
        ET.SubElement(
            meta,
            f"{{{STUDIO}}}taskTiming",
            taskRef=row["id"],
            start=str(row["start"]),
            finish=str(row["finish"]),
            resource=row["resource"],
        )
    return ET.tostring(root, encoding="unicode", pretty_print=True)


def diagram_svg(
    workflow: Workflow, caption="Selected-route plan; all alternatives remain in corrected.bpmn."
):
    positions = layout(workflow)
    width = max(560, max(x + w for x, y, w, h in positions.values()) + 70)
    height = max(y + h for x, y, w, h in positions.values()) + 90
    pieces = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}"><title>{escape(workflow.name)}</title>',
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 Z" fill="#315e68"/></marker></defs>',
        f'<rect width="{width}" height="{height}" fill="#f5f4ef"/>',
        f'<text x="30" y="22" font-family="sans-serif" font-size="14" fill="#1d2725">{escape(workflow.name[:70])}</text>',
        f'<text x="30" y="42" font-family="sans-serif" font-size="10" fill="#315e68">{escape(caption)}</text>',
    ]
    for edge in workflow.edges:
        x, y, w, h = positions[edge.source]
        tx, ty, _, th = positions[edge.target]
        mid = (x + w + tx) / 2
        pieces.append(
            f'<polyline points="{x + w},{y + h / 2} {mid},{y + h / 2} {mid},{ty + th / 2} {tx},{ty + th / 2}" fill="none" stroke="#315e68" stroke-width="2" marker-end="url(#arrow)"/>'
        )
    for node in workflow.nodes:
        x, y, w, h = positions[node.id]
        if node.kind in TASK_KINDS:
            pieces.append(
                f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="white" stroke="#315e68" stroke-width="2"/>'
            )
        elif node.kind.endswith("Gateway"):
            pieces.append(
                f'<polygon points="{x + w / 2},{y} {x + w},{y + h / 2} {x + w / 2},{y + h} {x},{y + h / 2}" fill="white" stroke="#315e68" stroke-width="2"/>'
            )
        else:
            pieces.append(
                f'<circle cx="{x + w / 2}" cy="{y + h / 2}" r="{w / 2}" fill="white" stroke="#315e68" stroke-width="2"/>'
            )
        import textwrap

        lines = textwrap.wrap(node.name or node.id, width=19)[:3]
        for index, line in enumerate(lines):
            label_y = y + 20 + index * 14 if node.kind in TASK_KINDS else y + h + 16 + index * 14
            pieces.append(
                f'<text x="{x + w / 2}" y="{label_y}" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#1d2725">{escape(line)}</text>'
            )
        if node.kind in TASK_KINDS:
            facts = (
                f"{node.duration:g} {workflow.time_unit}; {node.role}"
                if node.duration is not None
                else "Timing unknown"
            )
            pieces.append(
                f'<text x="{x + w / 2}" y="{y + h - 7}" text-anchor="middle" font-family="sans-serif" font-size="8" fill="#315e68">{escape(facts[:30])}</text>'
            )
        if node.kind.endswith("Gateway"):
            pieces.append(
                f'<text x="{x + w / 2}" y="{y + h / 2 + 5}" text-anchor="middle" font-family="sans-serif" font-size="18">{"+" if node.kind == "parallelGateway" else "X"}</text>'
            )
    pieces.append("</svg>")
    return "".join(pieces)


def build_revision(workflow, config, optimization, baseline, original_xml, repairs, source_verification):
    corrected_xml = corrected_source(original_xml, workflow, repairs)
    selected = optimization["selected"]
    required = set(task_predecessors(workflow, execution_graph(workflow, choose_routes(workflow, config))))
    validate_schedule(workflow, config, selected["schedule"], required)
    method, fallback = "resource_ordered_execution_plan", None
    try:
        plan, replay = execution_plan(workflow, config, selected)
    except DomainError as exc:
        method, fallback = "schedule_annotations_only", str(exc)
        plan = workflow.model_copy(deep=True)
        task_settings = settings(workflow, config)
        for node in plan.nodes:
            if node.kind in TASK_KINDS:
                setting = task_settings[node.id]
                node.duration, node.role, node.provenance = setting.duration, setting.role, setting.provenance
        plan.time_unit, plan.resource_pools = config.unit, config.resources
        replay = None
    if replay:
        original_predecessors = task_predecessors(
            workflow, execution_graph(workflow, choose_routes(workflow, config))
        )
        rows = [dict(row) for row in replay["schedule"]]
        by_id = {row["id"]: row for row in rows}
        for row in rows:
            row["ready"] = max((by_id[p]["finish"] for p in original_predecessors[row["id"]]), default=0)
            row["wait"] = row["start"] - row["ready"]
        revised_metrics = metrics(rows, config)
        if (
            optimization["status"] == "optimal"
            and revised_metrics["makespan"] < selected["metrics"]["makespan"] - 1e-7
        ):
            raise DomainError(
                "Independent plan replay contradicted the claimed optimal bound; output rejected."
            )
        selected = {
            "metrics": revised_metrics,
            "schedule": rows,
            "selected_routes": selected["selected_routes"],
            "warnings": selected["warnings"],
            "seed": config.seed,
        }
        validate_schedule(workflow, config, rows, required)
        optimization["selected"] = selected
        original_makespan = baseline["metrics"]["makespan"]
        optimization["improvement_pct"] = (
            100 * (original_makespan - revised_metrics["makespan"]) / original_makespan
            if original_makespan
            else 0
        )
        if optimization["best_bound"] is not None and revised_metrics["makespan"]:
            optimization["relative_gap"] = max(
                0, (revised_metrics["makespan"] - optimization["best_bound"]) / revised_metrics["makespan"]
            )
            if (
                optimization["status"] == "feasible"
                and abs(revised_metrics["makespan"] - optimization["best_bound"]) < 1e-7
            ):
                optimization["status"] = "optimal"
                optimization["method"] = "cp_sat_bound_and_replay"
                optimization["explanation"] = (
                    "Independent execution-plan replay attains the solver's proven lower bound with unchanged task facts and staffing."
                )
    checked = verify(plan)
    summary = {
        "status": "validated" if checked["status"] == "no_counterexample" else "verification_incomplete",
        "method": method,
        "fallback_reason": fallback,
        "optimality_proven": optimization["status"] == "optimal",
        "optimization_status": optimization["status"],
        "best_bound": optimization["best_bound"],
        "relative_gap": optimization["relative_gap"],
        "scope": "Fixed durations and staffing for the selected source route. Other routing alternatives remain in corrected.bpmn. Business-wide optimality and production execution conformance are not claimed.",
        "changes": repairs,
        "repaired_deadlock": bool(repairs),
        "source_verification_status": source_verification["status"],
        "full_process_verification_status": verify(workflow)["status"],
        "output_verification": {k: v for k, v in checked.items() if k != "petri_net"},
        "baseline_scope": "Baseline after gateway repair; the original deadlocked process had no valid completion time."
        if repairs
        else "Original process baseline under the recorded scenario.",
        "selected_routes": selected["selected_routes"],
        "excluded_task_ids": sorted(
            {n.id for n in workflow.nodes if n.kind in TASK_KINDS} - {r["id"] for r in selected["schedule"]}
        )
        if method == "resource_ordered_execution_plan"
        else [],
        "baseline_makespan": baseline["metrics"]["makespan"],
        "selected_makespan": selected["metrics"]["makespan"],
        "replay_makespan": replay["metrics"]["makespan"] if replay else None,
        "resource_wait_before": baseline["metrics"]["total_wait"],
        "resource_wait_after": selected["metrics"]["total_wait"],
        "bottleneck_notice": "Resource-order changes can reduce avoidable waiting; intrinsic workload and capacity limits can remain. Staffing and task durations were not changed. Plan resource order is encoded as precedence, so queue waits are compared using the original-process dependencies, not the rewritten plan's ready times.",
        "remaining_bottlenecks": [
            {"node_id": row["id"], "role": row["role"], "wait": row["wait"]}
            for row in selected["schedule"]
            if row["wait"] > 1e-7
        ],
        "source_sha256": hashlib.sha256(original_xml.encode()).hexdigest(),
        "available_artifacts": [],
    }
    if checked["status"] != "no_counterexample":
        return summary, {}
    xml = _annotate(serialize(plan), config, selected)
    restored, _ = parse(xml)
    if restored.model_dump() != plan.model_dump() or schema_check(xml):
        raise DomainError("Revised execution plan failed its schema or semantic round-trip check.")
    summary["optimized_sha256"] = hashlib.sha256(xml.encode()).hexdigest()
    summary["corrected_sha256"] = hashlib.sha256(corrected_xml.encode()).hexdigest()
    summary["available_artifacts"] = ["corrected.bpmn", "optimized.bpmn", "optimized.svg", "changes.json"]
    documents = {
        "corrected.bpmn": corrected_xml,
        "optimized.bpmn": xml,
        "optimized.svg": diagram_svg(
            plan,
            "Selected-route plan; all alternatives remain in corrected.bpmn."
            if method == "resource_ordered_execution_plan"
            else "Full-process annotations; no structural rewrite is claimed.",
        ),
        "changes.json": json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False),
    }
    return summary, documents
