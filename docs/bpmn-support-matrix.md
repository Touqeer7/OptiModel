# BPMN support and optimization guarantees

The authority is [OMG BPMN 2.0.2](https://www.omg.org/spec/BPMN/2.0.2/), including its normative [BPMN XML schema](https://www.omg.org/spec/BPMN/20100501/BPMN20.xsd). Those schemas are vendored for offline validation. Supporting a useful subset does not establish full BPMN conformance.

| Construct / property | Import and validation | Simulation | Fixed-resource optimization |
|---|---|---|---|
| Exactly one acyclic process, plain start/end | Supported; all elements on a start-to-end path | One process instance | Supported deterministic DAG |
| `task`, `userTask`, `serviceTask` | Supported as modeled work, not executable business integrations | One eligible role slot; fixed positive duration | Fixed durations, role eligibility, optional slot assignments |
| Sequence flow | Unique IDs, known endpoints, explicit incoming/outgoing declarations checked when present | Flow tokens | Transitive task precedence constraints |
| Parallel split / join | Separate 1:N split and N:1 join required | Split emits all tokens; join consumes every incoming token | All branch tasks mandatory; synchronization reduces to precedence |
| Exclusive split / merge | Conditions or default branch required; separate split and merge | Explicit selected flow or supplied seeded probabilities; merge consumes selected token without waiting for unselected branch | Unavailable; returns `unsupported` and baseline |
| Source DI, labels, extensions | Source text retained; missing DI gets a separate generated display layout | Extensions are metadata, not process-engine execution | Original BPMN never changed by scheduling |
| Lanes, text annotations, associations | Retained in source; non-executing visual context | No timing/eligibility inference from lanes | No hidden staffing inference |
| Loops, multiple instances, nested process / subprocess | Rejected with diagnostics | Unsupported | Unsupported |
| Inclusive, event-based, complex gateway | Rejected with element ID | Unsupported | Unsupported |
| Intermediate/boundary events; timers, messages, compensation | Rejected; non-unit token quantities rejected | Unsupported | Unsupported |
| Collaboration/message orchestration, multiple starts/ends | Rejected | Unsupported | Unsupported |
| Resource calendars, preemption, simultaneous multi-role work | Not modeled | Unsupported | Unsupported |

## Validation distinctions

1. Safe XML syntax and complexity checks precede interpretation.
2. Official XSD diagnostics are separate from strict supported-IR graph checks. Legacy nonstandard timing attributes can cause XSD warnings without silently becoming verified BPMN semantics.
3. Structural validation checks IDs, scope, source-to-end reachability, graph acyclicity, task/gateway degrees, explicit branch conditions, references and flow declarations. A source may be syntactically valid BPMN yet outside this release's supported subset.
4. Petri analysis uses flow places and element transitions, with separate alternative transitions for XOR. It explores all routing alternatives, independent of business-condition feasibility. Results are `no_counterexample`, `counterexample`, or `inconclusive`. Truncation is never reported as successful verification. Proper completion, reverse reachability from the exact final marking, transition coverage, deadlocks and a bounded trace are exposed. No complete workflow-net soundness claim is made.
5. Simulation can still fail on a selected trace that deadlocks or leaves tokens. Production jobs reject models where bounded verification already found a counterexample.

## Solver guarantee

CP-SAT minimizes single-instance makespan with immutable task durations, eligible role pools, individual slot intervals, non-overlap and task-precedence constraints. The feasible baseline is supplied as a hint and an upper bound. Every returned candidate is rechecked independently for task coverage, positive timing, unchanged durations, precedence and eligible non-overlapping resource assignment.

Durations must be exact multiples of 0.001 scenario time units; other values are simulated without rounding but optimization returns `unsupported`. `optimal` means a proof within this scheduling formulation, not proof of real-world improvement. `feasible` is a bounded candidate with the available objective bound/gap; `timeout` retains baseline. `infeasible`/`invalid` never cause manufactured gains. XOR optimization is unavailable. Identical/worse makespan retains baseline and reports zero improvement. Capacity changes belong to separate historical scenario comparisons, never the fixed-resource gain. No revised BPMN is generated because this implementation makes no structural transformations.
