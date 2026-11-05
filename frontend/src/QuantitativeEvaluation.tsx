import { useEffect, useState } from "react";
import { api } from "./api";
import { num } from "./format";
import type { PerformanceEvaluation, Run } from "./types";

export function QuantitativeEvaluation({
  modelId,
  run,
  initialOnly = false,
}: {
  modelId: string;
  run: Run | null;
  initialOnly?: boolean;
}) {
  const matchingRun = run?.model_id === modelId ? run : null;
  const recorded = matchingRun?.result?.performance_evaluation;
  const config = matchingRun?.config;
  const [preview, setPreview] = useState<{
    modelId: string;
    value: PerformanceEvaluation;
  } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (recorded) return;
    let active = true;
    setPreview(null);
    setError("");
    void api<PerformanceEvaluation>(
      `/models/${modelId}/evaluate`,
      config ? { config } : {},
    )
      .then((value) => {
        if (active) setPreview({ modelId, value });
      })
      .catch((reason) => {
        if (active)
          setError(
            reason instanceof Error
              ? reason.message
              : "Evaluation unavailable.",
          );
      });
    return () => {
      active = false;
    };
  }, [modelId, recorded, config]);
  const data =
    recorded || (preview?.modelId === modelId ? preview.value : null);
  const compare = !initialOnly && !!data?.final;
  const stages = data
    ? [
        { label: "Initial BPMN", value: data.initial },
        ...(compare && data.repaired_baseline
          ? [{ label: "Repaired baseline", value: data.repaired_baseline }]
          : []),
        ...(compare && data.final
          ? [{ label: "Final BPMN", value: data.final }]
          : []),
      ]
    : [];
  const roles = [
    ...new Set(
      stages.flatMap((stage) =>
        stage.value.resources.map((resource) => resource.role),
      ),
    ),
  ];
  return (
    <section
      className="panel quantitative-evaluation"
      aria-label="Quantitative performance evaluation"
    >
      <div className="section-heading">
        <h2>
          {compare
            ? "Initial and final performance"
            : "Initial BPMN performance"}
        </h2>
        <span className="tag">QUANTITATIVE EVALUATION</span>
      </div>
      {!data ? (
        <p role="status">
          {error || "Evaluating source reachability and simulated performance…"}
        </p>
      ) : (
        <>
          <p className="muted">
            {recorded ? "Recorded run assumptions" : data.scenario_source}.{" "}
            {matchingRun?.config.execution_mode === "automatic_demo" ||
            data.scenario_mode === "automatic_demo"
              ? "Automatic demo values are illustrative, not measured business performance."
              : "Single-case deterministic simulation."}
          </p>
          {stages
            .filter((stage) => !stage.value.available)
            .map((stage) => (
              <p key={stage.label}>
                <strong>{stage.label}:</strong> {stage.value.unavailable_reason}
              </p>
            ))}
          <div className="table-scroll">
            <table className="quantitative-table">
              <caption className="sr-only">
                {compare
                  ? "Initial versus final quantitative performance"
                  : "Initial BPMN quantitative metrics"}
              </caption>
              <thead>
                <tr>
                  <th scope="col">Measure</th>
                  <th scope="col">Unit</th>
                  <th scope="col">Initial BPMN</th>
                  {compare && data.repaired_baseline && (
                    <th scope="col">Repaired baseline</th>
                  )}
                  {compare && (
                    <>
                      <th scope="col">Final BPMN</th>
                      <th scope="col">Change</th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.key} data-metric={row.key}>
                    <th scope="row">{row.label}</th>
                    <td>{row.unit}</td>
                    <td>{row.initial}</td>
                    {compare && data.repaired_baseline && (
                      <td>{row.repaired_baseline}</td>
                    )}
                    {compare && (
                      <>
                        <td>{row.final}</td>
                        <td>{row.change}</td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {compare && (
            <p className="muted">
              Change reference: {data.change_reference}. The PDF report includes
              this comparison.
            </p>
          )}
          {!!roles.length && (
            <>
              <h3>Resource utilization by role</h3>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Role</th>
                      {stages.map((stage) => (
                        <th key={stage.label} scope="col">
                          {stage.label} (%)
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {roles.map((role) => (
                      <tr key={role}>
                        <th scope="row">{role}</th>
                        {stages.map((stage) => (
                          <td key={stage.label}>
                            {num(
                              stage.value.resources.find(
                                (resource) => resource.role === role,
                              )?.utilization_pct,
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          <details>
            <summary>Bottlenecks and measurement definitions</summary>
            {stages.map((stage) => (
              <div key={stage.label}>
                <h3>{stage.label}</h3>
                <p>
                  Reachability:{" "}
                  {stage.value.reachable_states.status.replaceAll("_", " ")} (
                  {stage.value.reachable_states.method.replaceAll("_", " ")}).
                  Deadlocks: {stage.value.deadlocks.status.replaceAll("_", " ")}
                  .
                </p>
                {stage.value.available ? (
                  <>
                    <p>
                      {stage.value.bottleneck_activities.length} queued
                      activities; {stage.value.bottleneck_roles.length} affected
                      resource pools.
                    </p>
                    {stage.value.bottleneck_activities.length > 0 && (
                      <ul>
                        {stage.value.bottleneck_activities.map((task) => (
                          <li key={task.id}>
                            {task.name || task.id} ({task.id}): {num(task.wait)}{" "}
                            {data.unit}, role {task.role}
                          </li>
                        ))}
                      </ul>
                    )}
                  </>
                ) : (
                  <p>{stage.value.unavailable_reason}</p>
                )}
              </div>
            ))}
            {data.notes.map((note) => (
              <p key={note}>{note}</p>
            ))}
            <ol>
              {data.definitions.map((definition) => (
                <li key={definition}>{definition}</li>
              ))}
            </ol>
            {!recorded && !!data.assumptions?.length && (
              <>
                <h3>Preview assumptions</h3>
                <ul>
                  {data.assumptions.map((note) => (
                    <li key={note}>{note}</li>
                  ))}
                </ul>
              </>
            )}
          </details>
        </>
      )}
    </section>
  );
}
