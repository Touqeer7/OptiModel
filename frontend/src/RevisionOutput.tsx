import { useEffect, useState } from "react";
import { Download, LoaderCircle } from "lucide-react";
import { download } from "./api";
import { Diagram } from "./Diagram";
import { num } from "./format";
import type { Run } from "./types";

export function RevisionOutput({ run }: { run: Run }) {
  const revision = run.result?.revision;
  const ready = !!revision?.available_artifacts.includes("optimized.bpmn");
  const [xml, setXml] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    setXml("");
    setError("");
    if (!ready) return;
    const controller = new AbortController();
    void fetch(download(run.id, "optimized.bpmn"), {
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok)
          throw new Error(
            "The revised diagram could not be loaded. Use the download link to retry.",
          );
        return response.text();
      })
      .then((value) => {
        if (!controller.signal.aborted) setXml(value);
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted)
          setError(
            failure instanceof Error
              ? failure.message
              : "Diagram loading failed.",
          );
      });
    return () => controller.abort();
  }, [run.id, ready]);
  if (!revision) return null;
  const rewritten = revision.method === "resource_ordered_execution_plan";
  return (
    <section className="panel" aria-label="Final BPMN output">
      <div className="section-heading">
        <h2>
          {rewritten && ready
            ? "Final optimized BPMN"
            : "Final BPMN assessment"}
        </h2>
        <span className="tag">{revision.status.replaceAll("_", " ")}</span>
      </div>
      <p>
        <strong>
          {revision.optimality_proven
            ? "Optimal schedule proved for this selected route and fixed resource assumptions."
            : "Best verified feasible schedule within the search limit; global optimality was not proved."}
        </strong>
      </p>
      <p className="muted">{revision.scope}</p>
      {rewritten && (
        <p>
          The diagram is a selected-route execution plan. All other business
          branches remain in the full-process BPMN download.
        </p>
      )}
      {revision.repaired_deadlock && (
        <div className="alert" role="status">
          <div>
            <strong>Gateway deadlock repaired and re-verified.</strong>
            <p>{revision.baseline_scope}</p>
          </div>
        </div>
      )}
      <p>
        Completion: {num(revision.baseline_makespan)} →{" "}
        {num(revision.selected_makespan)} {run.config.unit}. Resource queue
        wait: {num(revision.resource_wait_before)} →{" "}
        {num(revision.resource_wait_after)} {run.config.unit}.
      </p>
      <p className="muted">{revision.bottleneck_notice}</p>
      {!!revision.remaining_bottlenecks?.length && (
        <p>
          Remaining resource waits under current staffing:{" "}
          {revision.remaining_bottlenecks.length} task(s). The change record
          lists each wait; a minimum completion time does not imply zero
          queueing.
        </p>
      )}
      {revision.full_process_verification_status === "inconclusive" && (
        <p>
          Verification of every branch of the full process was inconclusive. The
          output execution-plan verification covers the selected route.
        </p>
      )}
      {revision.fallback_reason && (
        <p>
          {revision.fallback_reason} The full-process diagram carries schedule
          annotations; no structural optimization is claimed.
        </p>
      )}
      {!ready && (
        <p role="status">
          No revised file was published because output verification was
          incomplete.
        </p>
      )}
      {ready && !xml && !error && (
        <p role="status">
          <LoaderCircle size={16} className="spin" /> Loading final diagram…
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      {xml && (
        <Diagram
          xml={xml}
          selected={null}
          highlighted={[]}
          onSelect={() => {}}
        />
      )}
      {ready && (
        <div className="run-actions">
          <a
            className="button primary"
            href={download(run.id, "optimized.bpmn")}
          >
            <Download size={15} />
            {rewritten ? "Download optimized BPMN" : "Download annotated BPMN"}
          </a>
          <a className="button" href={download(run.id, "optimized.svg")}>
            Download diagram SVG
          </a>
          <a className="button" href={download(run.id, "corrected.bpmn")}>
            Full process BPMN
          </a>
          <a className="text-button" href={download(run.id, "changes.json")}>
            Change and verification record
          </a>
        </div>
      )}
      <details>
        <summary>Repairs, selected routing and verification</summary>
        {revision.changes.length ? (
          <ul>
            {revision.changes.map((change) => (
              <li key={change.node_id}>{change.message}</li>
            ))}
          </ul>
        ) : (
          <p>No gateway repair was necessary.</p>
        )}
        <p>
          Source verification:{" "}
          {revision.source_verification_status.replaceAll("_", " ")}. Output:{" "}
          {revision.output_verification.status.replaceAll("_", " ")}.
        </p>
        {!!revision.excluded_task_ids.length && (
          <p>
            Tasks outside the selected route are excluded from this execution
            plan, retained in the full process:{" "}
            {revision.excluded_task_ids.join(", ")}.
          </p>
        )}
      </details>
    </section>
  );
}
