"""One worker and a bounded queue. Cancel is cooperative; solver time is bounded."""

import logging
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore

from .domain import DomainError, Scenario, Workflow
from .scheduling import optimize
from .simulation import simulate
from .verification import verify

log = logging.getLogger(__name__)


class Jobs:
    def __init__(self, store):
        self.store = store
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="studio")
        self.capacity = BoundedSemaphore(8)

    def reserve(self):
        return self.capacity.acquire(blocking=False)

    def submit(self, run_id):
        try:
            self.executor.submit(self.execute, run_id)
        except Exception:
            self.capacity.release()
            self.store.update_run(run_id, state="failed", stage="failed", error="Job executor unavailable.")
            raise

    def stage(self, ident, stage):
        run = self.store.get("runs", ident)
        if not run or run["state"] == "canceled":
            return False
        self.store.update_run(ident, state="running", stage=stage)
        return True

    def execute(self, ident):
        try:
            run = self.store.get("runs", ident)
            model = self.store.get("models", run["model_id"])
            workflow = Workflow.model_validate(model["ir"])
            config = Scenario.model_validate(run["config"])
            if not self.stage(ident, "verification"):
                return
            verification = verify(workflow)
            if verification["status"] == "counterexample":
                raise DomainError(
                    "Verification found a counterexample; correct the gateway model before simulation."
                )
            if not self.stage(ident, "baseline simulation"):
                return
            baseline = simulate(workflow, config)
            optimization = None
            if run["mode"] == "optimize":
                if not self.stage(ident, "fixed-resource optimization"):
                    return
                optimization = optimize(workflow, config, baseline)
            result = {
                "run_id": ident,
                "project_id": run["project_id"],
                "model_id": run["model_id"],
                "created": run["created"],
                "model_name": workflow.name,
                "config": config.model_dump(),
                "verification": verification,
                "baseline": baseline,
                "optimization": optimization,
                "bpmn_changed": False,
                "diagnostics": model["diagnostics"],
                "assumptions": workflow.assumptions,
                "recommendations": self.recommend(baseline),
            }
            if not self.stage(ident, "writing run artifacts"):
                return
            from .reporting import export_run

            export_run(self.store, run, model, result)
            if self.store.get("runs", ident)["state"] != "canceled":
                self.store.update_run(ident, state="succeeded", stage="complete", result=result)
        except DomainError as exc:
            if self.store.get("runs", ident)["state"] != "canceled":
                self.store.update_run(ident, state="failed", stage="failed", error=str(exc))
        except Exception as exc:
            # Do not log prompts, provider responses, configuration, labels, or secrets.
            log.error("Run %s failed (%s)", ident, type(exc).__name__)
            if self.store.get("runs", ident)["state"] != "canceled":
                self.store.update_run(
                    ident,
                    state="failed",
                    stage="failed",
                    error="The local run failed. Check dependencies and the model; no result was accepted.",
                )
        finally:
            self.capacity.release()

    @staticmethod
    def recommend(baseline):
        rows = sorted(baseline["schedule"], key=lambda r: (-r["wait"], r["id"]))
        if rows and rows[0]["wait"] > 0:
            row = rows[0]
            return [
                {
                    "node_id": row["id"],
                    "message": f"{row['name']} waited {row['wait']:g} {baseline['metrics']['unit']} for role {row['role']}. Compare scheduling before considering a separate capacity scenario.",
                }
            ]
        return [
            {
                "node_id": None,
                "message": "No task queued for a resource in this baseline. Added capacity may not reduce completion time.",
            }
        ]

    def shutdown(self):
        self.executor.shutdown(wait=True, cancel_futures=False)
