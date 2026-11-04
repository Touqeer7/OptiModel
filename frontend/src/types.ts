export interface Node {
  id: string;
  name: string;
  kind: string;
  duration: number | null;
  role: string | null;
  provenance: string;
}
export interface Edge {
  id: string;
  source: string;
  target: string;
  name: string;
  condition: string | null;
  is_default: boolean;
}
export interface Workflow {
  id: string;
  name: string;
  nodes: Node[];
  edges: Edge[];
  assumptions: string[];
  ambiguities: string[];
  time_unit?: string;
}
export interface Diagnostic {
  code?: string;
  message: string;
  element_id?: string | null;
  severity?: string;
}
export interface Resource {
  role: string;
  capacity: number;
  cost_per_unit: number | null;
}
export interface Setting {
  duration: number;
  role: string;
  provenance: string;
}
export interface Config {
  unit: string;
  seed: number;
  solver_seconds: number;
  resources: Resource[];
  tasks: Record<string, Setting>;
  routes: Record<string, string>;
  probabilities: Record<string, Record<string, number>>;
}
export interface Project {
  id: string;
  name: string;
  created: string;
}
export interface Model {
  display_xml?: string;
  id: string;
  project_id: string;
  name: string;
  created: string;
  xml: string;
  ir: Workflow;
  diagnostics: Diagnostic[];
  complexity?: Complexity;
}
export interface Complexity {
  nodes: number;
  flows: number;
  tasks: number;
  exclusive_splits: number;
  parallel_splits: number;
  end_events: number;
  graph_depth: number;
  max_layer_width: number;
  scope: string;
}
export interface Inspection {
  notice: string;
  processes: number;
  nodes: number;
  flows: number;
  cyclic_regions: number;
  scopes: {
    path: string;
    id: string;
    name: string;
    kind: string;
    nodes: number;
    flows: number;
    cyclic_regions: number;
  }[];
  diagnostics: Diagnostic[];
  reference_issues: Diagnostic[];
}
export interface Sample {
  key: string;
  name: string;
  description: string;
  xml: string;
  ir: Workflow;
  config: Config;
}
export interface Verification {
  method?: string;
  status: string;
  soundness: string;
  states: number;
  truncated: boolean;
  proper_completion: boolean | null;
  all_states_can_complete: boolean | null;
  deadlock_count: number;
  counterexample_trace: string[];
  scope: string;
  dead_transitions: string[];
}
export interface Validation {
  complexity?: Complexity;
  structural: string;
  supported: boolean;
  diagnostics: Diagnostic[];
  verification: Verification;
  display_xml: string;
}
export interface Row {
  id: string;
  name: string;
  role: string;
  resource: string;
  duration: number;
  ready: number;
  start: number;
  finish: number;
  wait: number;
  provenance: string;
}
export interface Metrics {
  makespan: number;
  unit: string;
  total_wait: number;
  mean_wait: number;
  utilization_by_role: Record<string, number>;
  busy_labor_cost: number | null;
  staffed_capacity_cost: number | null;
  observed_throughput: number | null;
  task_count: number;
}
export interface Simulation {
  precedence_lower_bound?: number;
  critical_path_task_ids?: string[];
  critical_path_scope?: string;
  metrics: Metrics;
  schedule: Row[];
  warnings: string[];
  selected_routes: Record<string, string>;
}
export interface Optimization {
  method?: string;
  status: string;
  selected: Simulation;
  improvement_pct: number;
  explanation: string;
  best_bound: number | null;
  relative_gap: number | null;
  time_limit_seconds: number;
  bpmn_changed: boolean;
}
export interface Result {
  run_id: string;
  model_name: string;
  config: Config;
  baseline: Simulation;
  optimization: Optimization | null;
  verification: Verification;
  recommendations: { node_id: string | null; message: string }[];
  assumptions: string[];
}
export interface Run {
  id: string;
  model_id: string;
  project_id: string;
  created: string;
  state: string;
  stage: string;
  mode: string;
  config: Config;
  result: Result | null;
  error: string | null;
}
export interface Health {
  capabilities?: {
    limits: { xml_bytes: number; prompt_characters: number; nodes: number };
  };
  provider: {
    configured: boolean;
    model: string | null;
    destination: string | null;
    notice: string;
  };
}
export interface Draft {
  extraction_attempts?: number;
  ir: Workflow | null;
  clarification_questions?: string[];
  diagnostics: Diagnostic[];
  review_required: boolean;
  xml_preview: string | null;
}
export const isTask = (n: Node) =>
  [
    "task",
    "userTask",
    "serviceTask",
    "manualTask",
    "sendTask",
    "receiveTask",
    "scriptTask",
    "businessRuleTask",
  ].includes(n.kind);
