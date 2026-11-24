/// <reference types="vite/client" />

import {
  isDialogueMessage,
  isEventMessage,
  isTickMessage,
  type DialogueMessage,
  type EventMessage,
  type TickMessage,
  type WsConnectionState,
} from "../types/sim";

export interface VillageWsClientCallbacks {
  onTick: (msg: TickMessage) => void;
  onDialogue?: (msg: DialogueMessage) => void;
  onEvent?: (msg: EventMessage) => void;
  onStatusChange?: (status: WsConnectionState) => void;
}

const INITIAL_RECONNECT_DELAY_MS = 500;
const MAX_RECONNECT_DELAY_MS = 5000;

/** Resolve the WebSocket endpoint URL from Vite env or current window host. */
export function resolveWsUrl(): string {
  const configured = import.meta.env.VITE_WS_URL;
  if (typeof configured === "string" && configured.trim().length > 0) {
    return configured.trim();
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws`;
}

/** Passive WebSocket client consuming authoritative server tick snapshots with auto-reconnect. */
export class VillageWsClient {
  private readonly callbacks: VillageWsClientCallbacks;
  private readonly wsUrl: string;
  private socket: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempt = 0;
  private manuallyDisconnected = false;
  private status: WsConnectionState = "disconnected";

  constructor(callbacks: VillageWsClientCallbacks, wsUrl: string = resolveWsUrl()) {
    this.callbacks = callbacks;
    this.wsUrl = wsUrl;
  }

  public getStatus(): WsConnectionState {
    return this.status;
  }

  /** Open the WebSocket connection and begin listening for server tick snapshots. */
  public connect(): void {
    this.clearReconnectTimer();
    if (
      this.socket !== null &&
      (this.socket.readyState === WebSocket.OPEN ||
        this.socket.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    this.manuallyDisconnected = false;
    this.setStatus("connecting");

    const ws = new WebSocket(this.wsUrl);
    this.socket = ws;

    ws.addEventListener("open", () => {
      if (this.socket !== ws || this.manuallyDisconnected) {
        return;
      }
      this.reconnectAttempt = 0;
      this.setStatus("connected");
    });

    ws.addEventListener("message", (event: MessageEvent<unknown>) => {
      if (this.socket !== ws || this.manuallyDisconnected) {
        return;
      }
      if (typeof event.data !== "string") {
        return;
      }
      try {
        const parsed: unknown = JSON.parse(event.data);
        if (isTickMessage(parsed)) {
          this.callbacks.onTick(parsed);
        } else if (isDialogueMessage(parsed)) {
          this.callbacks.onDialogue?.(parsed);
        } else if (isEventMessage(parsed)) {
          this.callbacks.onEvent?.(parsed);
        }
      } catch {
        // Ignore malformed JSON payloads without disrupting the Phaser render loop.
      }
    });

    ws.addEventListener("error", () => {
      this.handleSocketClosed(ws);
    });

    ws.addEventListener("close", () => {
      this.handleSocketClosed(ws);
    });
  }

  /** Cancel pending reconnect timers and close any active socket cleanly. */
  public disconnect(): void {
    this.manuallyDisconnected = true;
    this.clearReconnectTimer();
    this.reconnectAttempt = 0;

    const ws = this.socket;
    this.socket = null;
    if (
      ws !== null &&
      (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)
    ) {
      try {
        ws.close();
      } catch {
        // Ignore close errors on manual teardown.
      }
    }

    this.setStatus("disconnected");
  }

  private handleSocketClosed(ws: WebSocket): void {
    if (this.socket !== ws) {
      return;
    }
    this.socket = null;
    if (
      ws.readyState === WebSocket.CONNECTING ||
      ws.readyState === WebSocket.OPEN
    ) {
      try {
        ws.close();
      } catch {
        // Ignore close errors while transitioning to reconnect.
      }
    }

    if (this.manuallyDisconnected) {
      this.setStatus("disconnected");
      return;
    }

    this.scheduleReconnect();
  }

  private scheduleReconnect(): void {
    this.clearReconnectTimer();
    const delayMs = Math.min(
      MAX_RECONNECT_DELAY_MS,
      INITIAL_RECONNECT_DELAY_MS * 2 ** this.reconnectAttempt,
    );
    this.reconnectAttempt += 1;
    this.setStatus("reconnecting");

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.manuallyDisconnected) {
        this.connect();
      }
    }, delayMs);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private setStatus(next: WsConnectionState): void {
    if (this.status !== next) {
      this.status = next;
      this.callbacks.onStatusChange?.(next);
    }
  }
}
