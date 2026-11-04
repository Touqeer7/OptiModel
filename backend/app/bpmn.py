"""Safe BPMN import and deterministic DI serialization; original XML stays separate."""

import re
from collections import Counter
from pathlib import Path

import networkx as nx
from lxml import etree as ET

from .domain import Diagnostic, DomainError, Edge, Node, TASK_KINDS, Workflow
from .graph_tools import flow_index
from .limits import MAX_XML, MAX_XML_DEPTH, MAX_XML_ELEMENTS

BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
DI = "http://www.omg.org/spec/BPMN/20100524/DI"
DC = "http://www.omg.org/spec/DD/20100524/DC"
WAY = "http://www.omg.org/spec/DD/20100524/DI"
STUDIO = "urn:optimodel:studio:1"
SUPPORTED = TASK_KINDS | {
    "startEvent",
    "endEvent",
    "intermediateThrowEvent",
    "parallelGateway",
    "exclusiveGateway",
}
PASSIVE = {
    "documentation",
    "extensionElements",
    "incoming",
    "outgoing",
    "conditionExpression",
    "laneSet",
    "lane",
    "flowNodeRef",
    "textAnnotation",
    "association",
    "text",
    "script",
}


def graph(workflow: Workflow) -> nx.DiGraph:
    g = nx.DiGraph()
    g.add_nodes_from(n.id for n in workflow.nodes)
    g.add_edges_from((e.source, e.target) for e in workflow.edges)
    return g


def validate(workflow: Workflow) -> list[Diagnostic]:
    issues = []

    def error(code, message, node_id=None):
        issues.append(Diagnostic(code=code, message=message, element_id=node_id))

    ids = [workflow.id] + [n.id for n in workflow.nodes] + [e.id for e in workflow.edges]
    for ident, count in Counter(ids).items():
        if count > 1:
            error("duplicate_id", "IDs must be unique across the document.", ident)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", ident):
            error("invalid_id", "Use an XML ID without spaces, colons, or special characters.", ident)
    nodes = {n.id: n for n in workflow.nodes}
    if not any(n.kind in TASK_KINDS for n in workflow.nodes):
        error("no_tasks", "Include at least one modeled work task.")
    for edge in workflow.edges:
        if edge.source not in nodes or edge.target not in nodes:
            error("dangling_flow", "Sequence flow references an unknown BPMN element.", edge.id)
    if issues:
        return issues
    g = graph(workflow)
    if len(g.edges) != len(workflow.edges):
        error("duplicate_connection", "Multiple flows between the same nodes are unsupported.")
    starts = [n.id for n in workflow.nodes if n.kind == "startEvent"]
    ends = [n.id for n in workflow.nodes if n.kind == "endEvent"]
    if len(starts) != 1 or not ends:
        error("scope", "Require exactly one plain start and at least one plain end event.")
    if not nx.is_directed_acyclic_graph(g):
        error("unsupported_loop", "Loops are unsupported; use an acyclic process.")
    for n in workflow.nodes:
        inc, out = g.in_degree(n.id), g.out_degree(n.id)
        if n.kind not in TASK_KINDS and (n.duration is not None or n.role is not None):
            error(
                "control_metadata",
                "Durations and resources belong to tasks, not zero-time control nodes.",
                n.id,
            )
        if n.kind == "startEvent" and (inc != 0 or out != 1):
            error("start_shape", "A start event needs no incoming and exactly one outgoing flow.", n.id)
        elif n.kind == "endEvent" and (inc != 1 or out != 0):
            error("end_shape", "An end event needs one incoming flow; merge branches explicitly.", n.id)
        elif n.kind in TASK_KINDS and (inc != 1 or out != 1):
            error("task_shape", "Tasks need one incoming and one outgoing flow; use explicit gateways.", n.id)
        elif n.kind == "intermediateThrowEvent" and (inc != 1 or out != 1):
            error(
                "event_shape", "A none intermediate throw event needs one incoming and outgoing flow.", n.id
            )
        elif n.kind.endswith("Gateway") and not ((inc == 1 and out >= 2) or (inc >= 2 and out == 1)):
            error("gateway_shape", "Use separate split (1:N) and merge/join (N:1) gateways.", n.id)
        if n.kind == "exclusiveGateway" and out > 1:
            branches = [e for e in workflow.edges if e.source == n.id]
            if sum(e.is_default for e in branches) > 1:
                error("xor_defaults", "An exclusive split can have only one default flow.", n.id)
        elif any(e.condition or e.is_default for e in workflow.edges if e.source == n.id):
            error(
                "unsupported_condition",
                "Conditions/default flows are supported only on exclusive splits.",
                n.id,
            )
    if len(starts) == 1 and ends:
        reachable = nx.descendants(g, starts[0]) | {starts[0]}
        reversed_graph = g.reverse(copy=False)
        ending = set(nx.multi_source_dijkstra_path_length(reversed_graph, ends, weight=None))
        for n in nodes:
            if n not in reachable or n not in ending:
                error("unreachable", "Every element must lie on a path from start to end.", n)
    if workflow.ambiguities:
        error("review_required", "Resolve generation ambiguities before accepting the model.")
    return issues


def routing_warnings(workflow: Workflow) -> list[Diagnostic]:
    """Missing business conditions do not prevent explicit scenario routing."""
    _, outgoing = flow_index(workflow)
    splits = {n.id for n in workflow.nodes if n.kind == "exclusiveGateway" and len(outgoing[n.id]) > 1}
    return [
        Diagnostic(
            code="missing_condition",
            severity="warning",
            element_id=edge.id,
            message="XOR branch has no condition. Select a route in Simulate before running; no condition is inferred.",
        )
        for edge in workflow.edges
        if edge.source in splits and not edge.condition and not edge.is_default
    ]


def _flatten_subprocesses(root):
    """Normalize only regular, single-entry/single-exit embedded scopes on a private XML tree.

    Original XML is retained by persistence. Events and task IDs remain traceable to source.
    Call activities, event/loop/multi-instance scopes are never approximated.
    """
    subprocesses = [
        elem
        for elem in root.iter(f"{{{BPMN}}}subProcess")
        if not any(a.tag == f"{{{BPMN}}}extensionElements" for a in elem.iterancestors())
    ]
    warnings = []
    if not subprocesses:
        return warnings
    for scope in [*root.findall(f"{{{BPMN}}}process"), *subprocesses]:
        local = {
            e.get("id"): e for e in scope if e.tag in {f"{{{BPMN}}}{k}" for k in SUPPORTED | {"subProcess"}}
        }
        flows = [e for e in scope if e.tag == f"{{{BPMN}}}sequenceFlow"]
        for flow in flows:
            if flow.get("sourceRef") not in local or flow.get("targetRef") not in local:
                raise DomainError(
                    "Sequence flows must stay within their process or subprocess scope.",
                    [
                        Diagnostic(
                            code="cross_scope_flow",
                            message="Use a subprocess's external entry/exit.",
                            element_id=flow.get("id"),
                        )
                    ],
                )
        for ident, elem in local.items():
            for direction, ref in (("incoming", "targetRef"), ("outgoing", "sourceRef")):
                declared = [e.text for e in elem.findall(f"{{{BPMN}}}{direction}")]
                expected = {e.get("id") for e in flows if e.get(ref) == ident}
                if declared and (set(declared) != expected or len(declared) != len(set(declared))):
                    raise DomainError("Flow declarations disagree with sequenceFlow references.")
    for sub in reversed(subprocesses):
        ident = sub.get("id")
        parent = sub.getparent()

        def unsupported(message):
            raise DomainError(
                "Unsupported embedded subprocess.",
                [Diagnostic(code="unsupported_subprocess", message=message, element_id=ident)],
            )

        if parent.tag not in (f"{{{BPMN}}}process", f"{{{BPMN}}}subProcess"):
            unsupported("Embedded subprocess must belong directly to a flow scope.")
        if any(sub.get(a, "false") not in ("false", "0") for a in ("triggeredByEvent", "isForCompensation")):
            unsupported("Event-triggered and compensation subprocesses are unsupported.")
        if any(sub.get(a, "1") != "1" for a in ("startQuantity", "completionQuantity")):
            unsupported("Non-unit subprocess token quantities are unsupported.")
        if (
            sub.get("duration")
            or sub.find(f"{{{BPMN}}}extensionElements/{{{STUDIO}}}metadata[@duration]") is not None
        ):
            unsupported(
                "Specify timings on subprocess child tasks; aggregate subprocess timing is not silently distributed."
            )
        if any(
            e.tag in (f"{{{BPMN}}}standardLoopCharacteristics", f"{{{BPMN}}}multiInstanceLoopCharacteristics")
            for e in sub
        ):
            unsupported("Loop and multi-instance subprocesses require execution semantics not modeled here.")
        starts = sub.findall(f"{{{BPMN}}}startEvent")
        ends = sub.findall(f"{{{BPMN}}}endEvent")
        if len(starts) != 1 or len(ends) != 1:
            unsupported("Embedded scope needs one plain start and one plain end event.")
        start, end = starts[0], ends[0]
        flows = sub.findall(f"{{{BPMN}}}sequenceFlow")
        if (
            sum(e.get("targetRef") == start.get("id") for e in flows)
            or sum(e.get("sourceRef") == start.get("id") for e in flows) != 1
            or sum(e.get("sourceRef") == end.get("id") for e in flows)
            or sum(e.get("targetRef") == end.get("id") for e in flows) != 1
        ):
            unsupported("Embedded start/end require a single entry and exit path.")
        outer = parent.findall(f"{{{BPMN}}}sequenceFlow")
        if (
            sum(e.get("targetRef") == ident for e in outer) != 1
            or sum(e.get("sourceRef") == ident for e in outer) != 1
        ):
            unsupported("Use explicit external gateways around subprocess entry and exit.")
        for edge in outer:
            if edge.get("targetRef") == ident:
                edge.set("targetRef", start.get("id"))
            if edge.get("sourceRef") == ident:
                edge.set("sourceRef", end.get("id"))
        start.tag = end.tag = f"{{{BPMN}}}intermediateThrowEvent"
        # Keep every semantic child; unsupported event definitions are checked below.
        for child in list(sub):
            if child.tag not in (
                f"{{{BPMN}}}incoming",
                f"{{{BPMN}}}outgoing",
                f"{{{BPMN}}}documentation",
                f"{{{BPMN}}}extensionElements",
            ):
                parent.append(child)
        parent.remove(sub)
        warnings.append(
            Diagnostic(
                code="flattened_subprocess",
                severity="info",
                element_id=ident,
                message="Single-entry/exit embedded scope expanded for analysis; original source and child IDs retained.",
            )
        )
    # Original declarations were checked before remapping scope entry/exit.
    for elem in root.iter():
        for child in list(elem):
            if child.tag in (f"{{{BPMN}}}incoming", f"{{{BPMN}}}outgoing"):
                elem.remove(child)
    return warnings


def require_valid(workflow: Workflow):
    issues = validate(workflow)
    if any(d.severity == "error" for d in issues):
        raise DomainError("The model is outside the supported BPMN subset.", issues)


def complexity(workflow: Workflow):
    g = graph(workflow)
    generations = list(nx.topological_generations(g))
    return {
        "nodes": len(workflow.nodes),
        "flows": len(workflow.edges),
        "tasks": sum(n.kind in TASK_KINDS for n in workflow.nodes),
        "exclusive_splits": sum(
            n.kind == "exclusiveGateway" and g.out_degree(n.id) > 1 for n in workflow.nodes
        ),
        "parallel_splits": sum(
            n.kind == "parallelGateway" and g.out_degree(n.id) > 1 for n in workflow.nodes
        ),
        "end_events": sum(n.kind == "endEvent" for n in workflow.nodes),
        "graph_depth": len(generations),
        "max_layer_width": max(map(len, generations), default=0),
        "scope": "Static DAG structure; layer width is not measured runtime concurrency.",
    }


def read_xml(xml: str):
    """Shared secure XML boundary for executable import and structural-only inspection."""
    if len(xml.encode("utf-8")) > MAX_XML:
        raise DomainError("BPMN exceeds the 10 MB input limit.")
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", xml, re.I):
        raise DomainError("DTD and entity declarations are forbidden.")
    try:
        root = ET.fromstring(
            xml.encode("utf-8"),
            ET.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False),
        )
    except (ET.XMLSyntaxError, ValueError) as exc:
        raise DomainError("Malformed XML. Check tag nesting and encoding.") from exc
    if root.tag != f"{{{BPMN}}}definitions":
        raise DomainError("Expected a BPMN 2.0 definitions document.")
    if len(list(root.iter())) > MAX_XML_ELEMENTS:
        raise DomainError("XML exceeds the 100,000-element complexity limit.")
    for elem in root.iter():
        if len(list(elem.iterancestors())) > MAX_XML_DEPTH:
            raise DomainError("XML nesting exceeds 64 levels.")
    all_ids = [e.get("id") for e in root.iter() if e.get("id")]
    duplicates = [i for i, c in Counter(all_ids).items() if c > 1]
    if duplicates:
        raise DomainError(
            "Duplicate XML IDs.",
            [Diagnostic(code="duplicate_id", message="Duplicate XML ID.", element_id=i) for i in duplicates],
        )
    return root


def parse(xml: str) -> tuple[Workflow, list[Diagnostic]]:
    root = read_xml(xml)
    normalization = _flatten_subprocesses(root)
    processes = root.findall(f"{{{BPMN}}}process")
    if len(processes) != 1:
        raise DomainError("Exactly one process is supported.")
    process = processes[0]
    unsupported = []
    for elem in root.iter():
        if not isinstance(elem.tag, str) or not elem.tag.startswith(f"{{{BPMN}}}"):
            continue
        kind = ET.QName(elem).localname
        # Foreign extensions are preserved but never interpreted as execution semantics.
        in_extension = any(a.tag == f"{{{BPMN}}}extensionElements" for a in elem.iterancestors())
        if kind in SUPPORTED | {"sequenceFlow"} and elem.getparent() is not process and not in_extension:
            unsupported.append(
                Diagnostic(
                    code="nested_scope",
                    message="Flow elements must belong directly to the single process scope.",
                    element_id=elem.get("id"),
                )
            )
        if kind == "process" and elem is not process:
            unsupported.append(
                Diagnostic(
                    code="nested_scope",
                    message="Nested process scopes are unsupported.",
                    element_id=elem.get("id"),
                )
            )
        if kind not in SUPPORTED | PASSIVE | {"definitions", "process", "sequenceFlow"} and not in_extension:
            unsupported.append(
                Diagnostic(
                    code="unsupported_element",
                    message=f"{kind} is not supported.",
                    element_id=elem.get("id") or elem.getparent().get("id"),
                )
            )
    if unsupported:
        raise DomainError("Unsupported BPMN semantics.", unsupported)
    nodes, edges, warnings = [], [], normalization
    elements = {elem.get("id"): elem for elem in process}
    for elem in process:
        if not isinstance(elem.tag, str) or not elem.tag.startswith(f"{{{BPMN}}}"):
            continue
        kind = ET.QName(elem).localname
        if kind in SUPPORTED:
            if elem.get("isForCompensation") == "true" or elem.get("triggeredByEvent") == "true":
                raise DomainError(f"Compensation/event-triggered activity {elem.get('id')} is unsupported.")
            if any(elem.get(attr, "1") != "1" for attr in ("startQuantity", "completionQuantity")):
                raise DomainError(f"Non-unit token quantities on {elem.get('id')} are unsupported.")
            duration, role, provenance = None, None, "unknown"
            meta = elem.find(f"{{{BPMN}}}extensionElements/{{{STUDIO}}}metadata")
            if meta is None:
                meta = elem.find(f"{{{BPMN}}}extensionElements/{{{STUDIO}}}task")
            if meta is not None:
                provenance = meta.get("provenance", "unknown")
            if kind in TASK_KINDS:
                if kind in {"sendTask", "receiveTask", "scriptTask", "businessRuleTask"}:
                    warnings.append(
                        Diagnostic(
                            code="non_executing_task",
                            severity="info",
                            element_id=elem.get("id"),
                            message="Modeled as timed work only; messages, scripts, integrations and business rules are not executed.",
                        )
                    )
                props = {
                    e.get("name"): e.get("value")
                    for e in elem.iter()
                    if isinstance(e.tag, str) and ET.QName(e).localname == "property"
                }
                doc = " ".join(elem.xpath("./b:documentation/text()", namespaces={"b": BPMN}))
                duration_text = (
                    (meta.get("duration") if meta is not None else None)
                    or props.get("duration")
                    or elem.get("duration")
                )
                match = re.search(r"\bduration\s*[:=]\s*([0-9.]+)", doc, re.I)
                duration_text = duration_text or (match.group(1) if match else None)
                if duration_text is not None:
                    try:
                        duration = float(duration_text)
                    except ValueError as exc:
                        raise DomainError(f"Invalid duration on {elem.get('id')}.") from exc
                    provenance = meta.get("provenance", "source") if meta is not None else "source"
                role = (
                    (meta.get("role") if meta is not None else None)
                    or props.get("resource")
                    or elem.get("resource")
                )
                if duration is None or role is None:
                    warnings.append(
                        Diagnostic(
                            code="missing_assumptions",
                            severity="warning",
                            element_id=elem.get("id"),
                            message="Set duration and resource role before simulation.",
                        )
                    )
            nodes.append(
                Node(
                    id=elem.get("id", ""),
                    name=elem.get("name", ""),
                    kind=kind,
                    duration=duration,
                    role=role,
                    provenance=provenance,
                )
            )
        elif kind == "sequenceFlow":
            condition = elem.find(f"{{{BPMN}}}conditionExpression")
            source = elements.get(elem.get("sourceRef"))
            edges.append(
                Edge(
                    id=elem.get("id", ""),
                    source=elem.get("sourceRef", ""),
                    target=elem.get("targetRef", ""),
                    name=elem.get("name", ""),
                    condition="".join(condition.itertext()).strip() if condition is not None else None,
                    is_default=source is not None and source.get("default") == elem.get("id"),
                )
            )
    declared_incoming, declared_outgoing = {}, {}
    for edge in edges:
        declared_incoming.setdefault(edge.target, set()).add(edge.id)
        declared_outgoing.setdefault(edge.source, set()).add(edge.id)
    for elem in process:
        if isinstance(elem.tag, str) and ET.QName(elem).localname in SUPPORTED:
            for direction, expected in [
                ("incoming", declared_incoming.get(elem.get("id"), set())),
                ("outgoing", declared_outgoing.get(elem.get("id"), set())),
            ]:
                declared = [e.text for e in elem.findall(f"{{{BPMN}}}{direction}")]
                if declared and (set(declared) != expected or len(declared) != len(set(declared))):
                    raise DomainError(
                        "Flow declarations disagree with sequenceFlow references.",
                        [
                            Diagnostic(
                                code="flow_declaration",
                                message=f"Correct the {direction} references.",
                                element_id=elem.get("id"),
                            )
                        ],
                    )
    assumptions = [
        "".join(e.itertext()) for e in process.findall(f"{{{BPMN}}}extensionElements/{{{STUDIO}}}assumption")
    ]
    meta = process.find(f"{{{BPMN}}}extensionElements/{{{STUDIO}}}process")
    workflow = Workflow(
        id=process.get("id", ""),
        name=process.get("name") or "Imported process",
        nodes=nodes,
        edges=edges,
        assumptions=assumptions,
        time_unit=meta.get("time_unit", "time units") if meta is not None else "time units",
    )
    issues = validate(workflow)
    if issues:
        raise DomainError("BPMN structural validation failed.", issues)
    warnings.extend(routing_warnings(workflow))
    warnings.append(
        Diagnostic(
            code="units",
            severity="warning",
            message="Choose a consistent scenario time unit; source timing metadata is not a measured business fact.",
        )
    )
    if not root.findall(f".//{{{DI}}}BPMNShape"):
        warnings.append(
            Diagnostic(
                code="no_di",
                severity="warning",
                message="No diagram coordinates; a separate display layout will be generated. Original XML is preserved.",
            )
        )
    return workflow, warnings


def schema_check(xml: str) -> list[Diagnostic]:
    path = Path(__file__).parent / "schemas" / "BPMN20.xsd"
    if not path.exists():
        return [
            Diagnostic(
                code="schema_unavailable",
                severity="warning",
                message="Official XSD not installed; schema validation unavailable.",
            )
        ]
    parser = ET.XMLParser(no_network=True, resolve_entities=False)
    schema = ET.XMLSchema(ET.parse(str(path), parser))
    tree = ET.fromstring(xml.encode(), parser)
    if schema.validate(tree):
        return []
    return [
        Diagnostic(code="xsd", severity="warning", message=f"Official schema: {e.message[:400]}")
        for e in list(schema.error_log)[:10]
    ]


def layout(workflow: Workflow) -> dict:
    g = graph(workflow)
    nodes = {n.id: n for n in workflow.nodes}
    positions = {}
    for col, generation in enumerate(nx.topological_generations(g)):
        generation = sorted(generation)
        for row, ident in enumerate(generation):
            n = nodes[ident]
            w, h = (120, 72) if n.kind in TASK_KINDS else (48, 48) if n.kind.endswith("Gateway") else (36, 36)
            center = 260 + (row - (len(generation) - 1) / 2) * 120
            predecessors = list(g.predecessors(ident))
            # Keep continuing branches in their own lanes; merge at the parents' mean.
            if predecessors and all(g.out_degree(p) == 1 for p in predecessors):
                center = sum(positions[p][1] + positions[p][3] / 2 for p in predecessors) / len(predecessors)
            positions[ident] = (60 + col * 180, center - h / 2, w, h)
    min_y = min(y for x, y, w, h in positions.values())
    if min_y < 60:
        positions = {ident: (x, y - min_y + 60, w, h) for ident, (x, y, w, h) in positions.items()}
    return positions


def serialize(workflow: Workflow) -> str:
    """Create an explicitly new model with readable layered DI; never rewrite imported originals."""
    require_valid(workflow)
    used = {workflow.id, *[n.id for n in workflow.nodes], *[e.id for e in workflow.edges]}

    def unique_id(base):
        result = base
        while result in used:
            result = "_" + result
        used.add(result)
        return result

    root = ET.Element(
        f"{{{BPMN}}}definitions",
        nsmap={"bpmn": BPMN, "bpmndi": DI, "dc": DC, "di": WAY, "studio": STUDIO},
        id=unique_id("StudioDefinitions"),
        targetNamespace=STUDIO,
    )
    process = ET.SubElement(
        root, f"{{{BPMN}}}process", id=workflow.id, name=workflow.name, isExecutable="false"
    )
    if workflow.assumptions or workflow.time_unit != "time units":
        extensions = ET.SubElement(process, f"{{{BPMN}}}extensionElements")
        if workflow.time_unit != "time units":
            ET.SubElement(extensions, f"{{{STUDIO}}}process", time_unit=workflow.time_unit)
        for assumption in workflow.assumptions:
            ET.SubElement(extensions, f"{{{STUDIO}}}assumption").text = assumption
    incoming, outgoing = flow_index(workflow)
    defaults = {e.source: e.id for e in workflow.edges if e.is_default}
    for n in workflow.nodes:
        attrs = {"id": n.id, "name": n.name}
        default = defaults.get(n.id)
        if default:
            attrs["default"] = default
        elem = ET.SubElement(process, f"{{{BPMN}}}{n.kind}", **attrs)
        if n.kind in TASK_KINDS or n.provenance != "unknown":
            ext = ET.SubElement(elem, f"{{{BPMN}}}extensionElements")
            props = {"provenance": n.provenance}
            if n.duration is not None:
                props["duration"] = str(n.duration)
            if n.role:
                props["role"] = n.role
            ET.SubElement(ext, f"{{{STUDIO}}}metadata", **props)
        for ident in incoming[n.id]:
            ET.SubElement(elem, f"{{{BPMN}}}incoming").text = ident
        for ident in outgoing[n.id]:
            ET.SubElement(elem, f"{{{BPMN}}}outgoing").text = ident
    for e in workflow.edges:
        elem = ET.SubElement(
            process, f"{{{BPMN}}}sequenceFlow", id=e.id, sourceRef=e.source, targetRef=e.target, name=e.name
        )
        if e.condition:
            ET.SubElement(elem, f"{{{BPMN}}}conditionExpression").text = e.condition
    diagram = ET.SubElement(root, f"{{{DI}}}BPMNDiagram", id=unique_id("StudioDiagram"))
    plane = ET.SubElement(diagram, f"{{{DI}}}BPMNPlane", id=unique_id("StudioPlane"), bpmnElement=workflow.id)
    positions = layout(workflow)
    for ident, (x, y, w, h) in positions.items():
        shape = ET.SubElement(plane, f"{{{DI}}}BPMNShape", id=unique_id(f"DI_{ident}"), bpmnElement=ident)
        ET.SubElement(shape, f"{{{DC}}}Bounds", x=str(x), y=str(y), width=str(w), height=str(h))
    for e in workflow.edges:
        edge = ET.SubElement(plane, f"{{{DI}}}BPMNEdge", id=unique_id(f"DI_{e.id}"), bpmnElement=e.id)
        x, y, w, h = positions[e.source]
        tx, ty, tw, th = positions[e.target]
        mid = (x + w + tx) / 2
        for px, py in [(x + w, y + h / 2), (mid, y + h / 2), (mid, ty + th / 2), (tx, ty + th / 2)]:
            ET.SubElement(edge, f"{{{WAY}}}waypoint", x=str(px), y=str(py))
    return ET.tostring(root, encoding="unicode", pretty_print=True)
