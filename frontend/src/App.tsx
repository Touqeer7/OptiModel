import { ScenarioEditor } from "./ScenarioEditor";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  Download,
  FileCode2,
  FileText,
  FolderOpen,
  GitCompareArrows,
  History,
  Layers3,
  LoaderCircle,
  PanelLeft,
  Play,
  Plus,
  Save,
  ScanLine,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Upload,
  Workflow as WorkflowIcon,
  X,
} from "lucide-react";
import { api, ApiError, download } from "./api";
import { Diagram } from "./Diagram";
import { Timeline } from "./Timeline";
import { date, num } from "./format";
import { isTask } from "./types";
import type {
  Config,
  Diagnostic,
  Draft,
  Health,
  Model,
  Project,
  Run,
  Sample,
  Validation,
  Workflow,
} from "./types";

type Section =
  | "Workspace"
  | "Model"
  | "Validate"
  | "Simulate"
  | "Optimize"
  | "Compare"
  | "Reports";
const navigation: [Section, ReactNode][] = [
  ["Workspace", <FolderOpen key="workspace" size={18} />],
  ["Model", <WorkflowIcon key="model" size={18} />],
  ["Validate", <ShieldCheck key="validate" size={18} />],
  ["Simulate", <Play key="simulate" size={18} />],
  ["Optimize", <SlidersHorizontal key="optimize" size={18} />],
  ["Compare", <GitCompareArrows key="compare" size={18} />],
  ["Reports", <FileText key="reports" size={18} />],
];
const configFor = (model: Model): Config => ({
  unit: "time units",
  seed: 42,
  solver_seconds: 5,
  resources: [
    ...new Set(
      model.ir.nodes
        .filter(isTask)
        .map((n) => n.role)
        .filter((r): r is string => !!r),
    ),
  ].map((role) => ({ role, capacity: 1, cost_per_unit: null })),
  tasks: {},
  routes: {},
  probabilities: {},
});

function Status({ value }: { value: string }) {
  return (
    <span className={`status status-${value}`}>
      <span />
      {value.replaceAll("_", " ")}
    </span>
  );
}
function Blank({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="blank">
      <ScanLine size={28} />
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}

export default function App() {
  const [section, setSection] = useState<Section>("Workspace");
  const [projects, setProjects] = useState<Project[]>([]);
  const [pid, setPid] = useState(localStorage.getItem("studio.project") || "");
  const [models, setModels] = useState<Model[]>([]);
  const [model, setModel] = useState<Model | null>(null);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [config, setConfig] = useState<Config>({
    unit: "time units",
    seed: 42,
    solver_seconds: 5,
    resources: [],
    tasks: {},
    routes: {},
    probabilities: {},
  });
  const [savedScenarios, setSavedScenarios] = useState<
    { id: string; name: string; config: Config }[]
  >([]);
  const [validation, setValidation] = useState<Validation | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<{
    message: string;
    diagnostics: Diagnostic[];
  } | null>(null);
  const [notice, setNotice] = useState("");
  const [projectName, setProjectName] = useState("");
  const [xml, setXml] = useState("");
  const [prompt, setPrompt] = useState("");
  const [generationError, setGenerationError] = useState("");
  const [draft, setDraft] = useState("");
  const [approved, setApproved] = useState(false);
  const [compareIds, setCompareIds] = useState(["", ""]);
  const [comparison, setComparison] = useState<{
    left: Run;
    right: Run;
    comparison_scope: string;
    warning: string | null;
  } | null>(null);
  const [mobileNav, setMobileNav] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const activeProject = projects.find((p) => p.id === pid);
  const active = run?.state === "queued" || run?.state === "running";
  const result = run?.result;
  const selectedSimulation = result?.optimization?.selected || result?.baseline;
  const selectedNode = model?.ir.nodes.find((n) => n.id === selected);

  async function action(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setError(null);
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError({
        message: e instanceof Error ? e.message : "Local operation failed.",
        diagnostics: e instanceof ApiError ? e.diagnostics : [],
      });
    } finally {
      setBusy("");
    }
  }
  useEffect(() => {
    let live = true;
    setBusy("Opening local workspace");
    void Promise.all([
      api<Project[]>("/projects"),
      api<Sample[]>("/samples"),
      api<Health>("/health"),
    ])
      .then(([p, s, h]) => {
        if (!live) return;
        setProjects(p);
        setSamples(s);
        setHealth(h);
        setPid((previous) =>
          p.some((project) => project.id === previous)
            ? previous
            : p[0]?.id || "",
        );
      })
      .catch((e) => {
        if (live) setError({ message: e.message, diagnostics: [] });
      })
      .finally(() => {
        if (live) setBusy("");
      });
    return () => {
      live = false;
    };
  }, []);
  useEffect(() => {
    setModel(null);
    setModels([]);
    setRuns([]);
    setRun(null);
    setValidation(null);
    setComparison(null);
    setSelected(null);
    setSavedScenarios([]);
    if (!pid) return;
    localStorage.setItem("studio.project", pid);
    let live = true;
    void Promise.all([
      api<Model[]>(`/projects/${pid}/models`),
      api<Run[]>(`/projects/${pid}/runs`),
      api<{ id: string; name: string; config: Config }[]>(
        `/projects/${pid}/scenarios`,
      ),
    ])
      .then(([m, r, s]) => {
        if (!live) return;
        setModels(m);
        setRuns(r);
        setSavedScenarios(s);
        if (m[0]) {
          setModel(m[0]);
          setConfig(configFor(m[0]));
          setXml(m[0].xml);
        }
        if (r[0]) setRun(r[0]);
      })
      .catch((e) => {
        if (live) setError({ message: e.message, diagnostics: [] });
      });
    return () => {
      live = false;
    };
  }, [pid]);
  const pollId = run?.id;
  const pollState = run?.state;
  useEffect(() => {
    if (!pollId || !pollState || !["queued", "running"].includes(pollState))
      return;
    let live = true;
    const timer = window.setInterval(() => {
      void api<Run>(`/runs/${pollId}`)
        .then((updated) => {
          if (!live) return;
          setRun(updated);
          setRuns((prev) => [
            updated,
            ...prev.filter((r) => r.id !== updated.id),
          ]);
          if (updated.state === "failed")
            setError({
              message: updated.error || "Run failed.",
              diagnostics: [],
            });
        })
        .catch((e) => {
          if (live) setError({ message: e.message, diagnostics: [] });
        });
    }, 700);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [pollId, pollState]);

  function selectModel(value: Model, supplied?: Config) {
    setModel(value);
    setConfig(supplied || configFor(value));
    setXml(value.xml);
    setValidation(null);
    setSelected(null);
  }
  async function ensureProject(name: string): Promise<string> {
    if (pid) return pid;
    const p = await api<Project>("/projects", { name });
    setProjects((prev) => [p, ...prev]);
    setPid(p.id);
    return p.id;
  }
  async function addModel(
    projectId: string,
    source: string,
    name: string,
    supplied?: Config,
  ) {
    const m = await api<Model>(`/projects/${projectId}/models`, {
      name,
      xml: source,
    });
    // The project effect may still be loading an empty collection for a just-created project.
    const all = await api<Model[]>(`/projects/${projectId}/models`);
    setModels(all);
    selectModel(m, supplied);
    setSection("Model");
    setNotice("Model saved as a new version. Source XML preserved.");
  }
  async function loadSample(s: Sample) {
    await action("Preparing sample", async () => {
      const projectId = await ensureProject(s.name);
      await addModel(projectId, s.xml, s.name, s.config);
    });
  }
  async function validateModel() {
    if (!model) return;
    await action("Checking model", async () => {
      setValidation(await api<Validation>(`/models/${model.id}/validate`, {}));
      setSection("Validate");
    });
  }
  async function start(mode: "simulate" | "optimize") {
    if (!model) return;
    await action("Queueing experiment", async () => {
      const newRun = await api<Run>(`/projects/${pid}/runs`, {
        model_id: model.id,
        config,
        mode,
      });
      setRun(newRun);
      setRuns((prev) => [newRun, ...prev]);
      setSection(mode === "optimize" ? "Optimize" : "Simulate");
    });
  }
  function updateTask(
    id: string,
    field: "duration" | "role",
    value: number | string,
  ) {
    if (!model) return;
    const source = model.ir.nodes.find((n) => n.id === id)!;
    setConfig((c) => {
      const previous = c.tasks[id] || {
        duration: source.duration ?? 0,
        role: source.role ?? "",
      };
      return {
        ...c,
        tasks: {
          ...c.tasks,
          [id]: { ...previous, [field]: value, provenance: "user" },
        },
      };
    });
  }
  function go(value: Section) {
    setSection(value);
    setMobileNav(false);
    setNotice("");
  }
  async function selectHistory(value: Run) {
    setRun(value);
    const matching = models.find((m) => m.id === value.model_id);
    if (matching) selectModel(matching, value.config);
    setSection(value.mode === "optimize" ? "Optimize" : "Simulate");
  }
  const diagnosticList = (items: Diagnostic[]) => (
    <ul className="diagnostics">
      {items.map((d) => (
        <li
          key={`${d.code}_${d.element_id}_${d.message}`}
          className={d.severity === "error" ? "danger" : ""}
        >
          {d.element_id && (
            <button
              type="button"
              className="element-id mono"
              onClick={() => {
                setSelected(d.element_id!);
                setSection("Model");
              }}
            >
              {d.element_id}
            </button>
          )}
          <span>{d.message}</span>
        </li>
      ))}
    </ul>
  );

  return (
    <div className="studio">
      <a className="skip-link" href="#main">
        Skip to workspace
      </a>
      <aside className={`rail ${mobileNav ? "open" : ""}`}>
        <button
          type="button"
          className="brand"
          onClick={() => {
            go("Workspace");
          }}
        >
          <span className="brand-mark">
            <WorkflowIcon size={23} />
          </span>
          <span>
            OptiModel<small>STUDIO</small>
          </span>
        </button>
        <div className="project-select">
          <label className="eyebrow" htmlFor="project-select">
            LOCAL WORKSPACE
          </label>
          <div className="select-wrap">
            <select
              id="project-select"
              value={pid}
              onChange={(e) => setPid(e.target.value)}
            >
              <option value="">Select a project</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <ChevronDown size={14} />
          </div>
        </div>
        <nav aria-label="Workspace sections">
          {navigation.map(([label, icon], i) => (
            <button
              type="button"
              key={label}
              className={section === label ? "nav-item current" : "nav-item"}
              onClick={() => go(label)}
              aria-current={section === label ? "page" : undefined}
            >
              {icon}
              <span>{label}</span>
              <small className="mono" aria-hidden="true">
                0{i + 1}
              </small>
            </button>
          ))}
        </nav>
        <div className="rail-bottom">
          <div className="local-dot">
            <span /> Stored on this computer
          </div>
          <p>
            No account required.
            <br />
            AI generation is optional.
          </p>
          <a href="/docs" target="_blank" rel="noreferrer">
            <CircleHelp size={15} /> API & local diagnostics{" "}
            <ArrowUpRight size={12} />
          </a>
          <div className="version mono">STUDIO / 3.0</div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="command-bar">
          <div className="breadcrumb">
            <button
              type="button"
              className="mobile-toggle"
              aria-label="Toggle navigation"
              onClick={() => setMobileNav(!mobileNav)}
            >
              <PanelLeft size={18} />
            </button>
            <span>Workspace</span>
            <span className="slash">/</span>
            <strong>{activeProject?.name || "Getting started"}</strong>
          </div>
          <div className="bar-right">
            <span className="desktop-note">
              <span className="live-dot" /> LOCAL SESSION
            </span>
            <button
              type="button"
              className="button small"
              onClick={() => file.current?.click()}
            >
              <Upload size={15} /> Import BPMN
            </button>
          </div>
        </header>
        <input
          className="sr-only"
          type="file"
          accept=".bpmn,.xml"
          ref={file}
          aria-label="Import BPMN file"
          onChange={(e) => {
            const picked = e.target.files?.[0];
            if (!picked) return;
            void action("Importing source model", async () => {
              if (picked.size > 1_000_000)
                throw new Error("BPMN exceeds 1 MB.");
              const projectId = await ensureProject("Imported processes");
              await addModel(projectId, await picked.text(), picked.name);
            });
            e.target.value = "";
          }}
        />
        <main id="main" tabIndex={-1}>
          <div className="page-heading">
            <div>
              <p className="eyebrow">
                PROCESS ENGINEERING / {section.toUpperCase()}
              </p>
              <h1>
                {section === "Workspace"
                  ? "Understand the process. Improve the work."
                  : section === "Model"
                    ? model?.ir.name || "Process model"
                    : section === "Validate"
                      ? "Check the process logic."
                      : section === "Simulate"
                        ? "Measure a stated scenario."
                        : section === "Optimize"
                          ? "Better scheduling. Same resources."
                          : section === "Compare"
                            ? "Make the differences explicit."
                            : "Evidence you can take with you."}
              </h1>
              <p className="lede">
                {section === "Workspace"
                  ? "A local place to model, test, and compare how your process could work."
                  : section === "Model"
                    ? "Review the original diagram and the facts attached to each activity."
                    : section === "Validate"
                      ? "Structural checks and bounded token-flow exploration, with a clear statement of scope."
                      : section === "Simulate"
                        ? "Define timing, roles, and capacity before running a reproducible single-case experiment."
                        : section === "Optimize"
                          ? "A constrained solver searches for a shorter schedule under identical task and resource assumptions."
                          : section === "Compare"
                            ? "Compare historical experiments and distinguish scheduling changes from capacity scenarios."
                            : "Every export belongs to a specific, saved experiment."}
              </p>
            </div>
            <span className="chapter mono">
              {String(
                navigation.findIndex(([s]) => s === section) + 1,
              ).padStart(2, "0")}{" "}
              / 07
            </span>
          </div>
          {busy && (
            <div className="operation" role="status">
              <LoaderCircle size={16} className="spin" />
              {busy}…
            </div>
          )}
          {error && (
            <div className="alert error" role="alert">
              <div>
                <strong>{error.message}</strong>
                {diagnosticList(error.diagnostics)}
              </div>
              <button
                type="button"
                aria-label="Dismiss error"
                onClick={() => setError(null)}
              >
                <X size={17} />
              </button>
            </div>
          )}
          {notice && (
            <div className="alert success" role="status">
              <CheckCircle2 size={17} />
              <span>{notice}</span>
            </div>
          )}

          {section === "Workspace" && (
            <>
              <section className="workspace-intro">
                <div>
                  <span className="eyebrow">START WITH A QUESTION</span>
                  <h2>
                    What happens when
                    <br />
                    the work meets a constraint?
                  </h2>
                  <p>
                    Explore a real process structure with transparent example
                    assumptions. Then bring your own model.
                  </p>
                  <div className="intro-actions">
                    <button
                      type="button"
                      className="button primary"
                      disabled={!!busy}
                      onClick={() => samples[0] && void loadSample(samples[0])}
                    >
                      Explore order fulfillment <ArrowRight size={16} />
                    </button>
                    <button
                      type="button"
                      className="text-button"
                      onClick={() => file.current?.click()}
                    >
                      Import your model <Upload size={15} />
                    </button>
                  </div>
                </div>
                <div className="intro-drawing" aria-hidden="true">
                  <span className="draft-label mono">
                    PROCESS / RESOURCE / TIME
                  </span>
                  <div className="draft-flow">
                    <i />
                    <b />
                    <div>
                      <span>Review</span>
                      <span>Prepare</span>
                    </div>
                    <b />
                    <i />
                  </div>
                  <div className="draft-times">
                    <span />
                    <span />
                    <span />
                  </div>
                  <span className="draft-caption mono">
                    A model is a hypothesis. Test the assumptions.
                  </span>
                </div>
              </section>
              <section className="panel">
                <div className="section-heading">
                  <h2>Three ways into the studio</h2>
                  <span className="eyebrow">
                    EXAMPLE DATA / EDITABLE ASSUMPTIONS
                  </span>
                </div>
                <div className="samples">
                  {samples.map((s, i) => (
                    <button
                      type="button"
                      key={s.key}
                      className="sample"
                      disabled={!!busy}
                      onClick={() => void loadSample(s)}
                    >
                      <span className="mono sample-index">0{i + 1}</span>
                      <div>
                        <strong>{s.name}</strong>
                        <p>{s.description}</p>
                        <span className="sample-type">
                          {i === 0
                            ? "PARALLEL / AND"
                            : i === 1
                              ? "CONDITIONAL / XOR"
                              : "SHARED RESOURCES"}
                        </span>
                      </div>
                      <ArrowUpRight size={19} />
                    </button>
                  ))}
                </div>
              </section>
              <div className="two-column">
                <section className="panel">
                  <div className="section-heading">
                    <h2>Projects on this computer</h2>
                    <Layers3 size={17} />
                  </div>
                  <form
                    className="inline-form"
                    onSubmit={(e) => {
                      e.preventDefault();
                      void action("Creating project", async () => {
                        const p = await api<Project>("/projects", {
                          name: projectName,
                        });
                        setProjects((prev) => [p, ...prev]);
                        setPid(p.id);
                        setProjectName("");
                      });
                    }}
                  >
                    <label className="sr-only" htmlFor="project-name">
                      New project name
                    </label>
                    <input
                      id="project-name"
                      required
                      maxLength={120}
                      value={projectName}
                      onChange={(e) => setProjectName(e.target.value)}
                      placeholder="New project name"
                    />
                    <button type="submit" className="button" disabled={!!busy}>
                      <Plus size={16} /> Create
                    </button>
                  </form>
                  <div className="project-list">
                    {projects.map((p) => (
                      <button
                        type="button"
                        key={p.id}
                        onClick={() => setPid(p.id)}
                        className={
                          pid === p.id ? "project active-project" : "project"
                        }
                      >
                        <FolderOpen size={17} />
                        <span>
                          {p.name}
                          <small>{date(p.created)}</small>
                        </span>
                        {pid === p.id && <Check size={16} />}
                      </button>
                    ))}
                  </div>
                  {activeProject && (
                    <details>
                      <summary>Project settings</summary>
                      <form
                        className="inline-form"
                        onSubmit={(e) => {
                          e.preventDefault();
                          const name = new FormData(e.currentTarget).get(
                            "name",
                          );
                          void action("Renaming project", async () => {
                            const p = await api<Project>(
                              `/projects/${pid}`,
                              { name },
                              "PATCH",
                            );
                            setProjects((prev) =>
                              prev.map((v) => (v.id === pid ? p : v)),
                            );
                          });
                        }}
                      >
                        <input
                          key={pid}
                          name="name"
                          defaultValue={activeProject.name}
                          aria-label="Project name"
                          required
                          maxLength={120}
                        />
                        <button type="submit" className="button small">
                          Rename
                        </button>
                      </form>
                      <button
                        type="button"
                        className="text-button danger"
                        onClick={() => {
                          if (
                            window.confirm(
                              "Hide this project and its downloads? Data is retained on local disk.",
                            )
                          )
                            void action("Removing project", async () => {
                              await api(
                                `/projects/${pid}`,
                                undefined,
                                "DELETE",
                              );
                              setProjects((prev) =>
                                prev.filter((p) => p.id !== pid),
                              );
                              setPid("");
                            });
                        }}
                      >
                        Remove project from workspace
                      </button>
                    </details>
                  )}
                </section>
                <section className="panel">
                  <div className="section-heading">
                    <h2>Recent experiments</h2>
                    <History size={17} />
                  </div>
                  {!runs.length ? (
                    <Blank title="A clean experiment log">
                      Run a simulation to start a history you can reopen later.
                    </Blank>
                  ) : (
                    <div className="history-list">
                      {runs.slice(0, 5).map((r) => (
                        <button
                          type="button"
                          key={r.id}
                          onClick={() => void selectHistory(r)}
                        >
                          <span className="mono">{r.id.slice(0, 8)}</span>
                          <div>
                            {r.mode === "optimize"
                              ? "Fixed-resource experiment"
                              : "Baseline simulation"}
                            <small>{date(r.created)}</small>
                          </div>
                          <Status value={r.state} />
                        </button>
                      ))}
                    </div>
                  )}
                </section>
              </div>
              <section className="panel generation">
                <div className="section-heading">
                  <h2>
                    <Sparkles size={18} /> Start from a description
                  </h2>
                  <span className="tag">OPTIONAL AI</span>
                </div>
                <p className="muted">
                  {health?.provider.notice}{" "}
                  {health?.provider.destination && (
                    <span>
                      Destination:{" "}
                      <strong>{health.provider.destination}</strong>.
                    </span>
                  )}
                </p>
                <label htmlFor="description">Process description</label>
                <textarea
                  id="description"
                  rows={4}
                  maxLength={12000}
                  value={prompt}
                  onChange={(e) => {
                    setPrompt(e.target.value);
                    setGenerationError("");
                  }}
                  placeholder="Describe tasks, decisions, parallel steps, and any timing or role facts you know."
                />
                <div className="generation-actions">
                  <button
                    type="button"
                    className="button"
                    disabled={
                      !!busy || !prompt.trim() || !health?.provider.configured
                    }
                    onClick={() =>
                      void action("Extracting a review draft", async () => {
                        setGenerationError("");
                        setDraft("");
                        setApproved(false);
                        const d = await api<Draft>("/generation/extract", {
                          prompt,
                        }).catch((e: unknown) => {
                          setGenerationError(
                            e instanceof Error
                              ? e.message
                              : "Draft extraction failed. Please retry.",
                          );
                          throw e;
                        });
                        setDraft(JSON.stringify(d.ir, null, 2));
                        setApproved(false);
                        if (d.diagnostics.length)
                          setNotice(
                            "Review the draft and resolve its structural or ambiguity diagnostics before acceptance.",
                          );
                      })
                    }
                  >
                    {busy === "Extracting a review draft" ? (
                      <>
                        <LoaderCircle size={16} className="spin" /> Extracting
                        draft…
                      </>
                    ) : (
                      <>
                        <Sparkles size={16} /> Extract review draft
                      </>
                    )}
                  </button>
                  {!health?.provider.configured && (
                    <p className="muted">
                      No AI provider configured. Set the optional backend
                      environment settings; samples and file import are ready
                      now.
                    </p>
                  )}
                </div>
                {busy === "Extracting a review draft" && (
                  <p role="status">
                    Waiting for the AI provider to return a draft…
                  </p>
                )}
                {generationError && (
                  <div className="alert error" role="alert">
                    {generationError}
                  </div>
                )}
                {draft && (
                  <div className="draft-editor">
                    <label htmlFor="draft-json">
                      Structured draft · review every task, branch, assumption,
                      and unresolved ambiguity
                    </label>
                    <textarea
                      id="draft-json"
                      className="code"
                      rows={18}
                      value={draft}
                      onChange={(e) => {
                        setDraft(e.target.value);
                        setApproved(false);
                      }}
                    />
                    <p className="muted">
                      Edit unknowns and clear ambiguities only after resolving
                      them. Unstated durations and roles can stay null until
                      scenario configuration.
                    </p>
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={approved}
                        onChange={(e) => setApproved(e.target.checked)}
                      />{" "}
                      I reviewed this model against my description and resolved
                      material ambiguity.
                    </label>
                    <button
                      type="button"
                      className="button primary"
                      disabled={!approved || !!busy}
                      onClick={() =>
                        void action("Saving reviewed model", async () => {
                          const ir = JSON.parse(draft) as Workflow;
                          const projectId = await ensureProject(ir.name);
                          const m = await api<Model>(
                            `/projects/${projectId}/generation/accept`,
                            { ir, review_confirmed: true },
                          );
                          setModels(
                            await api<Model[]>(`/projects/${projectId}/models`),
                          );
                          selectModel(m);
                          setSection("Model");
                        })
                      }
                    >
                      <Check size={16} /> Accept reviewed model
                    </button>
                  </div>
                )}
              </section>
            </>
          )}

          {section !== "Workspace" && !model && (
            <Blank title="Start with a process model">
              Choose an example in Workspace or import a BPMN file to continue.{" "}
              <button
                type="button"
                className="text-button"
                onClick={() => go("Workspace")}
              >
                Open workspace <ArrowRight size={15} />
              </button>
            </Blank>
          )}

          {section !== "Workspace" && model && (
            <>
              <div className="model-toolbar">
                <label>
                  MODEL VERSION{" "}
                  <select
                    aria-label="Model version"
                    value={model.id}
                    onChange={(e) => {
                      const next = models.find((m) => m.id === e.target.value);
                      if (next) {
                        selectModel(next);
                        setRun(null);
                      }
                    }}
                  >
                    {models.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name} · {date(m.created)} · {m.id.slice(0, 6)}
                      </option>
                    ))}
                  </select>
                </label>
                <span className="tag">
                  <FileCode2 size={13} /> SOURCE PRESERVED
                </span>
              </div>
              {section === "Model" && (
                <>
                  <div className="model-layout">
                    <Diagram
                      xml={
                        validation?.display_xml ||
                        model.display_xml ||
                        model.xml
                      }
                      selected={selected}
                      highlighted={
                        validation?.verification.counterexample_trace || []
                      }
                      onSelect={setSelected}
                    />
                    <aside className="inspector">
                      <div className="section-heading">
                        <h3>Element inspector</h3>
                        <Settings2 size={16} />
                      </div>
                      {selectedNode ? (
                        <>
                          <span className="eyebrow">
                            {selectedNode.kind.replace(/([A-Z])/g, " $1")}
                          </span>
                          <h3>{selectedNode.name || selectedNode.id}</h3>
                          <code>{selectedNode.id}</code>
                          <dl>
                            <dt>Source duration</dt>
                            <dd>
                              {num(selectedNode.duration)}{" "}
                              <small>scenario unit</small>
                            </dd>
                            <dt>Resource role</dt>
                            <dd>{selectedNode.role || "Unknown"}</dd>
                            <dt>Provenance</dt>
                            <dd>{selectedNode.provenance}</dd>
                            <dt>Incoming / outgoing</dt>
                            <dd>
                              {
                                model.ir.edges.filter(
                                  (e) => e.target === selectedNode.id,
                                ).length
                              }{" "}
                              /{" "}
                              {
                                model.ir.edges.filter(
                                  (e) => e.source === selectedNode.id,
                                ).length
                              }
                            </dd>
                          </dl>
                          <p className="muted">
                            Set scenario timing and staffing in Simulate. Source
                            values are preserved.
                          </p>
                        </>
                      ) : (
                        <>
                          <ScanLine size={27} className="inspector-icon" />
                          <p className="muted">
                            Select an element on the canvas or in the list to
                            inspect its source facts.
                          </p>
                          <dl>
                            <dt>Activities</dt>
                            <dd>{model.ir.nodes.filter(isTask).length}</dd>
                            <dt>Sequence flows</dt>
                            <dd>{model.ir.edges.length}</dd>
                          </dl>
                        </>
                      )}
                    </aside>
                  </div>
                  <div className="panel actions-strip">
                    <div>
                      <strong>Ready for a logic check?</strong>
                      <p className="muted">
                        Check structure, supported semantics, and token flow
                        before experimenting.
                      </p>
                    </div>
                    <button
                      type="button"
                      className="button primary"
                      disabled={!!busy}
                      onClick={() => void validateModel()}
                    >
                      <ShieldCheck size={16} /> Validate model
                    </button>
                  </div>
                  <section className="panel">
                    <div className="section-heading">
                      <h2>Process elements</h2>
                      <span className="mono">
                        {model.ir.nodes.length} ELEMENTS
                      </span>
                    </div>
                    <div className="element-list">
                      {model.ir.nodes.map((n) => (
                        <button
                          type="button"
                          className={selected === n.id ? "selected" : ""}
                          key={n.id}
                          onClick={() => setSelected(n.id)}
                        >
                          <span>{n.name || n.id}</span>
                          <small className="mono">{n.id}</small>
                          <span className="muted">{n.kind}</span>
                        </button>
                      ))}
                    </div>
                    <details className="xml-editor">
                      <summary>
                        Review / edit source XML as a new version
                      </summary>
                      <p className="muted">
                        Saving creates an immutable version and revalidates
                        supported semantics. Historical runs keep their source.
                      </p>
                      <label className="sr-only" htmlFor="xml-editor">
                        BPMN XML source
                      </label>
                      <textarea
                        id="xml-editor"
                        className="code"
                        rows={15}
                        value={xml}
                        onChange={(e) => setXml(e.target.value)}
                      />
                      <button
                        type="button"
                        className="button"
                        disabled={!!busy || xml === model.xml}
                        onClick={() =>
                          void action("Saving new model version", async () => {
                            await addModel(pid, xml, model.name);
                            setRun(null);
                          })
                        }
                      >
                        <Save size={16} /> Validate & save new version
                      </button>
                    </details>
                  </section>
                </>
              )}
              {section === "Validate" && (
                <div className="panel">
                  <div className="section-heading">
                    <h2>Validation record</h2>
                    <button
                      type="button"
                      className="button"
                      disabled={!!busy}
                      onClick={() => void validateModel()}
                    >
                      <ShieldCheck size={16} /> Run validation
                    </button>
                  </div>
                  {!validation ? (
                    <Blank title="Check this model">
                      Validation reports structural diagnostics and a bounded
                      analysis of possible token routes.
                    </Blank>
                  ) : (
                    <>
                      <div className="verification-summary">
                        <CheckCircle2 size={32} />
                        <div>
                          <h2>Structure valid · supported subset</h2>
                          <p>
                            Bounded verification:{" "}
                            <strong>
                              {validation.verification.status.replaceAll(
                                "_",
                                " ",
                              )}
                            </strong>
                          </p>
                        </div>
                        <Status value={validation.verification.status} />
                      </div>
                      <div className="facts">
                        <div>
                          <span>Explored markings</span>
                          <strong className="mono">
                            {validation.verification.states}
                          </strong>
                        </div>
                        <div>
                          <span>Deadlock states</span>
                          <strong className="mono">
                            {validation.verification.deadlock_count}
                          </strong>
                        </div>
                        <div>
                          <span>Exploration limit reached</span>
                          <strong>
                            {validation.verification.truncated
                              ? "Yes — inconclusive"
                              : "No"}
                          </strong>
                        </div>
                      </div>
                      <p className="method-note">
                        {validation.verification.scope}. Full workflow-net
                        soundness is not claimed.
                      </p>
                      {validation.verification.counterexample_trace.length >
                        0 && (
                        <p>
                          Counterexample:{" "}
                          {validation.verification.counterexample_trace.join(
                            " → ",
                          )}
                        </p>
                      )}
                      {diagnosticList(validation.diagnostics)}
                      <button
                        type="button"
                        className="button primary"
                        onClick={() => go("Simulate")}
                      >
                        Configure simulation <ArrowRight size={16} />
                      </button>
                    </>
                  )}
                </div>
              )}

              {(section === "Simulate" || section === "Optimize") && (
                <>
                  <ScenarioEditor
                    {...{
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
                    }}
                  />
                  {run && (
                    <section className="panel experiment">
                      <div className="section-heading">
                        <h2>
                          {run.mode === "optimize"
                            ? "Fixed-resource experiment"
                            : "Baseline experiment"}
                        </h2>
                        <div className="run-meta">
                          <span className="mono">{run.id.slice(0, 8)}</span>
                          <Status value={run.state} />
                        </div>
                      </div>
                      {active ? (
                        <div className="job-stage" role="status">
                          <LoaderCircle size={19} className="spin" />
                          <span>{run.stage}…</span>
                          <button
                            type="button"
                            className="button small"
                            onClick={() =>
                              void action("Canceling run", async () => {
                                setRun(
                                  await api<Run>(`/runs/${run.id}/cancel`, {}),
                                );
                              })
                            }
                          >
                            Cancel
                          </button>
                        </div>
                      ) : run.state === "failed" ? (
                        <div className="alert error">{run.error}</div>
                      ) : run.state === "canceled" ? (
                        <p className="muted">
                          This experiment was canceled. No results were
                          accepted.
                        </p>
                      ) : (
                        result &&
                        selectedSimulation && (
                          <>
                            <div className="result-banner">
                              <div>
                                <span className="eyebrow">
                                  {result.optimization
                                    ? "SCHEDULING / IDENTICAL CAPACITY"
                                    : "BASELINE / STATED ASSUMPTIONS"}
                                </span>
                                <h3>
                                  {result.optimization?.explanation ||
                                    "Single-case baseline completed."}
                                </h3>
                              </div>
                              {result.optimization && (
                                <Status value={result.optimization.status} />
                              )}
                            </div>
                            <div className="metric-strip">
                              <div>
                                <span>Baseline completion</span>
                                <strong>
                                  {num(result.baseline.metrics.makespan)}
                                  <small>{result.config.unit}</small>
                                </strong>
                              </div>
                              <div>
                                <span>Selected completion</span>
                                <strong>
                                  {num(selectedSimulation.metrics.makespan)}
                                  <small>{result.config.unit}</small>
                                </strong>
                              </div>
                              <div>
                                <span>Simulated scheduling change</span>
                                <strong>
                                  {result.optimization
                                    ? `${num(result.optimization.improvement_pct)}%`
                                    : "—"}
                                </strong>
                              </div>
                              <div>
                                <span>Total task queue wait</span>
                                <strong>
                                  {num(selectedSimulation.metrics.total_wait)}
                                  <small>{result.config.unit}</small>
                                </strong>
                              </div>
                            </div>
                            <p className="method-note">
                              {result.model_name} · run assumptions are frozen
                              below. Form edits above apply to your next
                              experiment.{" "}
                              {result.optimization &&
                                `Solver ${result.optimization.status}; bound ${num(result.optimization.best_bound)}; gap ${result.optimization.relative_gap == null ? "unknown" : `${num(result.optimization.relative_gap * 100)}%`}; limit ${result.optimization.time_limit_seconds}s.`}{" "}
                              No structural BPMN change. Throughput and
                              real-world savings are not measured.
                            </p>
                            <Timeline
                              data={selectedSimulation}
                              onSelect={(id) => {
                                setSelected(id);
                                go("Model");
                              }}
                            />
                            <div className="two-column result-notes">
                              <div>
                                <h3>Resource utilization</h3>
                                {Object.entries(
                                  selectedSimulation.metrics
                                    .utilization_by_role,
                                ).map(([role, value]) => (
                                  <div className="utilization" key={role}>
                                    <span>{role}</span>
                                    <div>
                                      <i style={{ width: `${value * 100}%` }} />
                                    </div>
                                    <strong className="mono">
                                      {num(value * 100)}%
                                    </strong>
                                  </div>
                                ))}
                                <p className="muted">
                                  Busy labor cost:{" "}
                                  {num(
                                    selectedSimulation.metrics.busy_labor_cost,
                                  )}
                                  <br />
                                  Staffed capacity cost:{" "}
                                  {num(
                                    selectedSimulation.metrics
                                      .staffed_capacity_cost,
                                  )}
                                </p>
                              </div>
                              <div>
                                <h3>What the evidence suggests</h3>
                                {result.baseline.critical_path_task_ids && (
                                  <p className="muted">
                                    Precedence-only lower bound:{" "}
                                    {num(
                                      result.baseline.precedence_lower_bound,
                                    )}{" "}
                                    {result.config.unit}. Task path:{" "}
                                    {result.baseline.critical_path_task_ids.join(
                                      " → ",
                                    )}
                                    . Resource waits are excluded.
                                  </p>
                                )}
                                {result.recommendations.map((r) => (
                                  <p key={r.message}>{r.message}</p>
                                ))}
                                <p className="muted">
                                  {result.assumptions.join(" ")}
                                </p>
                              </div>
                            </div>
                            <details>
                              <summary>
                                Frozen inputs, routing, and limitations
                              </summary>
                              <p className="muted">
                                {result.baseline.warnings.join(" ")}
                              </p>
                              <pre>
                                {JSON.stringify(result.config, null, 2)}
                              </pre>
                            </details>
                            <div className="run-actions">
                              <a
                                className="button"
                                href={download(run.id, "report.pdf")}
                              >
                                <Download size={15} /> PDF report
                              </a>
                              <button
                                type="button"
                                className="text-button"
                                onClick={() => go("Reports")}
                              >
                                All exports <ArrowRight size={15} />
                              </button>
                            </div>
                          </>
                        )
                      )}
                    </section>
                  )}
                  {runs.length > 0 && (
                    <section className="panel">
                      <div className="section-heading">
                        <h2>Experiment history</h2>
                        <History size={17} />
                      </div>
                      <div className="history-list">
                        {runs.map((r) => (
                          <div className="history-row" key={r.id}>
                            <button
                              type="button"
                              onClick={() => void selectHistory(r)}
                            >
                              <span className="mono">{r.id.slice(0, 8)}</span>
                              <div>
                                {r.mode === "optimize"
                                  ? "Fixed-resource scheduling"
                                  : "Baseline simulation"}
                                <small>{date(r.created)}</small>
                              </div>
                              <Status value={r.state} />
                            </button>
                            {!["running", "queued"].includes(r.state) && (
                              <button
                                type="button"
                                className="remove-run"
                                aria-label={`Remove run ${r.id.slice(0, 8)}`}
                                onClick={() =>
                                  void action("Removing run", async () => {
                                    await api(
                                      `/runs/${r.id}`,
                                      undefined,
                                      "DELETE",
                                    );
                                    setRuns((prev) =>
                                      prev.filter((v) => v.id !== r.id),
                                    );
                                    if (run?.id === r.id) setRun(null);
                                  })
                                }
                              >
                                <X size={14} />
                              </button>
                            )}
                          </div>
                        ))}
                      </div>
                    </section>
                  )}
                </>
              )}

              {section === "Compare" && (
                <section className="panel">
                  <div className="section-heading">
                    <h2>Historical experiment comparison</h2>
                    <GitCompareArrows size={19} />
                  </div>
                  <p className="muted">
                    Different staffing, timing or routing assumptions are
                    identified explicitly. Compare matching model versions for
                    meaningful scheduling evidence.
                  </p>
                  <div className="compare-selectors">
                    {[0, 1].map((index) => (
                      <label key={index}>
                        {index === 0
                          ? "Reference experiment"
                          : "Comparison experiment"}
                        <select
                          aria-label={
                            index === 0
                              ? "Reference experiment"
                              : "Comparison experiment"
                          }
                          value={compareIds[index]}
                          onChange={(e) =>
                            setCompareIds((prev) =>
                              prev.map((v, i) =>
                                i === index ? e.target.value : v,
                              ),
                            )
                          }
                        >
                          <option value="">Choose a completed run</option>
                          {runs
                            .filter((r) => r.state === "succeeded")
                            .map((r) => (
                              <option key={r.id} value={r.id}>
                                {r.id.slice(0, 8)} · {r.mode} ·{" "}
                                {date(r.created)}
                              </option>
                            ))}
                        </select>
                      </label>
                    ))}
                    <button
                      type="button"
                      className="button primary"
                      disabled={!!busy || !compareIds.every(Boolean)}
                      onClick={() =>
                        void action("Comparing saved runs", async () =>
                          setComparison(
                            await api(
                              `/compare?left=${compareIds[0]}&right=${compareIds[1]}`,
                            ),
                          ),
                        )
                      }
                    >
                      Compare runs <ArrowRight size={15} />
                    </button>
                  </div>
                  {comparison && (
                    <>
                      <div className="alert">
                        <strong>{comparison.comparison_scope}</strong>
                        {comparison.warning && (
                          <span>{comparison.warning}</span>
                        )}
                      </div>
                      <div className="compare-grid">
                        {[comparison.left, comparison.right].map((r) => {
                          const data =
                            r.result!.optimization?.selected ||
                            r.result!.baseline;
                          return (
                            <div key={r === comparison.left ? "left" : "right"}>
                              <h3 className="mono">{r.id.slice(0, 8)}</h3>
                              <p>{r.result!.model_name}</p>
                              <dl>
                                <dt>Completion</dt>
                                <dd>
                                  {num(data.metrics.makespan)} {r.config.unit}
                                </dd>
                                <dt>Queue wait</dt>
                                <dd>
                                  {num(data.metrics.total_wait)} {r.config.unit}
                                </dd>
                                <dt>Roles / capacities</dt>
                                <dd>
                                  {r.config.resources
                                    .map((v) => `${v.role}: ${v.capacity}`)
                                    .join(", ")}
                                </dd>
                                <dt>Staffed capacity cost</dt>
                                <dd>
                                  {num(data.metrics.staffed_capacity_cost)}
                                </dd>
                                <dt>Solver</dt>
                                <dd>
                                  {r.result!.optimization?.status || "not run"}
                                </dd>
                              </dl>
                              <Timeline
                                data={data}
                                onSelect={(id) => {
                                  const source = models.find(
                                    (m) => m.id === r.model_id,
                                  );
                                  if (source) selectModel(source, r.config);
                                  setSelected(id);
                                  go("Model");
                                }}
                              />
                            </div>
                          );
                        })}
                      </div>
                    </>
                  )}
                </section>
              )}

              {section === "Reports" && (
                <section className="panel">
                  <div className="section-heading">
                    <h2>Saved evidence & exports</h2>
                    <Download size={19} />
                  </div>
                  <p className="muted">
                    Original BPMN, schedule, inputs, solver evidence, and a
                    readable PDF. A scheduling result never claims to be a
                    revised process model.
                  </p>
                  {!runs.some((r) => r.state === "succeeded") ? (
                    <Blank title="No completed reports yet">
                      Complete a simulation or optimization to create an
                      immutable set of run artifacts.
                    </Blank>
                  ) : (
                    <div className="report-list">
                      {runs
                        .filter((r) => r.state === "succeeded")
                        .map((r) => (
                          <article className="report-row" key={r.id}>
                            <div>
                              <span className="mono">
                                {r.id.slice(0, 8)} / {date(r.created)}
                              </span>
                              <h3>{r.result?.model_name}</h3>
                              <p>
                                {r.mode === "optimize"
                                  ? "Fixed-resource scheduling"
                                  : "Baseline simulation"}{" "}
                                · Original BPMN preserved
                              </p>
                            </div>
                            <div className="export-links">
                              {[
                                ["report.pdf", "PDF report"],
                                ["original.bpmn", "Original BPMN"],
                                ["schedule.csv", "Schedule CSV"],
                                ["results.json", "Results JSON"],
                                ["bundle.zip", "Bundle ZIP"],
                              ].map(([name, label]) => (
                                <a
                                  key={name}
                                  className={
                                    name === "report.pdf"
                                      ? "button primary small"
                                      : "button small"
                                  }
                                  href={download(r.id, name)}
                                >
                                  <Download size={13} />
                                  {label}
                                </a>
                              ))}
                            </div>
                          </article>
                        ))}
                    </div>
                  )}
                </section>
              )}
            </>
          )}
          <footer className="page-footer">
            <span>MODELS ARE HYPOTHESES. ASSUMPTIONS ARE VISIBLE.</span>
            <span className="mono">LOCAL-FIRST / NO DEPLOYMENT</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
