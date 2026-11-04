"""Safe BPMN import and deterministic DI serialization; original XML stays separate."""

import re
from collections import Counter
from pathlib import Path

import networkx as nx
from lxml import etree as ET

from .domain import Diagnostic, DomainError, Edge, Node, TASK_KINDS, Workflow

BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
DI = "http://www.omg.org/spec/BPMN/20100524/DI"
DC = "http://www.omg.org/spec/DD/20100524/DC"
WAY = "http://www.omg.org/spec/DD/20100524/DI"
STUDIO = "urn:optimodel:studio:1"
MAX_XML = 1_000_000
SUPPORTED = TASK_KINDS | {"startEvent", "endEvent", "parallelGateway", "exclusiveGateway"}
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
    if len(starts) != 1 or len(ends) != 1:
        error("scope", "This release requires exactly one plain start and one plain end event.")
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
        elif n.kind.endswith("Gateway") and not ((inc == 1 and out >= 2) or (inc >= 2 and out == 1)):
            error("gateway_shape", "Use separate split (1:N) and merge/join (N:1) gateways.", n.id)
        if n.kind == "exclusiveGateway" and out > 1:
            branches = [e for e in workflow.edges if e.source == n.id]
            if sum(e.is_default for e in branches) > 1:
                error("xor_defaults", "An exclusive split can have only one default flow.", n.id)
            for edge in branches:
                if not edge.condition and not edge.is_default:
                    error(
                        "missing_condition",
                        "Label each XOR branch with a condition, or mark the default.",
                        edge.id,
                    )
        elif any(e.condition or e.is_default for e in workflow.edges if e.source == n.id):
            error(
                "unsupported_condition",
                "Conditions/default flows are supported only on exclusive splits.",
                n.id,
            )
    if len(starts) == len(ends) == 1:
        reachable = nx.descendants(g, starts[0]) | {starts[0]}
        ending = nx.ancestors(g, ends[0]) | {ends[0]}
        for n in nodes:
            if n not in reachable or n not in ending:
                error("unreachable", "Every element must lie on a path from start to end.", n)
    if workflow.ambiguities:
        error("review_required", "Resolve generation ambiguities before accepting the model.")
    return issues


def require_valid(workflow: Workflow):
    issues = validate(workflow)
    if any(d.severity == "error" for d in issues):
        raise DomainError("The model is outside the supported BPMN subset.", issues)


def parse(xml: str) -> tuple[Workflow, list[Diagnostic]]:
    if len(xml.encode("utf-8")) > MAX_XML:
        raise DomainError("BPMN exceeds the 1 MB input limit.")
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
    if len(list(root.iter())) > 5000:
        raise DomainError("XML exceeds the 5,000-element complexity limit.")
    for elem in root.iter():
        if len(list(elem.iterancestors())) > 30:
            raise DomainError("XML nesting exceeds 30 levels.")
    all_ids = [e.get("id") for e in root.iter() if e.get("id")]
    duplicates = [i for i, c in Counter(all_ids).items() if c > 1]
    if duplicates:
        raise DomainError(
            "Duplicate XML IDs.",
            [Diagnostic(code="duplicate_id", message="Duplicate XML ID.", element_id=i) for i in duplicates],
        )
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
    nodes, edges, warnings = [], [], []
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
            source = (
                process.find(f"{{{BPMN}}}*[@id='{elem.get('sourceRef', '')}']")
                if "'" not in elem.get("sourceRef", "")
                else None
            )
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
    for elem in process:
        if isinstance(elem.tag, str) and ET.QName(elem).localname in SUPPORTED:
            for direction, expected in [
                ("incoming", {e.id for e in edges if e.target == elem.get("id")}),
                ("outgoing", {e.id for e in edges if e.source == elem.get("id")}),
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
    workflow = Workflow(
        id=process.get("id", ""),
        name=process.get("name") or "Imported process",
        nodes=nodes,
        edges=edges,
        assumptions=assumptions,
    )
    issues = validate(workflow)
    if issues:
        raise DomainError("BPMN structural validation failed.", issues)
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
    positions = {}
    for col, generation in enumerate(nx.topological_generations(g)):
        generation = sorted(generation)
        for row, ident in enumerate(generation):
            n = next(n for n in workflow.nodes if n.id == ident)
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
    if workflow.assumptions:
        extensions = ET.SubElement(process, f"{{{BPMN}}}extensionElements")
        for assumption in workflow.assumptions:
            ET.SubElement(extensions, f"{{{STUDIO}}}assumption").text = assumption
    for n in workflow.nodes:
        attrs = {"id": n.id, "name": n.name}
        default = next((e.id for e in workflow.edges if e.source == n.id and e.is_default), None)
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
        for edge in workflow.edges:
            if edge.target == n.id:
                ET.SubElement(elem, f"{{{BPMN}}}incoming").text = edge.id
            if edge.source == n.id:
                ET.SubElement(elem, f"{{{BPMN}}}outgoing").text = edge.id
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
