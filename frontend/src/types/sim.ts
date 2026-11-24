export interface AgentSnapshot {
  id: string;
  name: string;
  role: string;
  sprite_index: number;
  x: number;
  y: number;
  target_location: string | null;
  current_action: string;
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

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
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
    typeof data.current_action === "string"
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
    typeof data.speed === "number" &&
    Number.isFinite(data.speed) &&
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
    (data.id === null || isInteger(data.id)) &&
    isInteger(data.tick) &&
    typeof data.sim_time === "string" &&
    typeof data.text === "string" &&
    isNullableString(data.location) &&
    isStringArray(data.affected_agents)
  );
}
