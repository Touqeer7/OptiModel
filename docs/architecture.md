> Historical Studio 3.0 snapshot. For the current expanded scope, verification methods and new regression/scale evidence, read [the Studio 3.1 upgrade](complex-model-upgrade.md).

# Architecture

OptiModel Studio is a local process engineering application. It models and experiments; it does not execute business transactions or deploy a process engine. There is no account requirement, cloud backend, telemetry, CDN runtime dependency, or mandatory AI subscription.

```text
React / TypeScript / bpmn-js (bundled by Vite)
                  | same-origin /api/v1
FastAPI: input bounds, typed errors, origin/Host restrictions
                  |
  BPMN safe parser -> typed Workflow IR -> structural validation
                  |                 |
          flow-place Petri net    scenario assumptions
                  |                 |
       bounded reachability    chronological token simulation
                                    |
                        fixed-resource CP-SAT scheduling
                                    |
                independent schedule invariant validation
                                    |
SQLite metadata + per-project/per-run artifacts + ReportLab PDF
```

## Module responsibilities

| Module | Responsibility |
|---|---|
| `backend/app/domain.py` | Pydantic workflow/node/edge/scenario/resource schemas, provenance, typed diagnostics |
| `bpmn.py` | Bounded namespace-aware XML import, supported-subset validation, offline official XSD diagnostics, deterministic new-model XML/DI layout |
| `verification.py` | Flow-place Petri conversion and bounded marking exploration, counterexample traces, reverse completion reachability, transition coverage |
| `simulation.py` | Flow tokens, AND synchronization, explicit XOR selection, chronological completion heap, role-slot allocation, metrics, independent invariant checks |
| `scheduling.py` | Fixed-duration/resource interval scheduling, assignment and non-overlap constraints, CP-SAT statuses/bounds, validated candidates |
| `persistence.py` | SQLite migration v1 (`PRAGMA user_version`), transactions with deterministic connection closure, UUID IDs and safe artifact paths |
| `jobs.py` | One local worker, maximum eight outstanding jobs, real stages, cooperative cancel, restart interruption handling |
| `nlp_generator.py` | Optional OpenAI-compatible structured extraction, strict response limits, redacted errors, draft/review contract |
| `reporting.py` | Run-specific original BPMN, CSV, JSON, four-section PDF and ZIP exports, escaped report text and CSV formula defense |
| `main.py` | Versioned API, project/version/scenario/history orchestration, same-origin static frontend and offline API docs |
| `frontend/src/ScenarioEditor.tsx` | Explicit assumptions, role pools, task facts and scenario controls |
| `Diagram.tsx`, `Timeline.tsx` | BPMN navigation/selection/trace highlighting and schedule/resource visualization |
| `api.ts`, `types.ts`, `format.ts` | Typed client contract, consistent errors and numerical/date presentation |
| `App.tsx` | Workspace sections, project selection, reviewed generation, run polling and historical comparison |

## Persistence and immutability

Default store: repository `data/studio.sqlite3`. Projects, source model versions (including XML), scenarios and runs are persisted with UTC timestamps. Each run freezes its model ID, complete configuration, seed, warnings, verification and results. Each model edit creates a new ID. Reopening another version does not change old run inputs.

Artifacts live in `data/artifacts/<project UUID>/<run UUID>/`. Requests look up the run, verify the owning project is visible, require succeeded state, and use a fixed filename allowlist. Original source text is kept separately from generated display coordinates and schedule assumptions. There is no global "latest" report. Legacy shared-artifact routes return HTTP 410.

Removing a project or run hides it and its downloads; files remain on local disk. This intentional soft deletion avoids silently destroying analyst work. Run only one server against a given data directory. SQLite initialization marks interrupted queued/running jobs failed; it never invents a completed result or resumes an unknown partial computation.

## Jobs and bounded work

The executor has one worker and eight reservations (active plus queued). Verification has a 2-second / 5,000-state / 64-token budget; simulation has a 5-second / 2,000-event budget; CP-SAT has a configurable 0.01–15-second budget and one search worker. XML: 1 MB, 5,000 XML elements, depth 30, 200 IR nodes, 400 flows. Resources: at most 20 roles / 64 slots. Provider requests: at most 12,000 prompt characters, 300 KB response, 25-second network timeout, no redirects. Cancellation is cooperative between stages; a solver already running can take its remaining bounded time before freeing the worker. Canceled results are never accepted.

## Security boundary

Loopback is the startup default. Host and write-origin checks reject external sites; no wildcard CORS. All APIs bound stream bytes even without Content-Length. DTD/entities are forbidden; XML parsing disables entity resolution, network and huge trees. Unsupported flow elements, loops and nested scopes are rejected rather than flattened. User labels are React text nodes, escaped PDF paragraphs and guarded CSV fields. Provider keys stay in backend environment variables, and raw prompts/provider responses are not logged. The local data directory is not encrypted and is not a multi-user access-control boundary; use OS permissions for confidential projects.

Offline `/docs` renders the actual route inventory and links the OpenAPI JSON contract without third-party scripts. No deployment or authentication infrastructure was added.
