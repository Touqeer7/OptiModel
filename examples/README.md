# Transparent example inputs

These files match the three built-in samples in `backend/app/samples.py` and the `/api/v1/samples` API. Regenerate them with `backend/.venv/Scripts/python scripts/export_examples.py`.

| File | Process | Explicit demonstration assumptions |
|---|---|---|
| `order.bpmn` | Order preparation in parallel, synchronized before dispatch | Inventory 4 hours, invoice 7 hours, dispatch 2 hours; Operations capacity 2; rate 25 per slot-hour |
| `loan.bpmn` | Review followed by an approved/declined XOR decision and merge | Review 4 hours, approved offer 3 hours, decline notice 1 hour; Analyst capacity 1; rate 40; supplied scenario explicitly selects approved flow |
| `operations.bpmn` | Competing jobs and a downstream calibration dependency | Labels 2 hours, calibration 3, inspection 7, calibrated batch 8; Technician capacity 2; rate 30 |

Each matching `.scenario.json` contains a full API configuration with hours, capacities, rates, seed and routing where applicable. In the UI, selecting the built-in sample preloads these settings. Importing just the BPMN preserves task metadata but requires the analyst to choose scenario capacities/units/rates explicitly; there is no silent staffing inference. All values are example assumptions, not observed business measurements.
