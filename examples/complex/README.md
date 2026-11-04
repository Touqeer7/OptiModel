# Larger and nested examples

Import `nested-order.bpmn` in Studio. It combines two nested embedded subprocesses, an AND split/join, an XOR decision, multiple normal end events and manual/business-rule/send tasks. Task IDs remain traceable to the original XML. No scripts, messages or business rules are executed.

In Simulate, choose **stock_yes** (Stock available), keep one slot for each role and minutes as the time unit. Completion is **35 minutes**, with five executed tasks. The unavailable-stock route completes in **8 minutes**, with two tasks. These are different routes, not optimization improvements. No improvement is expected for these particular fixed-resource assumptions.

`nested-order-scenario.json` contains the equivalent API scenario; configure those values in the UI or supply it in a run request's `config` field. Studio does not have a scenario-file upload control.

Run `backend/.venv/Scripts/python scripts/benchmark_complex.py` from the repository root to reproduce scale measurements. The script uses 100-, 1,000- and 1,998-task sequential models and a 128-branch parallel model. It writes synthetic benchmark evidence, not user projects. Read `docs/complex-model-upgrade.md` for the implemented scope and limitations.
