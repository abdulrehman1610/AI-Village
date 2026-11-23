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
