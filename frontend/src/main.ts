import Phaser from "phaser";
import { VillageWsClient } from "./net/wsClient";
import { VillageScene } from "./scenes/VillageScene";
import type {
  SimControlResponse,
  TickMessage,
  WsConnectionState,
} from "./types/sim";
import { ActivityFeed } from "./ui/activityFeed";
import { AgentInspector } from "./ui/agentInspector";
import { mountEventInjector } from "./ui/eventInjector";
import { TimeControls } from "./ui/timeControls";

interface CachedAgentChip {
  button: HTMLButtonElement;
  nameEl: HTMLElement;
  metaEl: HTMLSpanElement;
}

const statusBadgeEl = document.getElementById("ws-status");
const simTimeEl = document.getElementById("sim-time");
const simTickEl = document.getElementById("sim-tick");
const timeControlsEl = document.getElementById("time-controls");
const agentsBarEl = document.getElementById("agents-bar");
const agentInspectorEl = document.getElementById("agent-inspector");
const activityFeedEl = document.getElementById("activity-feed");
const eventFormEl = document.getElementById("event-form");
const eventLocationEl = document.getElementById("event-location");
const eventTextEl = document.getElementById("event-text");
const eventSubmitEl = document.getElementById("event-submit");
const eventFeedbackEl = document.getElementById("event-feedback");

const STATUS_LABELS: Record<WsConnectionState, string> = {
  connecting: "Connecting...",
  connected: "Live",
  reconnecting: "Reconnecting...",
  disconnected: "Disconnected",
};

const agentChipCache = new Map<string, CachedAgentChip>();

function isTextInputFocused(): boolean {
  const active = document.activeElement;
  return (
    active instanceof HTMLInputElement ||
    active instanceof HTMLTextAreaElement ||
    active instanceof HTMLSelectElement ||
    (active instanceof HTMLElement && active.isContentEditable)
  );
}

function updateConnectionStatus(status: WsConnectionState): void {
  if (statusBadgeEl === null) {
    return;
  }
  statusBadgeEl.className = `status-pill ${status}`;
  statusBadgeEl.textContent = STATUS_LABELS[status];
}

function updateClockDisplay(
  state: Pick<
    SimControlResponse,
    "day" | "sim_time" | "tick" | "running" | "speed"
  >,
): void {
  if (simTimeEl !== null) {
    const stateLabel = state.running ? `${state.speed}x` : "Paused";
    simTimeEl.textContent = `Day ${state.day} · ${state.sim_time} · ${stateLabel}`;
  }

  if (simTickEl !== null) {
    simTickEl.textContent = `Tick ${state.tick}`;
  }
}

function updateChipActiveStates(selectedAgentId: string | null): void {
  for (const [id, chip] of agentChipCache.entries()) {
    const isActive = id === selectedAgentId;
    chip.button.classList.toggle("active", isActive);
    chip.button.setAttribute("aria-pressed", String(isActive));
  }
}

function updateAgentChips(
  tickMsg: TickMessage,
  selectedAgentId: string | null,
  onSelect: (agentId: string) => void,
): void {
  if (agentsBarEl === null) {
    return;
  }

  const incomingIds = new Set(tickMsg.agents.map((agent) => agent.id));
  for (const [id, cached] of agentChipCache.entries()) {
    if (!incomingIds.has(id)) {
      cached.button.remove();
      agentChipCache.delete(id);
    }
  }

  for (const agent of tickMsg.agents) {
    let cached = agentChipCache.get(agent.id);
    if (cached === undefined) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "agent-chip";
      button.dataset.agentId = agent.id;

      const nameEl = document.createElement("strong");
      nameEl.textContent = agent.name;

      const metaEl = document.createElement("span");
      metaEl.className = "agent-meta";

      button.append(nameEl, metaEl);
      button.addEventListener("click", () => {
        onSelect(agent.id);
      });

      cached = { button, nameEl, metaEl };
      agentChipCache.set(agent.id, cached);
      agentsBarEl.appendChild(button);
    }

    if (cached.nameEl.textContent !== agent.name) {
      cached.nameEl.textContent = agent.name;
    }
    cached.metaEl.textContent = ` · ${agent.current_action} (${agent.x}, ${agent.y})`;

    const isActive = agent.id === selectedAgentId;
    cached.button.classList.toggle("active", isActive);
    cached.button.setAttribute("aria-pressed", String(isActive));
  }
}

const villageScene = new VillageScene();
const activityFeed = new ActivityFeed(activityFeedEl);

const timeControls = new TimeControls(timeControlsEl, {
  onStateChange: (state) => {
    updateClockDisplay(state);
  },
});

const agentInspector = new AgentInspector(agentInspectorEl, {
  onClose: () => {
    villageScene.setSelectedAgent(null);
    updateChipActiveStates(null);
  },
});

function selectAgent(agentId: string): void {
  villageScene.setSelectedAgent(agentId);
  updateChipActiveStates(agentId);
  void agentInspector.open(agentId);
}

villageScene.setOnAgentSelect((agentId) => {
  selectAgent(agentId);
});

const game = new Phaser.Game({
  type: Phaser.AUTO,
  parent: "game-container",
  backgroundColor: "#0f172a",
  pixelArt: true,
  input: {
    keyboard: {
      capture: [],
    },
  },
  scale: {
    mode: Phaser.Scale.RESIZE,
    autoCenter: Phaser.Scale.CENTER_BOTH,
  },
  scene: [villageScene],
});

const unmountEventInjector = mountEventInjector({
  formEl: eventFormEl instanceof HTMLFormElement ? eventFormEl : null,
  locationSelectEl:
    eventLocationEl instanceof HTMLSelectElement ? eventLocationEl : null,
  textInputEl: eventTextEl instanceof HTMLInputElement ? eventTextEl : null,
  submitBtnEl:
    eventSubmitEl instanceof HTMLButtonElement ? eventSubmitEl : null,
  feedbackEl: eventFeedbackEl,
  onFocusChange: (focused) => {
    villageScene.setKeyboardEnabled(!focused);
  },
});

const handleWindowKeyDown = (event: KeyboardEvent): void => {
  if (
    event.key === "Escape" &&
    !isTextInputFocused() &&
    agentInspector.getSelectedAgentId() !== null
  ) {
    agentInspector.close();
  }
};
window.addEventListener("keydown", handleWindowKeyDown);

const wsClient = new VillageWsClient({
  onStatusChange: (status) => {
    updateConnectionStatus(status);
  },
  onTick: (tickMsg) => {
    villageScene.applyTick(tickMsg);
    updateClockDisplay(tickMsg);
    timeControls.sync({ running: tickMsg.running, speed: tickMsg.speed });
    updateAgentChips(
      tickMsg,
      agentInspector.getSelectedAgentId(),
      selectAgent,
    );
    agentInspector.applyTick(tickMsg);
  },
  onDialogue: (dialogueMsg) => {
    villageScene.showDialogue(dialogueMsg);
    activityFeed.pushDialogue(dialogueMsg);
    agentInspector.handleDialogue(dialogueMsg);
  },
  onEvent: (eventMsg) => {
    villageScene.showEvent(eventMsg);
    activityFeed.pushEvent(eventMsg);
  },
  onReflection: (reflectionMsg) => {
    villageScene.showReflection(reflectionMsg);
    activityFeed.pushReflection(reflectionMsg);
    agentInspector.handleReflection(reflectionMsg);
  },
});

wsClient.connect();

window.addEventListener("beforeunload", () => {
  window.removeEventListener("keydown", handleWindowKeyDown);
  unmountEventInjector();
  timeControls.destroy();
  agentInspector.destroy();
  agentChipCache.clear();
  wsClient.disconnect();
  game.destroy(true);
});
