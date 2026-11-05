# Complex-model and prompt reliability upgrade (3.1)

## Implemented scope

This upgrade expands a bounded, local process-analysis tool. It does not establish complete BPMN conformance, unlimited scalability, reliable interpretation of every prompt, or a course grade. The semantic reference is the [OMG BPMN 2.0.2 specification](https://www.omg.org/spec/BPMN/2.0.2/PDF); original XML and vendor extensions remain separate from the analysis representation.

| Path | New behavior |
|---|---|
| Executable analysis import | Up to 2,000 flow nodes, 6,000 sequence flows, 10,000,000 UTF-8 bytes, 100,000 XML elements, nesting depth 64 |
| Nested processes | Regular embedded subprocesses with exactly one plain internal start/end and one external entry/exit are expanded; child IDs and original XML retained |
| Additional work nodes | Manual, send, receive, script and business-rule tasks are modeled as timed work; no code, messages or integrations are executed |
| Events | One plain root start; one or more normal root ends; none intermediate throw events |
| Larger parallel models | Conservative series/parallel reduction avoids enumeration of independent task interleavings when a certificate is available |
| Conditional optimization | The same explicitly selected/seeded XOR trace can be optimized without changing routing, task facts or resource capacities |
| Static assessment | `/api/v1/inspection` inventories multiple scopes, cycles and bad references even when execution semantics are unsupported; failed UI imports display this read-only assessment when XML is safe to inspect |
| Generation | Up to 60,000 prompt characters; prose/list/arrow/table instructions; explicit units; common provider content wrappers; one schema/topology repair; token-deadlock checks; clarification responses without invented tasks |
| UI and reports | Local loading/error feedback, draft diagnostics, verification method, model complexity, source units, scope inventory and optimization method |

The 2,000-node cap includes starts, ends, gateways and expanded internal subprocess boundary nodes. It is not a 2,000-task guarantee. All normal source XML checks remain in force: DTDs/entities are rejected, references stay within scope, IDs are unique, and unsupported semantics are diagnosed rather than silently discarded.

## Verification argument and scope

The structural certificate is deliberately conservative. On a directed acyclic single-entry/single-exit graph, it repeatedly removes serial vertices and collapses complete fork/join regions only when every branch goes to the same join and the fork/join types match (AND/AND or XOR/XOR). It accepts only when the entire graph reduces to one start-to-end edge. The certificate records serial and matched-region reductions. No markings are enumerated in this method, so `states` is correctly zero.

Graphs that do not reduce use flow-place Petri reachability with explicit time, state, token and marking-memory budgets. A reached limit produces `inconclusive`; it never becomes successful exhaustive verification. Multiple normal ends complete only when active flow tokens are consumed; an end on one branch does not cancel other branches. Full workflow-net soundness and feasibility of business conditions are not claimed.

Tests compare the structural certificate with complete token enumeration for the reference examples and 16 generated nested AND/XOR models. Mismatched joins fall back to token analysis and yield counterexamples. This is regression evidence, not a formal proof covering every possible BPMN extension.

## Scheduling argument

Sequence-flow adjacency is indexed once. The selected execution graph removes unselected XOR edges and unreachable branches. Nearest upstream task dependencies enforce the same transitive precedence without constructing every ancestor-pair constraint. An independent validator checks selected-task coverage, unchanged durations, finite times, resource eligibility/capacity and precedence.

Before invoking CP-SAT, the optimizer calculates precedence and per-role workload lower bounds. If the feasible baseline meets that bound, it is certified optimal with method `analytical_lower_bound`; no solver search is claimed. Otherwise bounded CP-SAT search returns its actual status, bound and gap. A timeout retains the feasible baseline. Search limits do not include Python model construction. Durations below 0.001 scenario units or outside exact millisecond-scale precision are not rounded into solver input.

The scheduling formulation optimizes a task schedule. The later [revised-output pipeline](revised-bpmn-output.md) separately compiles resource ordering into a selected-route BPMN, with supported gateway repairs and verification. `original.bpmn` remains the imported source, including subprocesses and source DI. There is no claim that a differently selected route is an optimization gain.

## Prompt behavior

The provider receives the description and schema. If JSON/schema/topology fails, one follow-up contains the previous answer and sanitized validation feedback; no credentials enter those messages. Common fenced JSON and text-block content are accepted. HTTP/auth/rate-limit/network failures remain explicit, output is size-bounded, and at most two extraction requests run concurrently. The provider-call time allowance is bounded; oversized/truncated responses are rejected.

When the provider cannot produce a faithful supported process, it can return clarification questions instead of an invented workflow. Material ambiguities produce clarification questions instead of offering a placeholder or partially specified draft for acceptance. Draft acceptance rejects discovered token deadlocks. Human review is still necessary: schema checks and repair do not prove that an AI preserved every detail or correctly understood a language. Mixed timing units are normalized by the provider into an explicit common unit; source units then survive XML round trips. Physical scenario-unit changes convert source durations and user overrides; costs are converted consistently. A day means 24 continuous hours, not an assumed work shift.

## Evidence and reproduction

Run from the repository root:

```powershell
backend/.venv/Scripts/python -m pytest backend/tests -q
backend/.venv/Scripts/python -m ruff check backend/app backend/tests scripts
backend/.venv/Scripts/python -m ruff format --check backend/app backend/tests scripts
backend/.venv/Scripts/python scripts/benchmark_complex.py
cd frontend
npm run lint
npm run typecheck
npm run format:check
npm run build
npm run test:e2e
```

The backend regression suite contains **191 passing tests**. All thirteen browser journeys pass. The browser suite covers the original journey, mobile/XOR routing, reviewed generation, unsupported-source assessment, loading/provider errors, clarification responses nested-subprocess import/simulation, and condition-free XOR import with explicit route selection. Browser tests use an isolated temporary database; benchmark inputs are synthetic and do not access user projects.

Live smoke checks against the configured provider returned HTTP 200 for a two-task sequence, a six-task parallel/decision process, and a vague-input clarification. The two defined processes returned no token counterexample; the vague input offered no placeholder draft after the final guard. See [the recorded summaries](evidence/live-generation-checks.json). These synthetic checks do not prove general extraction fidelity.

See [raw benchmark measurements](evidence/complex-model-benchmarks.json). Three warm-process repeats per input record all samples and medians. Search is limited to one second per benchmark run. The 1,998-task sequence contains exactly 2,000 analysis nodes. The 128-branch test demonstrates parallel verification without enumerating exponentially many interleavings. Measurements describe this Windows/Python host, not universal performance or a statistical scalability guarantee.


| Synthetic input | Parse median | Verification median | Simulation median | Scheduling median |
|---|---:|---:|---:|---:|
| 100-task benchmark | 7.12 ms | 1.12 ms | 3.60 ms | 1.87 ms |
| 1000-task benchmark | 114.98 ms | 50.88 ms | 122.97 ms | 17.68 ms |
| 1998-task benchmark | 316.30 ms | 189.70 ms | 389.95 ms | 36.14 ms |
| 128 independent parallel tasks | 13.47 ms | 2.63 ms | 7.48 ms | 1034.91 ms |

Use [the nested order example](../examples/complex/nested-order.bpmn) and [its scenario](../examples/complex/nested-order-scenario.json) for a reviewable demonstration. The stock-available route completes in 35 illustrative minutes; unavailable stock completes in 8. Different routing is explicitly not counted as improvement.

## Remaining limits

- Execution/simulation still requires one acyclic process instance, one activation per node, fixed positive task durations and continuously available single-role slots (64 total slots).
- Cycles, multi-instance tasks, event subprocesses, call activities, inclusive/event-based/complex gateways, timers/boundary/termination/message events and multi-pool orchestration receive structural inspection only. Embedded subprocesses with multiple internal endings or aggregate timing are not flattened into guessed behavior.
- No arrivals, multi-case throughput, stochastic distributions, calendars, preemption, multiple simultaneous roles per task, arbitrary business process redesign. Validated selected-route BPMN export and bounded gateway repair are implemented separately.
- Unstructured parallel graphs can reach bounded verification limits. A feasible scheduling result does not prove business-condition feasibility or process-wide optimality across routes.
- Browser diagrams and tables may become cumbersome near the import cap; engine benchmarks do not establish browser frame-rate guarantees. PDF topology remains summarized above 45 nodes, with the complete BPMN and JSON available separately.
- Multilingual generation is provider-dependent; PDF fonts do not guarantee every script. Local storage is not a multi-user security boundary. See the earlier architecture and engineering audit for persistence and deployment scope.

## Optional XOR condition metadata

An XOR split may be imported without condition expressions or a default flow. Each such branch receives a warning, while its source XML and IDs remain unchanged. Verification still explores alternatives; simulation and selected-trace optimization still require an explicit scenario route or supplied probabilities. A default flag never silently selects a branch. Multiple defaults, invalid references and genuine token deadlocks retain their existing checks. Generated drafts receive the same nonblocking warnings without unnecessary AI repair or invented conditions.

## Automatic simulation follow-up

The browser now starts a labeled demo simulation after imports, sample selection and reviewed-draft acceptance by default. It also starts on entering Simulate for an existing model without a current run. Missing inputs use disclosed, deterministic assumptions, with optional manual controls afterward. See [automatic simulation](automatic-simulation.md) for policies, API, provenance and limits. The earlier manual requirement for explicit scenario values remains in the manual API; the automatic endpoint constructs and records those values before using the same engine.

## Revised-output follow-up

Automatic runs now also attempt verified closed split/join repairs and publish a selected-route optimized BPMN/SVG, full-process corrected BPMN and change record. The acyclic AND-only token-induction method supplements the earlier reduction/reachability methods. See [the precise rules, replay evidence and limits](revised-bpmn-output.md).
