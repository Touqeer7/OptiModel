# Automatic simulation

Automatic simulation is enabled by default in the browser. Import a supported BPMN/XML file, choose a sample, or accept a reviewed AI draft. Studio creates a saved run, verifies token behavior, repairs supported gateway mismatches, runs the baseline and fixed-resource optimization, generates a revised diagram, writes reports and opens the results without requiring timing/resource forms. Opening Simulate for an existing model without a current run also starts an automatic attempt. Refreshing a completed current run reopens its history rather than launching it again.

The Workspace checkbox **Run simulation automatically** is a persistent browser preference. Turn it off to use the original manual workflow. Existing models also have a **Run automatically** action. The manual configuration remains available under **Adjust assumptions or optimize (optional)**. AI drafts still require process review before acceptance; automatic simulation does not approve an AI process on the user's behalf.

## Assumptions and factual boundaries

| Input | Policy |
|---|---|
| Source or supplied task duration | Preserve it; convert explicit source units to the selected scenario unit once |
| Missing duration | Assume 1 scenario time unit |
| Unknown physical time unit | Use generic `time units`; never guess minutes or hours |
| Source or supplied role | Preserve it |
| Missing role | Use `Demo worker` |
| Supplied resource capacities/costs | Preserve valid supplied values |
| Missing role capacity | Assume one continuously available slot; leave cost unknown |
| Supplied XOR route/probabilities | Preserve and validate; seeded probabilities remain reproducible |
| Missing XOR selection | Use the declared default, otherwise the first outgoing flow in source order; never evaluate or infer business conditions |

Every automatic run is labeled **Automatic demo simulation**. Generated task settings have `assumed` provenance when missing facts are filled. Scenario capacity and routing assumptions are recorded with the run. Results remain illustrative, not measured business performance. In particular, one shared worker can serialize parallel tasks; different staffing is a different scenario.

`config.execution_mode` and `config.automatic_assumptions` persist in SQLite history and `results.json`. The CSV records task-setting provenance, the PDF identifies the automatic demo, and the UI displays the assumptions. Large assumption lists are summarized in the UI/PDF, with the complete list in JSON. The imported XML and `original.bpmn` stay unchanged. Optional edits produce a new run with refreshed assumption notes.

## API and limits

```text
POST /api/v1/projects/{project_id}/runs/auto
{"model_id": "<saved-model-id>"}
```

An optional `config` may supply a unit, seed, solver limit, resources, partial task duration/role overrides, routes, and probabilities. Invalid explicit values are rejected instead of silently changed. The endpoint uses the existing bounded job queue, ownership checks, persistence and artifact exports. It runs locally and makes no AI/provider calls.

The manual `/runs` endpoint still requires complete valid simulation inputs. Automation does not expand BPMN execution semantics, bypass discovered deadlocks, or simulate unsupported events/loops. A token counterexample triggers a bounded supported split/join repair pass when revised output is enabled. Unrepairable or unverifiable models produce a failed run with no fabricated metrics. See [the repair and export rules](revised-bpmn-output.md). The existing 64-total-resource-slot and import limits apply.

## Validation

The regression suite covers missing inputs, preservation of supplied values and capacities, unit conversion, deterministic routing, explicit probabilities, invalid overrides, source/export identity, edited notes, project ownership and genuine deadlocks. Browser journeys demonstrate importing a model without metadata, selecting a sample with two technicians, accepting a reviewed draft, and reopening a completed automatic run without simulation form entry. Screenshot: [automatic results](evidence/automatic-simulation.png).
