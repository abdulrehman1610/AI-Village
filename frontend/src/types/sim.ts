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

export type WsConnectionState =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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
    typeof data.sprite_index === "number" &&
    Number.isInteger(data.sprite_index) &&
    typeof data.x === "number" &&
    Number.isInteger(data.x) &&
    typeof data.y === "number" &&
    Number.isInteger(data.y) &&
    (data.target_location === null || typeof data.target_location === "string") &&
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
    typeof data.tick === "number" &&
    Number.isInteger(data.tick) &&
    typeof data.sim_time === "string" &&
    typeof data.day === "number" &&
    Number.isInteger(data.day) &&
    typeof data.speed === "number" &&
    Number.isFinite(data.speed) &&
    typeof data.running === "boolean" &&
    Array.isArray(data.agents) &&
    data.agents.every(isAgentSnapshot)
  );
}
