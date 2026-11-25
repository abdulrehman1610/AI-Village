export interface AgentSnapshot {
  id: string;
  name: string;
  role: string;
  sprite_index: number;
  x: number;
  y: number;
  target_location: string | null;
  current_action: string;
  mood?: string;
}

export type SimSpeed = 1 | 4 | 16;

export interface SimControlResponse {
  running: boolean;
  speed: number;
  tick: number;
  sim_time: string;
  day: number;
}

export interface TickMessage {
  type: "tick";
  tick: number;
  sim_time: string;
  day: number;
  speed: number;
  running: boolean;
  agents: AgentSnapshot[];
}

export interface NamedLocationInfo {
  name: string;
  category: string;
  anchor_x: number;
  anchor_y: number;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface WorldInfo {
  width: number;
  height: number;
  tile_size: number;
  locations: NamedLocationInfo[];
}

export interface HealthInfo {
  status: string;
  tick: number;
  sim_time: string;
  agents: number;
  map_width: number;
  map_height: number;
}

export interface DialogueTurn {
  speaker_id: string;
  speaker_name: string;
  text: string;
}

export interface DialogueMessage {
  type: "dialogue";
  tick: number;
  sim_time: string;
  participants: string[];
  participant_names: string[];
  location: string | null;
  turns: DialogueTurn[];
  summary: string;
}

export interface EventMessage {
  type: "event";
  id: number | null;
  tick: number;
  sim_time: string;
  text: string;
  location: string | null;
  affected_agents: string[];
}

export interface ReflectionMessage {
  type: "reflection";
  tick: number;
  sim_time: string;
  agent_id: string;
  agent_name: string;
  insight: string;
  cited_memory_ids: number[];
  mood?: string;
}

export interface AgentPersonaProfile {
  id: string;
  name: string;
  age: number;
  role: string;
  traits: string[];
  bio: string;
  home_location: string;
  starting_goals: string[];
}

export interface AgentPlanStep {
  duration_minutes: number;
  location: string;
  action: string;
  start_tick: number;
  end_tick: number;
  arrived: boolean;
}

export interface AgentPlanBlock {
  start_hour: number;
  end_hour: number;
  location: string;
  description: string;
  hourly_focus: string | null;
  actions: AgentPlanStep[];
}

export interface AgentPlanView {
  day: number | null;
  active_block_index: number;
  active_minute_index: number;
  hourly_focus: string | null;
  current_step: AgentPlanStep | null;
  daily_plan: AgentPlanBlock[];
}

export interface AgentMemoryItem {
  id: number | null;
  type: string;
  text: string;
  importance: number;
  created_tick: number;
  last_access_tick: number;
  cited_memory_ids: number[];
}

export interface AgentRelationshipItem {
  peer_id: string;
  peer_name: string;
  affinity: number;
  notes: string;
  last_interaction_tick: number;
}

export interface AgentDetail {
  id: string;
  name: string;
  role: string;
  sprite_index: number;
  x: number;
  y: number;
  home_location: string;
  current_location: string;
  target_location: string | null;
  current_action: string;
  mood: string;
  accumulated_importance: number;
  reflection_threshold: number;
  persona: AgentPersonaProfile;
  plan: AgentPlanView;
  recent_memories: AgentMemoryItem[];
  top_memories: AgentMemoryItem[];
  reflections: AgentMemoryItem[];
  relationships: AgentRelationshipItem[];
}

export interface RelationshipNode {
  id: string;
  name: string;
  role: string;
  mood: string;
}

export interface RelationshipEdge {
  agent_a: string;
  agent_b: string;
  agent_a_name: string;
  agent_b_name: string;
  affinity: number;
  notes: string;
  last_interaction_tick: number;
}

export interface RelationshipsResponse {
  nodes: RelationshipNode[];
  edges: RelationshipEdge[];
}

export interface InjectEventRequest {
  text: string;
  location: string | null;
}

export interface InjectEventResponse {
  id: number | null;
  tick: number;
  sim_time: string;
  text: string;
  location: string | null;
  affected_agents: string[];
}

export interface PurposeMetrics {
  purpose: string;
  calls: number;
  cache_hits: number;
  tokens_in: number;
  tokens_out: number;
  total_tokens: number;
  cost_est: number;
  avg_latency_ms: number;
}

export interface ModelMetrics {
  model: string;
  calls: number;
  cache_hits: number;
  tokens_in: number;
  tokens_out: number;
  total_tokens: number;
  cost_est: number;
  avg_latency_ms: number;
}

export interface TickMetricsPoint {
  tick: number;
  calls: number;
  cache_hits: number;
  tokens_in: number;
  tokens_out: number;
  total_tokens: number;
  cost_est: number;
  avg_latency_ms: number;
  cumulative_tokens: number;
  cumulative_cost_est: number;
}

export interface MetricsSnapshot {
  tick: number;
  sim_time: string;
  day: number;
  total_calls: number;
  cache_hits: number;
  cache_hit_rate: number;
  tokens_in: number;
  tokens_out: number;
  total_tokens: number;
  cost_est: number;
  avg_latency_ms: number;
  max_latency_ms: number;
  daily_budget_usd: number;
  daily_token_limit: number;
  budget_day: number;
  budget_tokens_used: number;
  budget_cost_used: number;
  by_purpose: PurposeMetrics[];
  by_model: ModelMetrics[];
  history: TickMetricsPoint[];
}

export type MetricsMessage = MetricsSnapshot & { type: "metrics" };

export interface ReplayDaySummary {
  day: number;
  tick_count: number;
  frame_count: number;
  first_tick: number;
  last_tick: number;
  first_sim_time: string;
  last_sim_time: string;
}

export interface ReplayDaysResponse {
  current_day: number;
  days: ReplayDaySummary[];
}

export type ReplayFrame =
  | TickMessage
  | DialogueMessage
  | EventMessage
  | ReflectionMessage;

export interface ReplayLogResponse {
  day: number;
  tick_count: number;
  first_tick: number | null;
  last_tick: number | null;
  frames: ReplayFrame[];
}

export type WsConnectionState =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isNullableInteger(value: unknown): value is number | null {
  return value === null || isInteger(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isOptionalString(value: unknown): value is string | undefined {
  return value === undefined || typeof value === "string";
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isIntegerArray(value: unknown): value is number[] {
  return Array.isArray(value) && value.every(isInteger);
}

/** Validate that an unknown JSON value matches the backend AgentSnapshot schema. */
export function isAgentSnapshot(data: unknown): data is AgentSnapshot {
  if (!isRecord(data)) {
    return false;
  }
  return (
    typeof data.id === "string" &&
    typeof data.name === "string" &&
    typeof data.role === "string" &&
    isInteger(data.sprite_index) &&
    isInteger(data.x) &&
    isInteger(data.y) &&
    isNullableString(data.target_location) &&
    typeof data.current_action === "string" &&
    isOptionalString(data.mood)
  );
}

/** Validate that an unknown JSON value matches the backend TickPayload schema. */
export function isTickMessage(data: unknown): data is TickMessage {
  if (!isRecord(data)) {
    return false;
  }
  return (
    data.type === "tick" &&
    isInteger(data.tick) &&
    typeof data.sim_time === "string" &&
    isInteger(data.day) &&
    isFiniteNumber(data.speed) &&
    typeof data.running === "boolean" &&
    Array.isArray(data.agents) &&
    data.agents.every(isAgentSnapshot)
  );
}

/** Validate that an unknown JSON value matches the backend DialogueTurn schema. */
export function isDialogueTurn(data: unknown): data is DialogueTurn {
  if (!isRecord(data)) {
    return false;
  }
  return (
    typeof data.speaker_id === "string" &&
    typeof data.speaker_name === "string" &&
    typeof data.text === "string"
  );
}

/** Validate that an unknown JSON value matches the backend DialogueMessage schema. */
export function isDialogueMessage(data: unknown): data is DialogueMessage {
  if (!isRecord(data)) {
    return false;
  }
  return (
    data.type === "dialogue" &&
    isInteger(data.tick) &&
    typeof data.sim_time === "string" &&
    isStringArray(data.participants) &&
    isStringArray(data.participant_names) &&
    isNullableString(data.location) &&
    Array.isArray(data.turns) &&
    data.turns.every(isDialogueTurn) &&
    typeof data.summary === "string"
  );
}

/** Validate that an unknown JSON value matches the backend EventMessage schema. */
export function isEventMessage(data: unknown): data is EventMessage {
  if (!isRecord(data)) {
    return false;
  }
  return (
    data.type === "event" &&
    isNullableInteger(data.id) &&
    isInteger(data.tick) &&
    typeof data.sim_time === "string" &&
    typeof data.text === "string" &&
    isNullableString(data.location) &&
    isStringArray(data.affected_agents)
  );
}

/** Validate that an unknown JSON value matches the backend ReflectionMessage schema. */
export function isReflectionMessage(data: unknown): data is ReflectionMessage {
  if (!isRecord(data)) {
    return false;
  }
  return (
    data.type === "reflection" &&
    isInteger(data.tick) &&
    typeof data.sim_time === "string" &&
    typeof data.agent_id === "string" &&
    typeof data.agent_name === "string" &&
    typeof data.insight === "string" &&
    isIntegerArray(data.cited_memory_ids) &&
    isOptionalString(data.mood)
  );
}

/** Validate that an unknown JSON value matches the backend SimControlResponse schema. */
export function isSimControlResponse(data: unknown): data is SimControlResponse {
  if (!isRecord(data)) {
    return false;
  }
  return (
    typeof data.running === "boolean" &&
    isFiniteNumber(data.speed) &&
    isInteger(data.tick) &&
    typeof data.sim_time === "string" &&
    isInteger(data.day)
  );
}

/** Validate that an unknown JSON value matches the backend AgentPersonaProfile schema. */
export function isAgentPersonaProfile(data: unknown): data is AgentPersonaProfile {
  if (!isRecord(data)) {
    return false;
  }
  return (
    typeof data.id === "string" &&
    typeof data.name === "string" &&
    isInteger(data.age) &&
    typeof data.role === "string" &&
    isStringArray(data.traits) &&
    typeof data.bio === "string" &&
    typeof data.home_location === "string" &&
    isStringArray(data.starting_goals)
  );
}

/** Validate that an unknown JSON value matches the backend AgentPlanStep schema. */
export function isAgentPlanStep(data: unknown): data is AgentPlanStep {
  if (!isRecord(data)) {
    return false;
  }
  return (
    isInteger(data.duration_minutes) &&
    typeof data.location === "string" &&
    typeof data.action === "string" &&
    isInteger(data.start_tick) &&
    isInteger(data.end_tick) &&
    typeof data.arrived === "boolean"
  );
}

/** Validate that an unknown JSON value matches the backend AgentPlanBlock schema. */
export function isAgentPlanBlock(data: unknown): data is AgentPlanBlock {
  if (!isRecord(data)) {
    return false;
  }
  return (
    isInteger(data.start_hour) &&
    isInteger(data.end_hour) &&
    typeof data.location === "string" &&
    typeof data.description === "string" &&
    isNullableString(data.hourly_focus) &&
    Array.isArray(data.actions) &&
    data.actions.every(isAgentPlanStep)
  );
}

/** Validate that an unknown JSON value matches the backend AgentPlanView schema. */
export function isAgentPlanView(data: unknown): data is AgentPlanView {
  if (!isRecord(data)) {
    return false;
  }
  return (
    isNullableInteger(data.day) &&
    isInteger(data.active_block_index) &&
    isInteger(data.active_minute_index) &&
    isNullableString(data.hourly_focus) &&
    (data.current_step === null || isAgentPlanStep(data.current_step)) &&
    Array.isArray(data.daily_plan) &&
    data.daily_plan.every(isAgentPlanBlock)
  );
}

/** Validate that an unknown JSON value matches the backend AgentMemoryItem schema. */
export function isAgentMemoryItem(data: unknown): data is AgentMemoryItem {
  if (!isRecord(data)) {
    return false;
  }
  return (
    isNullableInteger(data.id) &&
    typeof data.type === "string" &&
    typeof data.text === "string" &&
    isInteger(data.importance) &&
    isInteger(data.created_tick) &&
    isInteger(data.last_access_tick) &&
    isIntegerArray(data.cited_memory_ids)
  );
}

/** Validate that an unknown JSON value matches the backend AgentRelationshipItem schema. */
export function isAgentRelationshipItem(data: unknown): data is AgentRelationshipItem {
  if (!isRecord(data)) {
    return false;
  }
  return (
    typeof data.peer_id === "string" &&
    typeof data.peer_name === "string" &&
    isFiniteNumber(data.affinity) &&
    typeof data.notes === "string" &&
    isInteger(data.last_interaction_tick)
  );
}

/** Validate that an unknown JSON value matches the backend GET /agents/{id} schema. */
export function isAgentDetail(data: unknown): data is AgentDetail {
  if (!isRecord(data)) {
    return false;
  }
  return (
    typeof data.id === "string" &&
    typeof data.name === "string" &&
    typeof data.role === "string" &&
    isInteger(data.sprite_index) &&
    isInteger(data.x) &&
    isInteger(data.y) &&
    typeof data.home_location === "string" &&
    typeof data.current_location === "string" &&
    isNullableString(data.target_location) &&
    typeof data.current_action === "string" &&
    typeof data.mood === "string" &&
    isFiniteNumber(data.accumulated_importance) &&
    isFiniteNumber(data.reflection_threshold) &&
    isAgentPersonaProfile(data.persona) &&
    isAgentPlanView(data.plan) &&
    Array.isArray(data.recent_memories) &&
    data.recent_memories.every(isAgentMemoryItem) &&
    Array.isArray(data.top_memories) &&
    data.top_memories.every(isAgentMemoryItem) &&
    Array.isArray(data.reflections) &&
    data.reflections.every(isAgentMemoryItem) &&
    Array.isArray(data.relationships) &&
    data.relationships.every(isAgentRelationshipItem)
  );
}

/** Validate that an unknown JSON value matches the backend RelationshipNode schema. */
export function isRelationshipNode(data: unknown): data is RelationshipNode {
  if (!isRecord(data)) {
    return false;
  }
  return (
    typeof data.id === "string" &&
    typeof data.name === "string" &&
    typeof data.role === "string" &&
    typeof data.mood === "string"
  );
}

/** Validate that an unknown JSON value matches the backend RelationshipEdge schema. */
export function isRelationshipEdge(data: unknown): data is RelationshipEdge {
  if (!isRecord(data)) {
    return false;
  }
  return (
    typeof data.agent_a === "string" &&
    typeof data.agent_b === "string" &&
    typeof data.agent_a_name === "string" &&
    typeof data.agent_b_name === "string" &&
    isFiniteNumber(data.affinity) &&
    typeof data.notes === "string" &&
    isInteger(data.last_interaction_tick)
  );
}

/** Validate that an unknown JSON value matches the backend GET /relationships schema. */
export function isRelationshipsResponse(data: unknown): data is RelationshipsResponse {
  if (!isRecord(data)) {
    return false;
  }
  return (
    Array.isArray(data.nodes) &&
    data.nodes.every(isRelationshipNode) &&
    Array.isArray(data.edges) &&
    data.edges.every(isRelationshipEdge)
  );
}

function hasCallMetricsFields(data: Record<string, unknown>): boolean {
  return (
    isInteger(data.calls) &&
    isInteger(data.cache_hits) &&
    isInteger(data.tokens_in) &&
    isInteger(data.tokens_out) &&
    isInteger(data.total_tokens) &&
    isFiniteNumber(data.cost_est) &&
    isFiniteNumber(data.avg_latency_ms)
  );
}

/** Validate that an unknown JSON value matches the backend PurposeMetrics schema. */
export function isPurposeMetrics(data: unknown): data is PurposeMetrics {
  if (!isRecord(data)) {
    return false;
  }
  return typeof data.purpose === "string" && hasCallMetricsFields(data);
}

/** Validate that an unknown JSON value matches the backend ModelMetrics schema. */
export function isModelMetrics(data: unknown): data is ModelMetrics {
  if (!isRecord(data)) {
    return false;
  }
  return typeof data.model === "string" && hasCallMetricsFields(data);
}

/** Validate that an unknown JSON value matches the backend TickMetricsPoint schema. */
export function isTickMetricsPoint(data: unknown): data is TickMetricsPoint {
  if (!isRecord(data)) {
    return false;
  }
  return (
    isInteger(data.tick) &&
    hasCallMetricsFields(data) &&
    isInteger(data.cumulative_tokens) &&
    isFiniteNumber(data.cumulative_cost_est)
  );
}

/** Validate that an unknown JSON value matches the backend MetricsSnapshot schema. */
export function isMetricsSnapshot(data: unknown): data is MetricsSnapshot {
  if (!isRecord(data)) {
    return false;
  }
  return (
    isInteger(data.tick) &&
    typeof data.sim_time === "string" &&
    isInteger(data.day) &&
    isInteger(data.total_calls) &&
    isInteger(data.cache_hits) &&
    isFiniteNumber(data.cache_hit_rate) &&
    isInteger(data.tokens_in) &&
    isInteger(data.tokens_out) &&
    isInteger(data.total_tokens) &&
    isFiniteNumber(data.cost_est) &&
    isFiniteNumber(data.avg_latency_ms) &&
    isFiniteNumber(data.max_latency_ms) &&
    isFiniteNumber(data.daily_budget_usd) &&
    isInteger(data.daily_token_limit) &&
    isInteger(data.budget_day) &&
    isInteger(data.budget_tokens_used) &&
    isFiniteNumber(data.budget_cost_used) &&
    Array.isArray(data.by_purpose) &&
    data.by_purpose.every(isPurposeMetrics) &&
    Array.isArray(data.by_model) &&
    data.by_model.every(isModelMetrics) &&
    Array.isArray(data.history) &&
    data.history.every(isTickMetricsPoint)
  );
}

/** Validate that an unknown JSON value matches the WebSocket metrics frame schema. */
export function isMetricsMessage(data: unknown): data is MetricsMessage {
  return isRecord(data) && data.type === "metrics" && isMetricsSnapshot(data);
}

/** Validate that an unknown JSON value matches the backend ReplayDaySummary schema. */
export function isReplayDaySummary(data: unknown): data is ReplayDaySummary {
  if (!isRecord(data)) {
    return false;
  }
  return (
    isInteger(data.day) &&
    isInteger(data.tick_count) &&
    isInteger(data.frame_count) &&
    isInteger(data.first_tick) &&
    isInteger(data.last_tick) &&
    typeof data.first_sim_time === "string" &&
    typeof data.last_sim_time === "string"
  );
}

/** Validate that an unknown JSON value matches the backend GET /replay schema. */
export function isReplayDaysResponse(data: unknown): data is ReplayDaysResponse {
  if (!isRecord(data)) {
    return false;
  }
  return (
    isInteger(data.current_day) &&
    Array.isArray(data.days) &&
    data.days.every(isReplayDaySummary)
  );
}

/** Validate that an unknown JSON value is one of the allowed replay frame types. */
export function isReplayFrame(data: unknown): data is ReplayFrame {
  return (
    isTickMessage(data) ||
    isDialogueMessage(data) ||
    isEventMessage(data) ||
    isReflectionMessage(data)
  );
}

/** Validate that an unknown JSON value matches the backend GET /replay/{day} schema. */
export function isReplayLogResponse(data: unknown): data is ReplayLogResponse {
  if (!isRecord(data)) {
    return false;
  }
  return (
    isInteger(data.day) &&
    isInteger(data.tick_count) &&
    isNullableInteger(data.first_tick) &&
    isNullableInteger(data.last_tick) &&
    Array.isArray(data.frames) &&
    data.frames.every(isReplayFrame)
  );
}
