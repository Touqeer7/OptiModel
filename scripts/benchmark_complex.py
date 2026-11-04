"""Reproduce larger-model correctness and warm-process latency measurements.

Run: backend/.venv/Scripts/python scripts/benchmark_complex.py
Writes isolated, non-user benchmark evidence only; no external AI requests.
"""

import json
import platform
import statistics
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.bpmn import parse, serialize  # noqa: E402
from backend.app.domain import Edge, Node, Resource, Scenario, Workflow  # noqa: E402
from backend.app.scheduling import optimize  # noqa: E402
from backend.app.simulation import simulate, validate_schedule  # noqa: E402
from backend.app.verification import verify  # noqa: E402
from scripts.benchmark import sequence  # noqa: E402


def parallel(count):
    nodes = [
        Node(id="s", kind="startEvent"),
        Node(id="fork", kind="parallelGateway"),
        Node(id="join", kind="parallelGateway"),
        Node(id="e", kind="endEvent"),
    ]
    pairs = [("s", "fork"), ("join", "e")]
    for i in range(count):
        ident = f"task_{i}"
        nodes.append(Node(id=ident, kind="task", duration=i % 7 + 1, role="Operator", provenance="example"))
        pairs.extend([("fork", ident), (ident, "join")])
    return Workflow(
        id=f"Parallel_{count}",
        name=f"{count} independent parallel tasks",
        nodes=nodes,
        edges=[Edge(id=f"f{i}", source=a, target=b) for i, (a, b) in enumerate(pairs)],
    )


def timed(fn):
    started = perf_counter()
    value = fn()
    return value, (perf_counter() - started) * 1000


def main():
    # Warm imports separately; CP-SAT search remains bounded for every case.
    from ortools.sat.python import cp_model  # noqa: F401

    cases = [sequence(100), sequence(1000), sequence(1998), parallel(128)]
    results = []
    for source in cases:
        measurements = []
        xml = serialize(source)
        for _ in range(3):
            (workflow, _), parse_ms = timed(lambda: parse(xml))
            verification, verify_ms = timed(lambda: verify(workflow))
            config = Scenario(resources=[Resource(role="Operator", capacity=16)], solver_seconds=1)
            baseline, simulation_ms = timed(lambda: simulate(workflow, config))
            optimization, optimization_ms = timed(lambda: optimize(workflow, config, baseline))
            assert verification["status"] == "no_counterexample"
            assert optimization["selected"]["metrics"]["makespan"] <= baseline["metrics"]["makespan"]
            validate_schedule(
                workflow,
                config,
                optimization["selected"]["schedule"],
                {r["id"] for r in baseline["schedule"]},
            )
            measurements.append(
                {
                    "parse_ms": parse_ms,
                    "verification_ms": verify_ms,
                    "simulation_ms": simulation_ms,
                    "optimization_ms": optimization_ms,
                }
            )
        results.append(
            {
                "name": source.name,
                "nodes": len(source.nodes),
                "tasks": len(baseline["schedule"]),
                "xml_bytes": len(xml.encode()),
                "flows": len(source.edges),
                "median_ms": {
                    key: round(statistics.median(m[key] for m in measurements), 3) for key in measurements[0]
                },
                "samples_ms": [{k: round(v, 3) for k, v in m.items()} for m in measurements],
                "verification_method": verification["method"],
                "verification_status": verification["status"],
                "solver_status_last_repeat": optimization["status"],
                "baseline_makespan": baseline["metrics"]["makespan"],
                "selected_makespan_last_repeat": optimization["selected"]["metrics"]["makespan"],
            }
        )
    output = {
        "platform": platform.system(),
        "python": platform.python_version(),
        "method": "Three warm-process repeats per case; median and all samples. Solver search budget 1 second per repeat; timings include model construction. Synthetic inputs, not real-world performance guarantees.",
        "cases": results,
    }
    path = ROOT / "docs/evidence/complex-model-benchmarks.json"
    path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"evidence": str(path.relative_to(ROOT)), "cases": results}, indent=2))


if __name__ == "__main__":
    main()
