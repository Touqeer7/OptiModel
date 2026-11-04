"""Read-only structural assessment, including BPMN outside executable analysis scope."""

from collections import Counter

import networkx as nx
from lxml import etree as ET
from pydantic import ValidationError

from .bpmn import BPMN, parse, read_xml
from .domain import DomainError


def inspect_xml(xml: str):
    root = read_xml(xml)
    scopes, counts, issues = [], Counter(), []
    process_count = len(root.findall(f"{{{BPMN}}}process"))
    for scope in root.iter():
        if scope.tag not in {
            f"{{{BPMN}}}{kind}" for kind in ("process", "subProcess", "transaction", "adHocSubProcess")
        }:
            continue
        g = nx.DiGraph()
        nodes, flows = [], []
        for element in scope:
            if not isinstance(element.tag, str) or not element.tag.startswith(f"{{{BPMN}}}"):
                continue
            kind = ET.QName(element).localname
            counts[kind] += 1
            ident = element.get("id")
            if kind == "sequenceFlow":
                flows.append(element)
            elif kind in (
                "task",
                "subProcess",
                "transaction",
                "adHocSubProcess",
                "callActivity",
            ) or kind.endswith(("Task", "Event", "Gateway")):
                if ident:
                    nodes.append(ident)
                    g.add_node(ident)
                else:
                    issues.append(
                        {
                            "code": "missing_id",
                            "element_id": scope.get("id"),
                            "message": f"A {kind} is missing its ID.",
                        }
                    )
        for flow in flows:
            source, target = flow.get("sourceRef"), flow.get("targetRef")
            if source not in g or target not in g:
                issues.append(
                    {
                        "code": "cross_scope_or_missing_reference",
                        "element_id": flow.get("id"),
                        "message": "Sequence flow must reference nodes in its own scope.",
                    }
                )
            else:
                g.add_edge(source, target)
        cyclic = [
            sorted(component)
            for component in nx.strongly_connected_components(g)
            if len(component) > 1 or any(g.has_edge(n, n) for n in component)
        ]
        starts = [e.get("id") for e in scope if e.tag == f"{{{BPMN}}}startEvent" and e.get("id") in g]
        reachable = set(nx.multi_source_dijkstra_path_length(g, starts, weight=None)) if starts else set()
        scopes.append(
            {
                "path": root.getroottree().getpath(scope),
                "id": scope.get("id"),
                "name": scope.get("name", ""),
                "kind": ET.QName(scope).localname,
                "nodes": len(nodes),
                "flows": len(flows),
                "cyclic_regions": len(cyclic),
                "cycle_examples": [c[:20] for c in cyclic[:5]],
                "unreachable_from_explicit_starts": sorted(set(nodes) - reachable)[:50],
            }
        )
    supported, diagnostics = False, []
    try:
        _, findings = parse(xml)
        diagnostics = [d.model_dump() for d in findings]
        supported = True
    except DomainError as exc:
        diagnostics = [d.model_dump() for d in exc.diagnostics][:100]
    except ValidationError:
        diagnostics = [
            {
                "code": "analysis_limits",
                "severity": "error",
                "message": "Source exceeds the executable analysis model limits or has invalid model fields.",
            }
        ]
    return {
        "mode": "structural_inspection",
        "executable_analysis_supported": supported,
        "notice": "Read-only XML and graph assessment. It does not simulate unsupported BPMN behavior or prove process soundness.",
        "processes": process_count,
        "scopes": scopes,
        "nodes": sum(s["nodes"] for s in scopes),
        "flows": sum(s["flows"] for s in scopes),
        "element_counts": dict(sorted(counts.items())),
        "cyclic_regions": sum(s["cyclic_regions"] for s in scopes),
        "reference_issues": issues[:100],
        "diagnostics": diagnostics,
    }
