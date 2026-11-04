> Historical Studio 3.0 snapshot. For the current expanded scope, verification methods and new regression/scale evidence, read [the Studio 3.1 upgrade](complex-model-upgrade.md).

# Engineering audit

Inspected on 2026-11-04. Source branch: `main`; working tree was clean. Work branch: `feature/optimodel-studio`. No remote push or deployment is authorized.

## Baseline evidence

- Read all Python application modules, legacy tests, HTML/JS/CSS, README, startup batch file, environment example, and three XML/BPMN samples.
- System Python 3.14.3, Node 22.13.1, npm 10.9.2. Initially no pytest/networkx; virtual environment creation needed sandbox approval. Installed isolated dependencies in `backend/.venv`.
- `backend/.venv/Scripts/python -m pytest backend/tests -q`: **9 passed, 1 failed**, 3 subtests passed. Failure: Graphviz `dot` executable missing, breaking PDF rendering. Cache writes also received sandbox permission warnings.
- Imported the baseline FastAPI app successfully and enumerated its eight business routes: `/analyze`, `/prompt-to-workflow`, `/generate-xml-only`, `/convert-to-petri-net`, `/view-report`, `/download-report`, `/download-optimized-bpmn` (plus generated OpenAPI/docs routes). Startup attempted report creation and silently swallowed errors. Baseline UI requires internet CDNs; no persistent projects or run history.

## Findings and fixes

| Severity | Evidence / impact | Implemented direction |
|---|---|---|
| Critical | Shared PDF/BPMN paths allow concurrent and historical cross-downloads | Immutable model versions, UUID run directories, SQLite artifact attribution |
| High | Shared workers ignore task-specific resource metadata | Explicit role pools and non-overlapping slots in chronological event engine |
| High | Increasing worker counts compete as "optimization" | Separate fixed-resource CP-SAT and user-created capacity scenarios |
| High | Default duration 1.0 hides unknown inputs | Nullable source facts; explicit, provenance-tagged scenario settings required |
| High | XML parser lacks size/semantic limits; multiple unsupported elements skipped | Bounded safe parser, supported-element allowlist, typed graph checks |
| High | Bounded check exposes `is_sound` without full soundness proof | Bounded verification status, truncation, proper completion, reverse reachability, dead transitions, traces; no blanket soundness claim |
| High | Single-case inverse makespan presented as throughput; idle time as waste | Explicit single-case metrics, throughput null, utilization by actual role capacity |
| High | Permissive CORS, unbounded upload, raw exception detail | Same-origin local app, loopback defaults, request/compute bounds, typed sanitized errors |
| High | AI returns XML with root-only validation; unused heuristic fabricates facts | Structured extraction, explicit human review, deterministic serialization and parse-back |
| Medium | PDF has an undeclared external `dot` dependency | ReportLab topology and schedule drawings without Graphviz runtime |
| Medium | Monolithic CDN frontend; dynamic HTML and simulated percentage | Bundled React/TypeScript/bpmn-js, text escaping, truthful job stages |
| Medium | Runtime binaries and PDFs tracked | Untrack generated artifacts while retaining local copies; ignore future runtime output |
| Medium | Batch binds API on all interfaces, opens multiple windows | One same-origin local server and foreground cross-platform startup scripts |

Final validation, observed benchmark measurements and known limits are recorded in `validation-and-benchmarks.md` and `implementation-progress.md`; this audit does not imply every requested advanced feature is supported.
