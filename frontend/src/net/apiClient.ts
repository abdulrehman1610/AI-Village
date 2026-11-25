/// <reference types="vite/client" />

import {
  isAgentDetail,
  isMetricsSnapshot,
  isRelationshipsResponse,
  isReplayDaysResponse,
  isReplayLogResponse,
  isSimControlResponse,
  type AgentDetail,
  type InjectEventRequest,
  type InjectEventResponse,
  type MetricsSnapshot,
  type NamedLocationInfo,
  type RelationshipsResponse,
  type ReplayDaysResponse,
  type ReplayLogResponse,
  type SimControlResponse,
  type SimSpeed,
  type WorldInfo,
} from "../types/sim";

/** Resolve the REST API base URL from Vite env or default to same-origin relative paths. */
export function resolveApiBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL;
  if (typeof configured === "string" && configured.trim().length > 0) {
    return configured.trim().replace(/\/+$/, "");
  }
  return "";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNamedLocationInfo(value: unknown): value is NamedLocationInfo {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value.name === "string" &&
    typeof value.category === "string" &&
    typeof value.anchor_x === "number" &&
    typeof value.anchor_y === "number" &&
    typeof value.x === "number" &&
    typeof value.y === "number" &&
    typeof value.width === "number" &&
    typeof value.height === "number"
  );
}

function isWorldInfo(value: unknown): value is WorldInfo {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value.width === "number" &&
    typeof value.height === "number" &&
    typeof value.tile_size === "number" &&
    Array.isArray(value.locations) &&
    value.locations.every(isNamedLocationInfo)
  );
}

function isInjectEventResponse(value: unknown): value is InjectEventResponse {
  if (!isRecord(value)) {
    return false;
  }
  return (
    (value.id === null || (typeof value.id === "number" && Number.isInteger(value.id))) &&
    typeof value.tick === "number" &&
    Number.isInteger(value.tick) &&
    typeof value.sim_time === "string" &&
    typeof value.text === "string" &&
    (value.location === null || typeof value.location === "string") &&
    Array.isArray(value.affected_agents) &&
    value.affected_agents.every((item) => typeof item === "string")
  );
}

async function extractErrorDetail(response: Response): Promise<string | null> {
  try {
    const body: unknown = await response.json();
    if (isRecord(body) && typeof body.detail === "string" && body.detail.trim().length > 0) {
      return body.detail.trim();
    }
  } catch {
    // Ignore non-JSON error bodies and fall back to HTTP status.
  }
  return null;
}

async function requestJson<T>(
  path: string,
  init: RequestInit | undefined,
  guard: (value: unknown) => value is T,
): Promise<T> {
  const url = `${resolveApiBaseUrl()}${path}`;
  const response = await fetch(url, init);
  if (!response.ok) {
    const detail = await extractErrorDetail(response);
    const suffix = detail ? `: ${detail}` : response.statusText ? ` ${response.statusText}` : "";
    throw new Error(`Request to ${path} failed (${response.status})${suffix}`);
  }
  const payload: unknown = await response.json();
  if (!guard(payload)) {
    throw new Error(`Invalid JSON payload received from ${path}`);
  }
  return payload;
}

/** Fetch world dimensions and named locations from GET /world. */
export async function fetchWorld(): Promise<WorldInfo> {
  return requestJson("/world", undefined, isWorldInfo);
}

/** Inject a god-mode event into the running simulation via POST /events. */
export async function injectEvent(payload: InjectEventRequest): Promise<InjectEventResponse> {
  return requestJson(
    "/events",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    isInjectEventResponse,
  );
}

/** Start or resume the simulation loop via POST /sim/start. */
export async function startSim(): Promise<SimControlResponse> {
  return requestJson("/sim/start", { method: "POST" }, isSimControlResponse);
}

/** Pause the simulation loop via POST /sim/pause. */
export async function pauseSim(): Promise<SimControlResponse> {
  return requestJson("/sim/pause", { method: "POST" }, isSimControlResponse);
}

/** Update the simulation speed multiplier (1x, 4x, or 16x) via POST /sim/speed. */
export async function setSimSpeed(speed: SimSpeed): Promise<SimControlResponse> {
  return requestJson(
    "/sim/speed",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ speed }),
    },
    isSimControlResponse,
  );
}

/** Fetch detailed persona, plan, memory, reflection, and relationship state for one agent. */
export async function fetchAgentDetail(agentId: string): Promise<AgentDetail> {
  const normalizedId = agentId.trim();
  if (normalizedId.length === 0) {
    throw new Error("Agent id must be a non-empty string");
  }
  return requestJson(
    `/agents/${encodeURIComponent(normalizedId)}`,
    undefined,
    isAgentDetail,
  );
}

/** Fetch canonical pairwise relationships and agent node metadata from GET /relationships. */
export async function fetchRelationships(): Promise<RelationshipsResponse> {
  return requestJson("/relationships", undefined, isRelationshipsResponse);
}

/** Fetch aggregated LLM call, token, cost, and latency telemetry from GET /metrics. */
export async function fetchMetrics(): Promise<MetricsSnapshot> {
  return requestJson("/metrics", undefined, isMetricsSnapshot);
}

/** Fetch available recorded simulation days and tick summaries from GET /replay. */
export async function fetchReplayDays(): Promise<ReplayDaysResponse> {
  return requestJson("/replay", undefined, isReplayDaysResponse);
}

/** Fetch ordered replay frames for a 1-indexed simulated day from GET /replay/{day}. */
export async function fetchReplayDay(day: number): Promise<ReplayLogResponse> {
  if (!Number.isInteger(day) || day < 1) {
    throw new Error("Replay day must be a positive integer");
  }
  return requestJson(`/replay/${day}`, undefined, isReplayLogResponse);
}
