"""Per-run exports and readable vector PDF reports. No global latest artifact."""

import csv
import io
import json
import zipfile
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Circle, Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .bpmn import layout
from .domain import TASK_KINDS, Workflow

INK, TEAL, COPPER = "#1D2725", "#315E68", "#C87544"
ARTIFACTS = {
    "original.bpmn": "application/xml",
    "schedule.csv": "text/csv",
    "results.json": "application/json",
    "report.pdf": "application/pdf",
    "bundle.zip": "application/zip",
}


def safe_csv(value):
    text = str(value)
    # A spreadsheet must not execute imported task names as formulas.
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else text


def export_run(store, run, model, result):
    directory = store.run_dir(run["project_id"], run["id"])
    directory.mkdir(parents=True, exist_ok=True)
    result["artifacts"] = [
        {"name": name, "media_type": media, "url": f"/api/v1/runs/{run['id']}/artifacts/{name}"}
        for name, media in ARTIFACTS.items()
    ]
    (directory / "original.bpmn").write_text(model["xml"], encoding="utf-8", newline="")
    (directory / "results.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    columns = [
        "scenario",
        "id",
        "name",
        "role",
        "resource",
        "duration",
        "ready",
        "start",
        "finish",
        "wait",
        "provenance",
        "unit",
    ]
    writer.writerow(columns)
    selected = result["optimization"]["selected"] if result["optimization"] else None
    for label, data in [("baseline", result["baseline"]), ("selected", selected)]:
        if data:
            for row in data["schedule"]:
                writer.writerow(
                    [
                        safe_csv({"scenario": label, **row, "unit": result["config"]["unit"]}.get(c, ""))
                        for c in columns
                    ]
                )
    (directory / "schedule.csv").write_text(buffer.getvalue(), encoding="utf-8-sig", newline="")
    build_report(result, Workflow.model_validate(model["ir"]), directory / "report.pdf")
    with zipfile.ZipFile(directory / "bundle.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ARTIFACTS:
            if name != "bundle.zip":
                archive.write(directory / name, arcname=name)


def topology(workflow: Workflow) -> Drawing:
    """Actual BPMN topology with a diagram budget; large models get a clear omission note."""
    if len(workflow.nodes) > 45:
        drawing = Drawing(490, 45)
        drawing.add(
            String(0, 20, "Topology omitted above 45 nodes. Open the original BPMN in Studio.", fontSize=9)
        )
        return drawing
    bounds = layout(workflow)
    width = max(490, max(x + w for x, y, w, h in bounds.values()) + 40)
    height = max(y + h for x, y, w, h in bounds.values()) + 65
    drawing = Drawing(width, height)
    positions = {ident: (x + w / 2, height - y - h / 2) for ident, (x, y, w, h) in bounds.items()}
    for edge in workflow.edges:
        sx, sy, sw, sh = bounds[edge.source]
        tx, ty, tw, th = bounds[edge.target]
        x, y, tx, ty = sx + sw, height - sy - sh / 2, tx, height - ty - th / 2
        mid = tx - 30
        for a, b, c, d in [(x, y, mid, y), (mid, y, mid, ty), (mid, ty, tx, ty)]:
            drawing.add(Line(a, b, c, d, strokeColor=colors.HexColor(TEAL), strokeWidth=1.5))
        drawing.add(
            Polygon(
                [tx, ty, tx - 7, ty + 3, tx - 7, ty - 3], fillColor=colors.HexColor(TEAL), strokeColor=None
            )
        )
    for node in workflow.nodes:
        x, y = positions[node.id]
        if node.kind in TASK_KINDS:
            drawing.add(
                Rect(
                    x - 60,
                    y - 36,
                    120,
                    72,
                    rx=3,
                    fillColor=colors.HexColor("#EFF2F1"),
                    strokeColor=colors.HexColor(TEAL),
                )
            )
        elif node.kind.endswith("Gateway"):
            drawing.add(
                Polygon(
                    [x, y + 24, x + 24, y, x, y - 24, x - 24, y],
                    fillColor=colors.white,
                    strokeColor=colors.HexColor(TEAL),
                )
            )
            drawing.add(String(x - 4, y - 4, "+" if node.kind == "parallelGateway" else "X", fontSize=16))
        else:
            drawing.add(
                Circle(
                    x,
                    y,
                    18,
                    fillColor=colors.white,
                    strokeColor=colors.HexColor(INK),
                    strokeWidth=2 if node.kind == "endEvent" else 1,
                )
            )
        label = node.name or node.id
        import textwrap

        chunks = textwrap.wrap(label, width=14)[:3]
        for idx, chunk in enumerate(chunks):
            label_y = y + 8 if node.kind in TASK_KINDS else y - 40
            drawing.add(String(x, label_y - idx * 13, chunk, textAnchor="middle", fontSize=11))
    scale = min(490 / width, 280 / height, 1)
    drawing.scale(scale, scale)
    drawing.width, drawing.height = width * scale, height * scale
    return drawing


def timeline(rows, unit):
    rows = rows[:18]
    width, height = 490, 35 + len(rows) * 21
    drawing = Drawing(width, height)
    span = max((r["finish"] for r in rows), default=1) or 1
    for i, row in enumerate(rows):
        y = height - 25 - i * 21
        drawing.add(String(0, y, row["id"][:22], fontName="Helvetica", fontSize=8))
        x = 125 + row["start"] / span * 290
        w = max(1, row["duration"] / span * 290)
        drawing.add(Rect(x, y - 2, w, 12, fillColor=colors.HexColor(TEAL), strokeColor=None))
        drawing.add(String(x + w + 4, y, f"{row['finish']:g}", fontSize=7))
    drawing.add(String(125, 4, f"0 to {span:g} {unit}; first 18 tasks in start order", fontSize=8))
    return drawing


def build_report(result, workflow, path):
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="StudioBody",
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=colors.HexColor(INK),
            spaceAfter=7,
        )
    )
    styles.add(ParagraphStyle(name="StudioCell", fontName="Helvetica", fontSize=8, leading=11))
    styles["Title"].textColor = colors.HexColor(INK)
    styles["Heading2"].textColor = colors.HexColor(TEAL)
    parts = []

    def p(text):
        return Paragraph(escape(str(text)), styles["StudioBody"])

    def heading(text):
        parts.extend([Paragraph(escape(text), styles["Heading2"]), Spacer(1, 5)])

    def table(rows, widths):
        values = [[Paragraph(escape(str(c)), styles["StudioCell"]) for c in row] for row in rows]
        item = Table(values, colWidths=widths, repeatRows=1, hAlign="LEFT")
        item.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E4ECEC")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor(TEAL)),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#D8DCD7")),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        parts.append(item)

    opt = result["optimization"]
    base = result["baseline"]
    selected = opt["selected"] if opt else base
    unit = result["config"]["unit"]
    parts.append(Paragraph("OptiModel Studio", styles["Title"]))
    parts.extend(
        [
            p("PROCESS ENGINEERING / LOCAL EXPERIMENT"),
            p(workflow.name),
            p(f"Run {result['run_id']} | {result['created']}"),
            p(f"Project {result['project_id']} / model version {result['model_id']}"),
        ]
    )
    heading("Decision summary")
    parts.append(
        p(
            opt["explanation"]
            if opt
            else "Baseline simulation only. No scheduling or process transformation was applied."
        )
    )
    parts.append(
        p(
            "The original BPMN is unchanged. These are simulated single-case outcomes under the stated assumptions, not measured business savings."
        )
    )
    table(
        [
            ["Measure", "Baseline", "Selected"],
            [
                f"Completion ({unit})",
                f"{base['metrics']['makespan']:g}",
                f"{selected['metrics']['makespan']:g}",
            ],
            [
                f"Total task queue wait ({unit})",
                f"{base['metrics']['total_wait']:g}",
                f"{selected['metrics']['total_wait']:g}",
            ],
            ["Busy labor cost", base["metrics"]["busy_labor_cost"], selected["metrics"]["busy_labor_cost"]],
            [
                "Staffed capacity cost",
                base["metrics"]["staffed_capacity_cost"],
                selected["metrics"]["staffed_capacity_cost"],
            ],
            ["Throughput", "Not measured: one case", "Not measured: one case"],
        ],
        [230, 130, 130],
    )
    heading("Method and evidence")
    parts.append(
        p(
            f"Intervention: {opt['intervention'] if opt else 'baseline'}. Solver: {opt['status'] if opt else 'not run'}; seed {result['config']['seed']}; time budget {result['config']['solver_seconds']} seconds."
        )
    )
    if opt:
        parts.append(
            p(
                f"Best lower bound: {opt['best_bound']}; relative gap: {opt['relative_gap']}. Optimal status applies only to this deterministic supported scheduling model."
            )
        )
    for recommendation in result["recommendations"]:
        parts.append(p(recommendation["message"]))
    parts.append(PageBreak())
    heading("Original / analyzed process topology")
    parts.extend(
        [
            topology(workflow),
            Spacer(1, 12),
            p("Topology derived from the recorded source model. Scheduling changes are exported separately."),
        ]
    )
    heading("Bounded verification")
    verification = result["verification"]
    parts.append(
        p(
            f"Status: {verification['status']}. Explored {verification['states']} states; deadlocks {verification['deadlock_count']}; truncated: {verification['truncated']}."
        )
    )
    parts.append(p(verification["scope"]))
    parts.append(
        p(
            f"Proper completion: {verification['proper_completion']}; all explored states can complete: {verification['all_states_can_complete']}. Complete BPMN workflow-net soundness is not claimed."
        )
    )
    parts.append(
        p(
            f"Counterexample trace: {verification['counterexample_trace'] or 'none found'}. Petri places and transitions, including BPMN IDs, are available in results.json."
        )
    )
    parts.append(PageBreak())
    heading("Selected resource schedule")
    parts.extend([timeline(selected["schedule"], unit), Spacer(1, 10)])
    table(
        [["Task / BPMN ID", "Role / slot", "Ready", "Start", "End", "Wait"]]
        + [
            [
                f"{r['name']} ({r['id']})",
                r["resource"],
                f"{r['ready']:g}",
                f"{r['start']:g}",
                f"{r['finish']:g}",
                f"{r['wait']:g}",
            ]
            for r in selected["schedule"]
        ],
        [160, 130, 50, 50, 50, 50],
    )
    heading("Role capacity and utilization")
    table(
        [["Role", "Slots", "Rate / time unit", "Baseline busy %", "Selected busy %"]]
        + [
            [
                r["role"],
                r["capacity"],
                r["cost_per_unit"],
                f"{100 * base['metrics']['utilization_by_role'][r['role']]:.1f}",
                f"{100 * selected['metrics']['utilization_by_role'][r['role']]:.1f}",
            ]
            for r in result["config"]["resources"]
        ],
        [130, 50, 110, 100, 100],
    )
    parts.append(PageBreak())
    heading("Assumptions and provenance")
    for warning in result["assumptions"] + base["warnings"]:
        parts.append(p(warning))
    for diagnostic in result["diagnostics"]:
        parts.append(p(diagnostic["message"]))
    table(
        [["Task ID", "Duration", "Role", "Provenance"]]
        + [[r["id"], f"{r['duration']:g} {unit}", r["role"], r["provenance"]] for r in base["schedule"]],
        [130, 120, 130, 110],
    )
    heading("Route selection and limitations")
    parts.append(p(f"Explicit selected routes: {base['selected_routes'] or 'no exclusive split'}."))
    parts.append(
        p(
            "Acyclic, single-process, one-start/one-end subset only. No loops, timers, subprocesses, calendars, multi-case arrivals or stochastic task durations. XOR conditions are never executed as code. Idle capacity is not classified as waste."
        )
    )
    parts.append(
        p(
            "Busy labor cost uses busy task time; staffed capacity cost charges every configured slot for the experiment horizon. Missing rates produce null costs. Currency must be interpreted consistently by the analyst."
        )
    )

    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor(TEAL))
        canvas.drawString(42, 24, "OPTIMODEL STUDIO / SIMULATION EVIDENCE")
        canvas.drawRightString(A4[0] - 42, 24, str(doc.page))

    SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=42,
        rightMargin=42,
        topMargin=36,
        bottomMargin=40,
        title=workflow.name,
        author="OptiModel Studio",
    ).build(parts, onFirstPage=footer, onLaterPages=footer)
