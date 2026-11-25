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
import { MetricsDashboardPanel } from "./ui/metricsDashboard";
import { RelationshipGraphModal } from "./ui/relationshipGraph";
import { ReplayController } from "./ui/replayControls";
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
const stageEl = document.getElementById("stage");
const agentInspectorEl = document.getElementById("agent-inspector");
const activityFeedEl = document.getElementById("activity-feed");
const relationshipPanelEl = document.getElementById("relationship-panel");
const metricsPanelEl = document.getElementById("metrics-panel");
const godModeBarEl = document.getElementById("god-mode-bar");
const replayBarEl = document.getElementById("replay-bar");
const btnRelationshipsEl = document.getElementById("btn-relationships");
const btnMetricsEl = document.getElementById("btn-metrics");
const btnReplayEl = document.getElementById("btn-replay");
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
let lastLiveTick: TickMessage | null = null;

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
  isReplay = false,
): void {
  if (simTimeEl !== null) {
    const stateLabel = isReplay
      ? "Replay"
      : state.running
        ? `${state.speed}x`
        : "Paused";
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
    if (!replayController.isActive()) {
      updateClockDisplay(state, false);
    }
  },
});

const agentInspector = new AgentInspector(agentInspectorEl, {
  onClose: () => {
    villageScene.setSelectedAgent(null);
    updateChipActiveStates(null);
    stageEl?.classList.remove("inspector-open");
  },
});

const relationshipGraph = new RelationshipGraphModal(relationshipPanelEl, {
  onSelectAgent: (agentId) => {
    selectAgent(agentId);
  },
  onClose: () => {
    syncToolButtons();
  },
});

const metricsDashboard = new MetricsDashboardPanel(metricsPanelEl, {
  onClose: () => {
    syncToolButtons();
  },
});

function applyTickToUi(
  tickMsg: TickMessage,
  immediate: boolean,
  isReplay: boolean,
): void {
  villageScene.applyTick(tickMsg, { immediate });
  updateClockDisplay(tickMsg, isReplay);

  const selectedId = isReplay ? null : agentInspector.getSelectedAgentId();
  updateAgentChips(tickMsg, selectedId, selectAgent);

  if (!isReplay) {
    timeControls.sync({ running: tickMsg.running, speed: tickMsg.speed });
    agentInspector.applyTick(tickMsg);
  }
}

const replayController = new ReplayController(replayBarEl, {
  onEnter: () => {
    agentInspector.close();
    villageScene.setSelectedAgent(null);
    updateChipActiveStates(null);
    stageEl?.classList.remove("inspector-open");
    villageScene.resetTransientVisuals();
    timeControlsEl?.classList.add("hidden");
    godModeBarEl?.classList.add("hidden");
    activityFeed.setModeLabel("Replay Activity");
    activityFeed.clear("Replay active — press Play or scrub timeline...");
    syncToolButtons();
  },
  onResetTimeline: () => {
    villageScene.resetTransientVisuals();
    activityFeed.clear("Replay position jumped...");
  },
  onApplyTick: (msg, immediate) => {
    applyTickToUi(msg, immediate, true);
  },
  onApplyDialogue: (msg) => {
    villageScene.showDialogue(msg);
    activityFeed.pushDialogue(msg);
  },
  onApplyEvent: (msg) => {
    villageScene.showEvent(msg);
    activityFeed.pushEvent(msg);
  },
  onApplyReflection: (msg) => {
    villageScene.showReflection(msg);
    activityFeed.pushReflection(msg);
  },
  onExit: () => {
    villageScene.resetTransientVisuals();
    villageScene.setSelectedAgent(agentInspector.getSelectedAgentId());
    activityFeed.setModeLabel("Live Activity");
    activityFeed.clear();
    timeControlsEl?.classList.remove("hidden");
    godModeBarEl?.classList.remove("hidden");
    syncToolButtons();
    if (lastLiveTick !== null) {
      applyTickToUi(lastLiveTick, true, false);
    }
  },
});

function syncToolButtons(): void {
  const relOpen = relationshipGraph.isOpen();
  const metricsOpen = metricsDashboard.isOpen();
  const replayOpen = replayController.isActive();

  if (btnRelationshipsEl !== null) {
    btnRelationshipsEl.classList.toggle("active", relOpen);
    btnRelationshipsEl.setAttribute("aria-pressed", String(relOpen));
  }

  if (btnMetricsEl !== null) {
    btnMetricsEl.classList.toggle("active", metricsOpen);
    btnMetricsEl.setAttribute("aria-pressed", String(metricsOpen));
  }

  if (btnReplayEl !== null) {
    btnReplayEl.classList.toggle("active", replayOpen);
    btnReplayEl.setAttribute("aria-pressed", String(replayOpen));
  }
}

function selectAgent(agentId: string): void {
  villageScene.setSelectedAgent(agentId);
  if (replayController.isActive()) {
    updateChipActiveStates(null);
    return;
  }

  updateChipActiveStates(agentId);
  void agentInspector.open(agentId);
  stageEl?.classList.toggle(
    "inspector-open",
    agentInspector.getSelectedAgentId() !== null,
  );
}

villageScene.setOnAgentSelect((agentId) => {
  selectAgent(agentId);
});

const handleRelationshipsClick = (): void => {
  if (relationshipGraph.isOpen()) {
    relationshipGraph.close();
    return;
  }
  metricsDashboard.close();
  void relationshipGraph.open();
  syncToolButtons();
};

const handleMetricsClick = (): void => {
  if (metricsDashboard.isOpen()) {
    metricsDashboard.close();
    return;
  }
  relationshipGraph.close();
  void metricsDashboard.open();
  syncToolButtons();
};

const handleReplayClick = (): void => {
  if (replayController.isActive()) {
    replayController.exit();
    return;
  }
  void replayController.open();
  syncToolButtons();
};

btnRelationshipsEl?.addEventListener("click", handleRelationshipsClick);
btnMetricsEl?.addEventListener("click", handleMetricsClick);
btnReplayEl?.addEventListener("click", handleReplayClick);

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
  if (event.key !== "Escape" || isTextInputFocused()) {
    return;
  }
  if (relationshipGraph.isOpen()) {
    relationshipGraph.close();
    return;
  }
  if (metricsDashboard.isOpen()) {
    metricsDashboard.close();
    return;
  }
  if (agentInspector.getSelectedAgentId() !== null) {
    agentInspector.close();
  }
};
window.addEventListener("keydown", handleWindowKeyDown);

const wsClient = new VillageWsClient({
  onStatusChange: (status) => {
    updateConnectionStatus(status);
  },
  onTick: (tickMsg) => {
    lastLiveTick = tickMsg;
    if (replayController.isActive()) {
      timeControls.sync({ running: tickMsg.running, speed: tickMsg.speed });
      return;
    }
    applyTickToUi(tickMsg, false, false);
  },
  onDialogue: (dialogueMsg) => {
    relationshipGraph.handleDialogue();
    if (replayController.isActive()) {
      return;
    }
    villageScene.showDialogue(dialogueMsg);
    activityFeed.pushDialogue(dialogueMsg);
    agentInspector.handleDialogue(dialogueMsg);
  },
  onEvent: (eventMsg) => {
    if (replayController.isActive()) {
      return;
    }
    villageScene.showEvent(eventMsg);
    activityFeed.pushEvent(eventMsg);
  },
  onReflection: (reflectionMsg) => {
    if (replayController.isActive()) {
      return;
    }
    villageScene.showReflection(reflectionMsg);
    activityFeed.pushReflection(reflectionMsg);
    agentInspector.handleReflection(reflectionMsg);
  },
  onMetrics: (metricsMsg) => {
    metricsDashboard.applyMetrics(metricsMsg);
  },
});

wsClient.connect();

window.addEventListener("beforeunload", () => {
  window.removeEventListener("keydown", handleWindowKeyDown);
  btnRelationshipsEl?.removeEventListener("click", handleRelationshipsClick);
  btnMetricsEl?.removeEventListener("click", handleMetricsClick);
  btnReplayEl?.removeEventListener("click", handleReplayClick);
  unmountEventInjector();
  timeControls.destroy();
  agentInspector.destroy();
  relationshipGraph.destroy();
  metricsDashboard.destroy();
  replayController.destroy();
  agentChipCache.clear();
  wsClient.disconnect();
  game.destroy(true);
});
