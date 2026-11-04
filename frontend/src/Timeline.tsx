import type { Simulation } from "./types";
import { num } from "./format";
export function Timeline({
  data,
  onSelect,
}: {
  data: Simulation;
  onSelect: (id: string) => void;
}) {
  const span = data.metrics.makespan || 1;
  const slots = [...new Set(data.schedule.map((r) => r.resource))].sort();
  return (
    <section className="timeline">
      <div className="section-heading">
        <h3>Execution timeline</h3>
        <span className="mono">
          0 — {num(span)} {data.metrics.unit}
        </span>
      </div>
      <p className="muted">
        Resource lanes · select a task for details. Empty space is available
        capacity.
      </p>
      <div
        className="gantt"
        role="img"
        aria-label={`Resource timeline, completion ${num(span)} ${data.metrics.unit}. Detailed start and end times follow in the schedule table.`}
      >
        {slots.map((slot) => (
          <div className="gantt-lane" key={slot}>
            <span className="lane-label mono">{slot}</span>
            <div className="lane-track">
              {data.schedule
                .filter((r) => r.resource === slot)
                .map((r) => (
                  <button
                    type="button"
                    key={r.id}
                    className="gantt-bar"
                    style={{
                      left: `${(100 * r.start) / span}%`,
                      width: `${(100 * r.duration) / span}%`,
                    }}
                    title={`${r.name}: ${r.start}–${r.finish} ${data.metrics.unit}`}
                    onClick={() => onSelect(r.id)}
                  >
                    <span>{r.name}</span>
                  </button>
                ))}
            </div>
          </div>
        ))}
      </div>
      <div className="table-scroll">
        <table>
          <caption className="sr-only">
            Task start, completion and resource waiting times in{" "}
            {data.metrics.unit}
          </caption>
          <thead>
            <tr>
              <th>Task</th>
              <th>Resource</th>
              <th>Ready</th>
              <th>Start</th>
              <th>End</th>
              <th>Queue wait</th>
            </tr>
          </thead>
          <tbody>
            {data.schedule.map((r) => (
              <tr key={r.id}>
                <td>
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => onSelect(r.id)}
                  >
                    {r.name || r.id}
                  </button>
                  <small className="mono block">{r.id}</small>
                </td>
                <td>{r.resource}</td>
                <td className="mono">{num(r.ready)}</td>
                <td className="mono">{num(r.start)}</td>
                <td className="mono">{num(r.finish)}</td>
                <td className="mono">{num(r.wait)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
