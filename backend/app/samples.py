"""Transparent demonstration data, not measurements from an operating business."""

from .bpmn import serialize
from .domain import Edge, Node, Resource, Scenario, Workflow


def sample(key: str) -> dict:
    if key == "order":
        name = "Order fulfillment"
        nodes = [
            ("start", "Order received", "startEvent", None, None),
            ("split", "Prepare in parallel", "parallelGateway", None, None),
            ("inventory", "Verify inventory", "userTask", 4, "Operations"),
            ("invoice", "Prepare invoice", "userTask", 7, "Operations"),
            ("join", "All preparation complete", "parallelGateway", None, None),
            ("dispatch", "Dispatch order", "serviceTask", 2, "Operations"),
            ("end", "Order dispatched", "endEvent", None, None),
        ]
        pairs = [
            ("start", "split"),
            ("split", "inventory"),
            ("split", "invoice"),
            ("inventory", "join"),
            ("invoice", "join"),
            ("join", "dispatch"),
            ("dispatch", "end"),
        ]
        resources = [Resource(role="Operations", capacity=2, cost_per_unit=25)]
    elif key == "loan":
        name = "Loan review"
        nodes = [
            ("start", "Application received", "startEvent", None, None),
            ("review", "Review application", "userTask", 4, "Analyst"),
            ("decision", "Credit decision", "exclusiveGateway", None, None),
            ("approve", "Prepare approved offer", "userTask", 3, "Analyst"),
            ("decline", "Send decline notice", "serviceTask", 1, "Analyst"),
            ("merge", "Decision recorded", "exclusiveGateway", None, None),
            ("end", "Review complete", "endEvent", None, None),
        ]
        pairs = [
            ("start", "review"),
            ("review", "decision"),
            ("decision", "approve"),
            ("decision", "decline"),
            ("approve", "merge"),
            ("decline", "merge"),
            ("merge", "end"),
        ]
        resources = [Resource(role="Analyst", capacity=1, cost_per_unit=40)]
    elif key == "operations":
        name = "Resource-constrained operations"
        nodes = [
            ("start", "Work order received", "startEvent", None, None),
            ("split", "Release jobs", "parallelGateway", None, None),
            ("a_short", "Prepare labels", "userTask", 2, "Technician"),
            ("c_chain", "Calibrate equipment", "userTask", 3, "Technician"),
            ("b_independent", "Run quality inspection", "userTask", 7, "Technician"),
            ("d_finish", "Complete calibrated batch", "userTask", 8, "Technician"),
            ("join", "All jobs complete", "parallelGateway", None, None),
            ("end", "Batch released", "endEvent", None, None),
        ]
        pairs = [
            ("start", "split"),
            ("split", "a_short"),
            ("split", "c_chain"),
            ("split", "b_independent"),
            ("c_chain", "d_finish"),
            ("a_short", "join"),
            ("b_independent", "join"),
            ("d_finish", "join"),
            ("join", "end"),
        ]
        resources = [Resource(role="Technician", capacity=2, cost_per_unit=30)]
    else:
        raise KeyError(key)
    ir = Workflow(
        id=f"Process_{key}",
        name=name,
        nodes=[
            Node(id=i, name=n, kind=k, duration=d, role=r, provenance="example" if d else "unknown")
            for i, n, k, d, r in nodes
        ],
        edges=[
            Edge(
                id=f"flow_{i + 1}",
                source=s,
                target=t,
                condition=("approved" if t == "approve" else "declined") if s == "decision" else None,
                name=("Approved" if t == "approve" else "Declined") if s == "decision" else "",
            )
            for i, (s, t) in enumerate(pairs)
        ],
        assumptions=["All durations, staffing and rates are illustrative example assumptions."],
    )
    config = Scenario(
        unit="hours", resources=resources, routes={"decision": "flow_3"} if key == "loan" else {}
    )
    return {
        "key": key,
        "name": name,
        "description": {
            "order": "Parallel preparation, synchronized before dispatch.",
            "loan": "An explicit approved or declined route. Only one branch executes.",
            "operations": "Shared technicians, competing jobs, and a downstream dependency.",
        }[key],
        "xml": serialize(ir),
        "ir": ir.model_dump(),
        "config": config.model_dump(),
    }
