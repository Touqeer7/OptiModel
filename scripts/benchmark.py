"""Reproducible reference timings and an actual sample report for visual QA."""

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.bpmn import parse, serialize  # noqa: E402
from backend.app.domain import Edge, Node, Resource, Scenario, Workflow  # noqa: E402
from backend.app.persistence import Store, new_id, now  # noqa: E402
from backend.app.reporting import export_run  # noqa: E402
from backend.app.samples import sample  # noqa: E402
from backend.app.scheduling import optimize  # noqa: E402
from backend.app.simulation import simulate  # noqa: E402
from backend.app.verification import verify  # noqa: E402


def sequence(count):
    ids = ["start", *[f"t_{i}" for i in range(count)], "end"]
    nodes = (
        [Node(id="start", kind="startEvent")]
        + [
            Node(
                id=ident,
                name=f"Activity {i}",
                kind="task",
                duration=(i % 7) + 1,
                role="Operator",
                provenance="example",
            )
            for i, ident in enumerate(ids[1:-1])
        ]
        + [Node(id="end", kind="endEvent")]
    )
    return Workflow(
        id=f"Sequence_{count}",
        name=f"{count}-task benchmark",
        nodes=nodes,
        edges=[Edge(id=f"f_{i}", source=a, target=b) for i, (a, b) in enumerate(zip(ids, ids[1:]))],
    )


def timed(fn):
    before = time.perf_counter()
    value = fn()
    return value, round((time.perf_counter() - before) * 1000, 3)


def main():
    evidence = ROOT / "docs" / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    results = []
    # Warm the solver import separately; report timings are warm-process measurements.
    from ortools.sat.python import cp_model  # noqa: F401

    for count in (10, 150):
        xml = serialize(sequence(count))
        (w, _), parse_ms = timed(lambda: parse(xml))
        c = Scenario(resources=[Resource(role="Operator", capacity=2)], solver_seconds=2)
        v, verify_ms = timed(lambda: verify(w))
        b, simulate_ms = timed(lambda: simulate(w, c))
        o, solver_ms = timed(lambda: optimize(w, c, b))
        results.append(
            {
                "tasks": count,
                "xml_bytes": len(xml.encode()),
                "parse_ms": parse_ms,
                "verification_ms": verify_ms,
                "simulation_ms": simulate_ms,
                "optimization_ms": solver_ms,
                "states": v["states"],
                "verification_status": v["status"],
                "baseline_completion": b["metrics"]["makespan"],
                "selected_completion": o["selected"]["metrics"]["makespan"],
                "solver_status": o["status"],
            }
        )
    s = sample("operations")
    w = Workflow.model_validate(s["ir"])
    c = Scenario.model_validate(s["config"])
    b = simulate(w, c)
    o = optimize(w, c, b)
    v = verify(w)
    store = Store(ROOT / "tmp" / "qa-data")
    pid, rid, mid = new_id(), new_id(), new_id()
    run = {"id": rid, "project_id": pid}
    result = {
        "run_id": rid,
        "project_id": pid,
        "model_id": mid,
        "model_name": w.name,
        "created": now(),
        "config": c.model_dump(),
        "baseline": b,
        "optimization": o,
        "verification": v,
        "diagnostics": [],
        "assumptions": w.assumptions,
        "recommendations": [
            {
                "node_id": "c_chain",
                "message": "Prioritize calibration to release its downstream batch task earlier; identical technicians and durations are retained.",
            }
        ],
    }
    export_run(store, run, {"xml": s["xml"], "ir": s["ir"]}, result)
    shutil.copyfile(store.run_dir(pid, rid) / "report.pdf", evidence / "demo-report.pdf")
    import pymupdf

    pdf = pymupdf.open(evidence / "demo-report.pdf")
    for i, page in enumerate(pdf):
        page.get_pixmap(matrix=pymupdf.Matrix(1.3, 1.3)).save(str(evidence / f"report-page-{i + 1}.png"))
    output = {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "method": "one warm-process measurement per case; not a statistically characterized performance claim",
        "benchmarks": results,
        "sample": {
            "name": w.name,
            "baseline": b["metrics"],
            "selected": o["selected"]["metrics"],
            "solver_status": o["status"],
            "bound": o["best_bound"],
            "improvement_pct": o["improvement_pct"],
            "pdf_pages": len(pdf),
        },
    }
    (evidence / "benchmarks.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
