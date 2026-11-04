# Validation and measured benchmarks

Recorded 2026-11-04 on Windows x64, Python 3.14.3, Node 22.13.1, npm 10.9.2. All results below are observed commands, not targets. This host did not execute Linux/macOS application startup or use live AI credentials.

## Command ledger

Commands run from repository root unless marked `frontend/`.

| Command | Final observed result |
|---|---|
| `backend/.venv/Scripts/python -m pytest backend/tests -q --tb=short` | **86 passed**, 1 upstream Starlette/httpx deprecation warning, 8.25 seconds |
| `backend/.venv/Scripts/python -m ruff check backend/app backend/tests run.py scripts` | Passed |
| `backend/.venv/Scripts/python -m ruff format --check backend/app backend/tests run.py scripts` | Passed (last formatting pass includes the final changes) |
| `npm run lint` (`frontend/`) | Biome checked 10 source files; no diagnostics |
| `npm run typecheck` (`frontend/`) | TypeScript passed |
| `npm run format:check` (`frontend/`) | Prettier passed all matched source/config/E2E files |
| `npm run build` (`frontend/`) | Production build passed; Vite 7.3.7; main JS 471.42 KB / 142.14 KB gzip in this build |
| `npm run test:e2e` (`frontend/`) | **4 passed**, 13.4 seconds, installed Chrome, isolated store and localhost port 8017 |
| `npm audit` (`frontend/`) | **0 vulnerabilities**, production and development dependency tree after replacing the affected lint chain |
| `npm audit --omit=dev` (`frontend/`) | **0 vulnerabilities** |
| `backend/.venv/Scripts/python -m pip check` | No broken requirements found (dependency consistency, not a vulnerability audit) |
| `python run.py --check` | Local dependencies and bundled UI ready |
| `python run.py --port 8001` | Actual foreground startup succeeded on loopback; existing service on port 8000 preserved |
| `backend/.venv/Scripts/python scripts/export_examples.py` | Exported the three BPMN models and paired scenario JSON files |
| `backend/.venv/Scripts/python scripts/benchmark.py` | Generated measured JSON, a real four-page PDF and four rendered page PNGs |
| `git diff --check` | Passed |

The initial baseline after dependency installation was **9 passed / 1 failed** (missing Graphviz executable), not a passing legacy suite. The legacy contracts were replaced intentionally: the new suite tests original fixture compatibility and the new truthful semantics instead of retaining inverse-makespan throughput or a blanket soundness boolean. Existing sample files were retained unchanged.

An actual online npm audit initially found a moderate minimatch denial-of-service advisory in the development ESLint chain. That chain was removed and replaced with Biome 2.6.5, retaining integrated accessibility, React-effect and TypeScript linting. Final online audits reported zero findings. This does not establish an absolute security guarantee. Python dependency vulnerability scanning was not run; `pip check` only verifies dependency compatibility.

## Reference and invariant evidence

- Sequence 4 + 3 completes at 7.
- Parallel tasks 4 and 7 complete at 7 with two eligible slots, 11 with one.
- XOR executes the selected branch only; its merge does not wait for an unselected token. Replacing its merge with AND produces actual bounded deadlock traces.
- Twelve seeded generated parallel-chain/role cases check exact task coverage, precedence, eligible slots, non-overlap, fixed durations, reproducibility and candidate feasibility independently. Solver results cannot exceed baseline completion.
- Unknown durations and unavailable skills fail explicitly. Nonfinite values, missing/invalid probabilities, unsupported precision, unsupported elements, loops, dangling references, duplicate IDs, contradictory flow declarations, nested scopes, XXE and size limits are covered.
- Fixed-resource operations reaches an optimal 11-hour schedule from a 13-hour baseline with identical resources. No-improvement, unsupported and timeout fallback contracts are tested.
- API tests cover independent project/run artifacts, full pipeline and all five exports, reopen after application restart, immutable versions, project ownership, soft deletion, CORS/origin/Host/body boundaries, safe error responses, queue limit, running cancellation, restart interruption and offline docs.
- Provider tests cover structured success, explicit review requirement, material ambiguity, unknown facts and provenance round-trip, malformed JSON/XML-shaped output, oversized response, missing key, HTTP 401/404/429/500, timeout and redirect/HTTPS controls. No live provider was contacted.

## Browser journeys

1. Real file import → render → validate → configure resources → simulate → optimize → compare historical runs → actual PDF download → reload and reopen history. Browser page errors are asserted absent.
2. Sample loan review → explicit declined route → only decline branch in schedule → 390-pixel mobile layout without page overflow → unsafe user labels stay text.
3. Structured extraction mocked at the HTTP boundary → visible review draft → acceptance disabled before explicit review → real server acceptance/import. Backend provider behavior is independently mocked below the network boundary in the Python suite.
4. Unsupported subprocess file → actionable element-ID diagnostics → no accepted model.

Screenshots are real Playwright captures: `workspace.png`, `model.png`, `optimization.png`, `mobile.png`. All four sample PDF pages were rendered with PyMuPDF and inspected. Poppler is absent; Graphviz is no longer an app dependency. No accessibility conformance certification, coverage percentage or statistically significant performance claim is made.

## Benchmarks

Source and full outputs: `scripts/benchmark.py`, `docs/evidence/benchmarks.json`. One warm-process observation per deterministic sequence case, after OR-Tools import; default verification limits and a 2-second solver budget. These are measured reference timings, not a throughput or scaling guarantee.

| Tasks | XML bytes | Parse ms | Verification ms | Simulation ms | CP-SAT total ms | States | Result |
|---:|---:|---:|---:|---:|---:|---:|---|
| 10 | 8,948 | 1.507 | 0.214 | 0.560 | 5.302 | 13 | Optimal; completion 34 time units |
| 150 | 117,086 | 20.696 | 8.700 | 17.887 | 678.131 | 153 | Optimal; completion 594 time units |

Sequence cases have no parallel scheduling opportunity. The same supported process cannot gain time by reordering them, so the baseline is retained honestly. Resource/memory profiling and repeated-sample performance distributions were not measured.

Operations sample (all example assumptions): completion **13 → 11 hours**, proven bound **11**, relative gap **0**, scheduling change **15.384615%**, two Technician slots throughout. Busy work remains **20 technician-hours** and busy labor cost **600**. Utilization changes **76.923% → 90.909%** because the paid horizon becomes shorter. Staffed-capacity cost **780 → 660** is conditional on the explicit full-horizon payment assumption. No observed throughput or real-world saving is inferred.

## Remaining practical limits

See `implementation-progress.md` and `bpmn-support-matrix.md`: no multi-case/stochastic-duration semantics, calendars, advanced BPMN constructs, graphical modeling, XOR solver or structural redesign. Capacity comparisons are manual scenarios, not automated Pareto planning. No deployment, remote push, live-provider validation or non-Windows runtime verification was performed. Broader Unicode PDF fonts and further frontend controller extraction remain useful follow-ups.
