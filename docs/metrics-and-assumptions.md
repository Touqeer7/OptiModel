# Metrics and assumptions

## Facts and configured inputs

Source task duration and role are nullable. Import reads explicit Studio metadata, legacy Camunda properties, task attributes, and `duration: N` documentation. A number in a task's name is never interpreted as a timing fact. Unstated values remain unknown and block simulation until entered in the scenario editor. Task metadata carries `source`, `user`, `example`, `ai_extracted` or `unknown` provenance; edits are tagged user. AI extraction remains a user-reviewed draft, not independent verification of the business description.

The analyst chooses a consistent time unit: generic time units, minutes, hours or days. Units are not silently converted or inferred from unstructured names. For descriptions with mixed or unclear units, clarify and normalize before acceptance. All three built-in examples use hours, and every duration, capacity and rate is an explicitly illustrative example assumption. Imported models with unknown roles get no magical worker pool.

One resource slot of the configured required role is occupied for the entire task interval. Resources are continuously available, non-preemptive and do not multitask. Multiple required roles per task, calendars and calendars-based labor costing are outside scope. The scenario editor changes experiment assumptions, not source XML. A run freezes its complete inputs; later form edits affect the next experiment only.

## Definitions

| Output | Definition and interpretation |
|---|---|
| Makespan / single-case completion | Latest task finish relative to a case arrival at time zero. Supported plain end/control nodes have zero duration. |
| Ready time | Time the required input flow token(s) enable that task. AND joins wait for all incoming tokens. |
| Queue wait | Task start minus ready time. Total wait sums per-task queue delays; parallel waits are not additive case cycle time. |
| Utilization by role | Sum of busy task durations for that role divided by makespan × actual configured role capacity. Idle slots count in the denominator. |
| Busy labor/resource cost | Sum of busy time per role × its configured cost rate. Absent if any rate is unknown. |
| Staffed capacity cost | Makespan × sum(capacity × configured rate). Assumes all slots paid for the full experiment horizon; it is a distinct accounting assumption, not measured savings. |
| Observed throughput | Null. A single case cannot establish multi-case observed throughput. No inverse-makespan throughput is presented. |
| Precedence lower bound | Longest weighted task path of the executed trace, ignoring resource contention; returned with task IDs and explicit scope in baseline JSON. This is not a critical-chain proof. |
| Scheduling change % | 100 × (baseline completion − selected completion) / baseline completion, using the same task durations, roles and capacities. Zero when no better schedule was accepted. |
| Solver bound / gap | CP-SAT's lower bound on completion and relative objective gap. An optimal status only applies to the supported mathematical model. |

Unused capacity is not called waste. Single-case values are not p50/p95 estimates or real-world results. Baseline uses deterministic chronological readiness and ID order, rather than an inferred operational dispatch policy.

## Decisions and reproducibility

Conditions are displayed as business-rule labels and never evaluated as code. The analyst explicitly selects an XOR outgoing flow or supplies probabilities summing to one through the API. A local seeded RNG chooses routes. No probabilities are fabricated. Repeated simulation with identical workflow/configuration/seed has identical event logs and schedules. CP-SAT uses one search worker and a configured seed; wall-time-limited search may stop at different stages on different machines, so an exact incumbent schedule is not guaranteed cross-machine. Objective/status/bounds are always recorded.

## Example evidence

Operations: durations 2, 3, 7 and 8 hours; two identical technicians; the 3-hour calibration precedes the 8-hour batch task. Baseline completion is 13 hours. The solver finds and proves 11 hours with the same resources and durations: 15.3846% simulated scheduling change. Total busy work stays 20 technician-hours and busy labor cost stays 600 at a rate of 30. Staffed capacity cost changes from 780 to 660 only under the paid-full-horizon assumption. No business saving or BPMN structural change is claimed.
