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
            source_workflow = workflow
            config = Scenario.model_validate(run["config"])
            if not self.stage(ident, "verification"):
                return
            verification = verify(workflow)
            source_verification = verification
            repairs, revised_documents = [], {}
            should_revise = config.produce_revised_bpmn or run["mode"] == "optimize"
            if verification["status"] == "counterexample":
                if not should_revise:
                    raise DomainError(
                        "Verification found a counterexample; correct the gateway model before simulation."
                    )
                if not self.stage(ident, "repairing closed split/join regions"):
                    return
                from .revision import repair_deadlocks

                workflow, verification, repairs = repair_deadlocks(workflow, source_verification)
            if not self.stage(ident, "baseline simulation"):
                return
            baseline = simulate(workflow, config)
            if config.execution_mode == "automatic_demo":
                from .automatic import DEMO_NOTICE

                baseline["warnings"].insert(0, DEMO_NOTICE)
            optimization = None
            if run["mode"] == "optimize" or config.produce_revised_bpmn:
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
                "source_verification": source_verification,
                "baseline": baseline,
                "optimization": optimization,
                "bpmn_changed": False,
                "diagnostics": model["diagnostics"],
                "assumptions": [*workflow.assumptions, *config.automatic_assumptions],
                "recommendations": self.recommend(baseline),
            }
            if should_revise:
                if not self.stage(ident, "validating revised BPMN and replay"):
                    return
                from .revision import build_revision

                revision, revised_documents = build_revision(
                    workflow, config, optimization, baseline, model["xml"], repairs, source_verification
                )
                result["revision"] = revision
                result["bpmn_changed"] = bool(revised_documents)
                result["assumptions"].append(revision["scope"])
            if not self.stage(ident, "quantitative performance evaluation"):
                return
            from .bpmn import parse
            from .evaluation import comparison, phase

            final_workflow = (
                parse(revised_documents["optimized.bpmn"])[0]
                if "optimized.bpmn" in revised_documents
                else workflow
            )
            selected = optimization["selected"] if optimization else baseline
            initial = phase(
                source_workflow,
                config,
                source_verification,
                None if repairs else baseline,
                "Initial BPMN has a verification counterexample; timings begin only after repair."
                if repairs
                else None,
            )
            repaired = phase(workflow, config, verification, baseline) if repairs else None
            final = (
                None
                if should_revise and not revised_documents
                else phase(final_workflow, config, verify(final_workflow), selected)
            )
            result["performance_evaluation"] = comparison(initial, final, repaired, config.unit)
            if should_revise and not revised_documents:
                result["performance_evaluation"]["notes"].append(
                    "Final BPMN verification was incomplete; no final BPMN was accepted or exported. Final measurements are unavailable."
                )
            if not self.stage(ident, "writing run artifacts"):
                return
            from .reporting import export_run

            export_run(self.store, run, model, result, revised_documents=revised_documents)
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
