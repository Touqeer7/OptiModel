> Historical Studio 3.0 snapshot. For the current expanded scope, verification methods and new regression/scale evidence, read [the Studio 3.1 upgrade](complex-model-upgrade.md).

# Implementation progress

## Completed checkpoints

1. Inspected clean main branch and all original application modules, frontend, tests, samples, README and startup/configuration. Created `feature/optimodel-studio`. Baseline: 9 tests passed / 1 missing-Graphviz failure after dependency setup; initial system interpreter lacked dependencies.
2. Replaced the legacy parser/optimizer/report pipeline with typed IR, secure bounded XML import, namespace/scope/reference validation, explicit unsupported-semantic errors and immutable original text. Vendored official OMG schemas.
3. Implemented flow-place Petri conversion with XOR alternatives, bounded state exploration, counterexample traces, exact completion checks and reverse completion reachability. Removed the old blanket soundness boolean.
4. Implemented chronological single-case token simulation, actual role-slot eligibility, AND synchronization, explicit XOR choices, seeded probabilities, event logs, independent schedule validation and honest metrics.
5. Implemented OR-Tools CP-SAT fixed-resource scheduling, solver status/bounds/gaps, bounded search, baseline fallback and no rewritten BPMN claim.
6. Added migration v1 SQLite projects/model versions/scenarios/runs, one bounded local worker, real job stages, cooperative cancel, interrupted-run failure, safe per-run export paths and restart-persistence tests. Corrected deterministic SQLite connection closure and sticky cancellation during review.
7. Replaced CDN HTML/JS with bundled React/TypeScript/Vite/bpmn-js, local IBM Plex fonts, consistent drafting palette, model inspector, task/role configuration, validation, timeline, comparison, history, exports and responsive navigation. Split the scenario editor, diagram, timeline and typed API into modules.
8. Added optional structured AI extraction, explicit draft review/acceptance, deterministic BPMN/DI generation and parse-back checks. Makerend compatibility remains, but no model name is invented. File/sample flows need no AI configuration.
9. Added per-run PDF/BPMN/CSV/JSON/ZIP, source identity, recorded inputs, utilization, solver and verification scope, assumptions and limitations. Actual report pages were rendered and inspected. Improved branch lane layout after screenshot review.
10. Added foreground, loopback, cross-platform startup, an isolated test server, offline API documentation, exact dependency locks and the engineering documentation set. Legacy shared-artifact API routes now return 410 with migration guidance.

## Verification commands and evidence

See `validation-and-benchmarks.md` for the final command ledger, test counts, benchmark measurements and what was not run. Initial browser failures exposed accessible navigation names, an asynchronous AI draft-reset race and mobile scroll overflow; all were corrected and the four journey tests then passed. Screenshots in `docs/evidence/` were captured by Playwright, not fabricated. Sample report pages were rendered using PyMuPDF because Poppler is absent in this host.

Final review also added a regression for BPMN flows literally named `source` or `sink`: Petri flow-place IDs are now namespaced and expose an explicit source-ID map, preventing collision with internal initial/final places. Comparison timeline selection opens the correct historical source model and element inspector. Final suite: **86 Python tests and four browser journeys passed**. Production startup was checked at `http://127.0.0.1:8001`; the pre-existing port 8000 service was preserved.

Code checkpoints: `dd6b0b2` (backend, persistence, exports, local startup and examples), `f4ac987` (bundled UI/browser tests), `373b1cc` (Petri ID collision regression), `5d157a5` (comparison inspector). Work remains on `feature/optimodel-studio`; nothing has been pushed or deployed. The exact changed paths are recorded in `change-manifest.md`.

## Explicit remaining limits

- Single-case, fixed-duration, continuously available role pools only. No arrivals, stochastic duration percentiles, calendars, preemption, multiple simultaneous roles per task or process execution.
- Loops, subprocesses, advanced events/gateways and multi-process orchestration rejected. XOR simulation is conditional on explicit choices; its scheduling optimization is unavailable.
- No structural BPMN redesign or revised BPMN export. Source XML edits create a new validated version; the UI offers XML editing rather than a graphical modeler.
- Capacity scenarios are user-configured comparisons; automated Pareto planning is not implemented. No capacity increase is counted as fixed-resource gain.
- Complete soundness is not claimed. Bounded verification can be inconclusive and explores branch choices without proving feasibility of business conditions.
- AI has mocked success/error/UI evidence only; no live provider credentials were used. Human review remains essential to fidelity. No model repair loop; invalid output returns a clear error or review draft.
- Soft deletion retains local files. Local storage uses OS file permissions, not encryption or multi-user authentication. Use one server per data directory.
- Report topology is omitted above 45 nodes with an explicit note; complete original BPMN and JSON remain available. PDF uses standard fonts; full multilingual glyph coverage is not guaranteed.
- Windows execution is verified here. Linux/macOS commands are provided but not executed on this Windows host. There is no deployment or remote push.

## Next useful work

Prioritize mixed-unit structured timing metadata, multi-case arrivals with measured throughput, conditional-trace optimization, visual model editing with semantic validation, broader Unicode PDF fonts, and further UI controller/component extraction. These must preserve the existing evidence and supported-subset boundaries.
