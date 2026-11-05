# Verified repairs and optimized BPMN output

Automatic runs now verify, attempt supported gateway repairs, simulate a baseline, optimize the selected route, and generate a separate revised output. Manual optimization runs generate the same output. Plain manual simulation remains available without rewriting. `Scenario.produce_revised_bpmn` defaults to false for manual API scenarios; the automatic planner defaults it to true.

## Output files

| File | Meaning |
|---|---|
| `original.bpmn` | Exact imported source text as stored; never overwritten |
| `corrected.bpmn` | Full process with every original business branch and task retained; only validated gateway join-type repairs applied |
| `optimized.bpmn` | A resource-ordered execution plan for the current selected route, with BPMN DI, resolved task facts/provenance, explicit resource pools, timing and route annotations |
| `optimized.svg` | A shareable vector rendering of that output diagram |
| `changes.json` | Repairs, source/output hashes, verification methods/results, routing scope, excluded alternative-task IDs, schedule bounds/gaps and remaining queue waits |

All available files appear in the UI and ZIP bundle. The final diagram is displayed above the simulation result. PDF reports distinguish imported source from revised output and record repair/optimality scope. Old runs without these artifacts still retain their existing exports.

**The optimized execution plan covers one selected route.** It does not delete alternatives from the full process: those remain in `corrected.bpmn`. This separation is essential because one static task/resource schedule does not establish the optimal business policy across every decision outcome. The files have `isExecutable=false` when generated from the analysis representation; they are analysis plans, not automatically deployable business integrations.

## Automatic repair rule

The supported repair changes a mismatched join to match its controlling split: XOR split → XOR merge, AND split → AND join. A candidate is considered only when:

1. The split dominates the join and the join postdominates the split.
2. Branch interiors are disjoint until the join.
3. The region has no external side entry or exit.
4. Task IDs, facts and all sequence flows remain unchanged.
5. Complete supported token verification or an applicable structural proof returns `no_counterexample` after repair.

The split's stated routing semantics are authoritative; the tool does not infer a new business rule. Up to eight join repairs are considered within a bounded repair pass. The source XML is patched by gateway ID, preserving original extensions and unrelated content, then reparsed and compared with the repaired typed model. Unsupported/ambiguous structures, cyclic processes or a repair that remains inconclusive do not receive a fabricated "corrected" result.

If the original deadlocked, it has no valid completion time. The reported baseline is explicitly **after repair**, and any scheduling percentage compares that baseline with the repaired model's selected schedule. It is not a numerical improvement over a deadlock.

## Execution-plan construction and validation

The compiler retains every work task on the selected route and its resolved duration/role/provenance. It adds the original task dependencies and sequential dependencies for tasks assigned to each resource slot, removes redundant transitive edges, and introduces explicit AND splits/joins where required. It never invents task independence, deletes mandatory work, shortens durations, or increases staffing to manufacture an improvement.

The new graph must pass supported structural validation, independent token verification, an actual simulation replay, validation against the original selected-route precedences/resource capacities, official XSD checks, and a semantic XML round trip. Exported resource-pool metadata preserves staffing on reimport; physical unit conversion also converts the corresponding cost rates. The reference operations sample produces **13 → 11 hours**, and importing the generated BPMN reproduces **11 hours** with the same two technicians and task durations.

For validated acyclic AND-only graphs, topological induction proves each control node/task fires once and every flow token is consumed. This avoids enumerating independent interleavings, including in resource-ordered DAGs. Small references are compared with bounded Petri enumeration in tests. XOR graphs retain matched-region reduction or bounded reachability; this is not a claim of complete BPMN conformance or business correctness.

Resource ordering becomes precedence in the plan. Therefore plan-replay queue waits are not directly comparable with original process queue waits. Reported before/after queue waits are computed against the original task dependencies. Intrinsic workload/capacity bottlenecks can remain; the change record retains them instead of hiding them.

## Optimality and limits

- `optimality_proven=true` is set only for an analytical lower-bound certificate, a solver-proved optimum, or a validated replay reaching the solver's proved lower bound, for fixed durations/staffing and the selected route.
- Feasible or timeout results are labeled best verified feasible, with actual bounds/gaps; there is no universal "most optimized business process" guarantee.
- If resource-order compilation would exceed the existing node/flow budgets, the output is explicitly labeled **schedule annotations only**. It retains the full graph and is not presented as a verified structural rewrite or replay-equivalent plan.
- If output token verification is incomplete, no revised artifact is published.
- Unsupported events, loops, collaborations and business-condition feasibility remain outside execution scope. Arbitrary business dependencies are not rewritten automatically.

## Regression evidence

The current suite passes **191 backend tests** and **13 browser journeys**. New coverage includes both closed gateway mismatch types, rejection of an unstructured deadlock, source/vendor-extension identity, all-branch full-process preservation, selected-route exclusion disclosure, solver-bound labeling, replay improvements, invalid-candidate rejection, budget fallback, SVG escaping, resource/cost/unit round trips, conditional artifact/ZIP integrity, optimized-file reimport and automatic repair in the browser.

Screenshots: [final optimized output](evidence/final-optimized-bpmn.png), [repaired deadlock output](evidence/repaired-deadlock-bpmn.png). Run the commands in [the main validation guide](complex-model-upgrade.md) to reproduce the suite.
