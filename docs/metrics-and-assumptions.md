# Metrics and assumptions

## Facts and configured inputs

Source task duration and role are nullable. Import reads explicit Studio metadata, legacy Camunda properties, task attributes, and `duration: N` documentation. A number in a task's name is never interpreted as a timing fact. Manual scenarios require missing values to be entered. Automatic demo scenarios supply disclosed illustrative values (one time unit, Demo worker, one slot per role, and a default or first decision branch); source facts remain unchanged. Task metadata carries provenance; AI extraction remains a user-reviewed draft, not independent verification of business meaning.

The scenario records a consistent unit: generic time units, minutes, hours or days. Units are not inferred from unstructured names. Mixed or unclear units need clarification. Built-in example durations, capacities and rates are illustrative. The site distinguishes automatic defaults from imported facts and freezes the complete scenario in each run.

One resource slot of the configured required role is occupied for the entire task interval. Resources are continuously available, non-preemptive and do not multitask. Multiple required roles per task, calendars and calendars-based labor costing are outside scope. The scenario editor changes experiment assumptions, not source XML. A run freezes its complete inputs; later form edits affect the next experiment only.

## Definitions

| Output | Definition and interpretation |
|---|---|
| Reachable states | Unique reachable flow-place Petri markings, including initial and final markings. Completed enumeration is exact. Series/parallel single-entry/exit reduction can count markings exactly without enumeration: serial composition adds, XOR regions sum branch counts, AND regions multiply them. Exact large counts are decimal strings in JSON. Interrupted enumeration is a lower bound. Proofs that enumerate zero states are never presented as zero reachable states. |
| Deadlock count | Reachable non-final markings with no enabled transition. Exact after complete enumeration or a zero-deadlock structural proof; otherwise a lower bound. |
| Bottleneck count | Activities with resource queue wait greater than 1e-7, and distinct affected role pools, reported separately. This is a queue-based criterion, not a complete diagnosis of every throughput constraint. |
| Time wasted: demonstrated avoidable waiting | max(0, reference total waiting - final total waiting). The reference is the initial executable model, or a separately labeled repaired baseline. The final value is zero additional reduction demonstrated, not a proof that no avoidable waiting remains. Uncompared/unexecutable values are N/A. |
| Time wasted: demonstrated avoidable idle | max(0, reference idle slot-time - final idle slot-time), under identical capacities. Total actual idle capacity is reported separately and is not automatically all waste. |
| Makespan / single-case completion | Latest task finish relative to a case arrival at time zero. Supported plain end/control nodes have zero duration. |
| Ready time | Time the required input flow token(s) enable that task. AND joins wait for all incoming tokens. |
| Queue wait | Task start minus ready time. Total wait sums per-task queue delays; parallel waits are not additive case cycle time. |
| Utilization by role | Sum of busy task durations for that role divided by makespan × actual configured role capacity. Idle slots count in the denominator. |
| Busy labor/resource cost | Sum of busy time per role × its configured cost rate. Absent if any rate is unknown. |
| Staffed capacity cost | Makespan × sum(capacity × configured rate). Assumes all slots paid for the full experiment horizon; it is a distinct accounting assumption, not measured savings. |
| Throughput: simulated completion rate | Completed simulated cases / observation period [0, makespan], currently one case. It is not measured business or steady-state throughput. The legacy `observed_throughput` field remains null; the explicitly scoped rate lives in `performance_evaluation`. Zero observation periods produce N/A. |
| Average waiting time | Total resource queue wait / executed task instances; uses original process dependencies even when resource-order edges are written into the final BPMN. |
| Degree of concurrency | Maximum simultaneous running activities and time-weighted average simultaneous running activities = total busy task time / makespan. Half-open intervals [start, finish) prevent adjacent tasks being counted as concurrent. This is observed concurrency, not the graph's theoretical parallelism. |
| Total idle capacity | Sum over roles of (makespan × slots - busy role time), in slot-time units. Overall utilization uses summed busy / summed available slot-time; the report also shows percentages by role. |
| Precedence lower bound | Longest weighted task path of the executed trace, ignoring resource contention; returned with task IDs and explicit scope in baseline JSON. This is not a critical-chain proof. |
| Scheduling change % | 100 × (baseline completion − selected completion) / baseline completion, using the same task durations, roles and capacities. Zero when no better schedule was accepted. |
| Solver bound / gap | CP-SAT's lower bound on completion and relative objective gap. An optimal status only applies to the supported mathematical model. |

Unused capacity is not called waste. Single-case values are not p50/p95 estimates or real-world results. Baseline uses deterministic chronological readiness and ID order, rather than an inferred operational dispatch policy.

## Decisions and reproducibility

Conditions are displayed as business-rule labels and never evaluated as code. The analyst explicitly selects an XOR outgoing flow or supplies probabilities summing to one through the API. A local seeded RNG chooses routes. No probabilities are fabricated. Repeated simulation with identical workflow/configuration/seed has identical event logs and schedules. CP-SAT uses one search worker and a configured seed; wall-time-limited search may stop at different stages on different machines, so an exact incumbent schedule is not guaranteed cross-machine. Objective/status/bounds are always recorded.

Automatic mode discloses its default/first-branch choice. Structural verification explores alternatives without evaluating business conditions. A revised execution plan represents the recorded selected route; state-count reductions can reflect excluded alternatives rather than an efficiency improvement.

## Site and report contract

The Model page shows all metric rows for the initial source. Simulate and Optimize show initial/final columns and signed changes. A deadlocked original retains its structural counts but has N/A timing, queueing, utilization and concurrency. Its repaired baseline gets a separate column; timing changes compare repaired baseline to final, while structural changes compare initial source to final. Unsupported BPMN remains structural inspection only.

Every new successful run stores the same `performance_evaluation` object in its API result and `results.json`; the PDF renders its comparison rows, role utilization, bottleneck details and definitions. Existing run artifacts remain immutable; run again to create a report with the added evaluation. Read-only `POST /api/v1/models/{id}/evaluate` with `{}` previews a demo source evaluation; `{ "config": <full Scenario> }` uses supplied assumptions without creating a run or repairing source XML.

Lower waiting, fewer states, more utilization and more concurrency are not universally equivalent to a better process. Signed changes remain visible, including queueing regressions in a makespan-optimal schedule. Unknown data is N/A, not a fabricated zero.

## Example evidence

Operations: durations 2, 3, 7 and 8 hours; two technicians; the 3-hour calibration precedes the 8-hour batch task. Baseline completion is 13 hours; selected completion is 11 hours: 15.3846% simulated improvement. Busy work stays 20 technician-hours. Idle capacity falls from 6 to 2 technician-hours. Utilization rises from 76.9231% to 90.9091%; average concurrency from 1.5385 to 1.8182; simulated completion rate from 0.0769 to 0.0909 cases/hour. Maximum concurrency is two. Queue wait depends on the selected optimal tie and is computed from the actual accepted schedule; it is not assumed to decrease. The final selected-route BPMN preserves source task facts and encodes the resource schedule, while original XML is retained separately.
