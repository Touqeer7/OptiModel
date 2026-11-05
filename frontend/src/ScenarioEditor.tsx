import { useRef } from "react";
import type { Dispatch, SetStateAction } from "react";
import {
  ArrowRight,
  FlaskConical,
  Play,
  Plus,
  Save,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { api } from "./api";
import { convertTime } from "./format";
import { isTask } from "./types";
import type { Config, Model, Resource } from "./types";

type SavedScenario = { id: string; name: string; config: Config };
interface Props {
  model: Model;
  config: Config;
  setConfig: Dispatch<SetStateAction<Config>>;
  savedScenarios: SavedScenario[];
  setSavedScenarios: Dispatch<SetStateAction<SavedScenario[]>>;
  section: "Simulate" | "Optimize";
  busy: string;
  active: boolean;
  pid: string;
  updateTask: (
    id: string,
    field: "duration" | "role",
    value: number | string,
  ) => void;
  start: (mode: "simulate" | "optimize") => Promise<void>;
  action: (label: string, fn: () => Promise<void>) => Promise<void>;
  setNotice: Dispatch<SetStateAction<string>>;
  go: (section: "Optimize") => void;
}
export function ScenarioEditor({
  model,
  config,
  setConfig,
  savedScenarios,
  setSavedScenarios,
  section,
  busy,
  active,
  pid,
  updateTask,
  start,
  action,
  setNotice,
  go,
}: Props) {
  const resourceKeys = useRef(new WeakMap<Resource, string>());
  function resourceKey(resource: Resource) {
    let id = resourceKeys.current.get(resource);
    if (!id) {
      id = crypto.randomUUID();
      resourceKeys.current.set(resource, id);
    }
    return id;
  }
  function updateResource(index: number, fields: Partial<Resource>) {
    setConfig((c) => ({
      ...c,
      resources: c.resources.map((r, i) => {
        if (i !== index) return r;
        const updated = { ...r, ...fields };
        resourceKeys.current.set(updated, resourceKey(r));
        return updated;
      }),
    }));
  }
  return (
    <section className="panel configuration">
      <div className="section-heading">
        <h2>
          <FlaskConical size={18} /> Scenario assumptions
        </h2>
        <span className="tag">SINGLE CASE / DETERMINISTIC</span>
      </div>
      <p className="muted">
        Every task needs a positive duration and an eligible resource role.
        Automatic runs fill missing inputs with labeled demo assumptions. These
        optional controls let you replace those assumptions with your own
        durations, roles, capacities and routes.
      </p>
      <div className="settings-row">
        <label>
          Time unit
          <select
            aria-label="Time unit"
            value={config.unit}
            onChange={(e) => {
              const unit = e.target.value;
              setConfig((c) => ({
                ...c,
                unit,
                tasks: Object.fromEntries(
                  Object.entries(c.tasks).map(([id, task]) => [
                    id,
                    {
                      ...task,
                      duration: convertTime(task.duration, c.unit, unit),
                    },
                  ]),
                ),
                resources: c.resources.map((r) => ({
                  ...r,
                  cost_per_unit:
                    r.cost_per_unit == null
                      ? null
                      : convertTime(r.cost_per_unit, unit, c.unit),
                })),
              }));
            }}
          >
            {["time units", "minutes", "hours", "days"].map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        </label>
        <label>
          Random seed
          <input
            aria-label="Random seed"
            type="number"
            min="0"
            max="2147483647"
            value={config.seed}
            onChange={(e) =>
              setConfig((c) => ({
                ...c,
                seed: Number(e.target.value),
              }))
            }
          />
        </label>
        <label>
          Solver limit (seconds)
          <input
            aria-label="Solver limit"
            type="number"
            min="0.01"
            max="15"
            step="0.01"
            value={config.solver_seconds}
            onChange={(e) =>
              setConfig((c) => ({
                ...c,
                solver_seconds: Number(e.target.value),
              }))
            }
          />
        </label>
        {savedScenarios.length > 0 && (
          <label>
            Saved scenario
            <select
              aria-label="Saved scenario"
              defaultValue=""
              onChange={(e) => {
                const s = savedScenarios.find((v) => v.id === e.target.value);
                if (s) setConfig(s.config);
              }}
            >
              <option value="" disabled>
                Choose assumptions
              </option>
              {savedScenarios.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <div className="sub-heading">
        <h3>Resource pools</h3>
        <button
          type="button"
          className="text-button"
          onClick={() =>
            setConfig((c) => ({
              ...c,
              resources: [
                ...c.resources,
                {
                  role: `Role ${c.resources.length + 1}`,
                  capacity: 1,
                  cost_per_unit: null,
                },
              ],
            }))
          }
        >
          <Plus size={14} /> Add role
        </button>
      </div>
      <div className="table-scroll">
        <table className="input-table">
          <thead>
            <tr>
              <th>Role / skill</th>
              <th>Available slots</th>
              <th>
                Cost per{" "}
                {config.unit === "time units"
                  ? "time unit"
                  : config.unit.replace(/s$/, "")}
              </th>
              <th>
                <span className="sr-only">Remove</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {config.resources.map((resource, i) => (
              <tr key={resourceKey(resource)}>
                <td>
                  <input
                    aria-label={`Role ${i + 1} name`}
                    value={resource.role}
                    maxLength={100}
                    onChange={(e) =>
                      updateResource(i, { role: e.target.value })
                    }
                  />
                </td>
                <td>
                  <input
                    aria-label={`${resource.role} capacity`}
                    type="number"
                    min="1"
                    max="32"
                    value={resource.capacity}
                    onChange={(e) =>
                      updateResource(i, { capacity: Number(e.target.value) })
                    }
                  />
                </td>
                <td>
                  <input
                    aria-label={`${resource.role} cost rate`}
                    placeholder="Unknown"
                    type="number"
                    min="0"
                    max="1000000"
                    value={resource.cost_per_unit ?? ""}
                    onChange={(e) =>
                      updateResource(i, {
                        cost_per_unit:
                          e.target.value === "" ? null : Number(e.target.value),
                      })
                    }
                  />
                </td>
                <td>
                  <button
                    type="button"
                    aria-label={`Remove ${resource.role}`}
                    onClick={() =>
                      setConfig((c) => ({
                        ...c,
                        resources: c.resources.filter((_, j) => j !== i),
                      }))
                    }
                  >
                    <X size={16} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3 className="sub-heading">Activity assumptions</h3>
      <div className="table-scroll">
        <table className="input-table">
          <thead>
            <tr>
              <th>Activity / BPMN ID</th>
              <th>Duration ({config.unit})</th>
              <th>Required role</th>
              <th>Provenance</th>
            </tr>
          </thead>
          <tbody>
            {model.ir.nodes.filter(isTask).map((n) => (
              <tr key={n.id}>
                <td>
                  {n.name || n.id}
                  <small className="block mono">{n.id}</small>
                </td>
                <td>
                  <input
                    aria-label={`${n.id} duration`}
                    type="number"
                    min="0.001"
                    max="1000000"
                    step="0.001"
                    placeholder="Required"
                    value={
                      config.tasks[n.id]?.duration ??
                      (n.duration == null
                        ? ""
                        : convertTime(
                            n.duration,
                            model.ir.time_unit || "time units",
                            config.unit,
                          ))
                    }
                    onChange={(e) =>
                      updateTask(n.id, "duration", Number(e.target.value))
                    }
                  />
                </td>
                <td>
                  <select
                    aria-label={`${n.id} role`}
                    value={config.tasks[n.id]?.role ?? n.role ?? ""}
                    onChange={(e) => updateTask(n.id, "role", e.target.value)}
                  >
                    <option value="">Choose a role</option>
                    {config.resources.map((r) => (
                      <option key={resourceKey(r)} value={r.role}>
                        {r.role}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <span className="tag">
                    {config.tasks[n.id]?.provenance || n.provenance}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {model.ir.nodes
        .filter(
          (n) =>
            n.kind === "exclusiveGateway" &&
            model.ir.edges.filter((e) => e.source === n.id).length > 1,
        )
        .map((n) => (
          <label className="route-select" key={n.id}>
            Explicit route: {n.name || n.id}
            <select
              aria-label={`${n.id} route`}
              value={config.routes[n.id] || ""}
              onChange={(e) =>
                setConfig((c) => ({
                  ...c,
                  routes: { ...c.routes, [n.id]: e.target.value },
                }))
              }
            >
              <option value="">Select a branch — no routing assumed</option>
              {model.ir.edges
                .filter((edge) => edge.source === n.id)
                .map((edge) => (
                  <option key={edge.id} value={edge.id}>
                    {edge.name || edge.condition || edge.id}
                    {edge.is_default ? " (default)" : ""}
                  </option>
                ))}
            </select>
          </label>
        ))}
      <p className="method-note">
        Continuous availability, one role slot per task, no preemption. Cost
        rates use a consistent currency of your choice. A changed capacity is a
        separate scenario, not a scheduling gain.
      </p>
      <div className="run-actions">
        <button
          type="button"
          className="button primary"
          disabled={!!busy || active}
          onClick={() =>
            void start(section === "Optimize" ? "optimize" : "simulate")
          }
        >
          {section === "Optimize" ? (
            <SlidersHorizontal size={16} />
          ) : (
            <Play size={16} />
          )}{" "}
          {section === "Optimize"
            ? "Run fixed-resource optimization"
            : "Run baseline simulation"}
        </button>
        <button
          type="button"
          className="button"
          disabled={!!busy}
          onClick={() =>
            void action("Saving scenario", async () => {
              await api(`/projects/${pid}/scenarios`, {
                name: `Scenario ${savedScenarios.length + 1}`,
                config,
              });
              setSavedScenarios(await api(`/projects/${pid}/scenarios`));
              setNotice("Scenario assumptions saved.");
            })
          }
        >
          <Save size={15} /> Save assumptions
        </button>
        {section === "Simulate" && (
          <button
            type="button"
            className="text-button"
            onClick={() => go("Optimize")}
          >
            Open fixed-resource optimizer <ArrowRight size={15} />
          </button>
        )}
      </div>
    </section>
  );
}
