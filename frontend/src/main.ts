import Phaser from "phaser";
import { VillageWsClient } from "./net/wsClient";
import { VillageScene } from "./scenes/VillageScene";
import type { TickMessage, WsConnectionState } from "./types/sim";
import { ActivityFeed } from "./ui/activityFeed";
import { mountEventInjector } from "./ui/eventInjector";

const statusBadgeEl = document.getElementById("ws-status");
const simTimeEl = document.getElementById("sim-time");
const simTickEl = document.getElementById("sim-tick");
const agentsBarEl = document.getElementById("agents-bar");
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

function updateConnectionStatus(status: WsConnectionState): void {
  if (statusBadgeEl === null) {
    return;
  }
  statusBadgeEl.className = `status-pill ${status}`;
  statusBadgeEl.textContent = STATUS_LABELS[status];
}

function updateHud(tickMsg: TickMessage): void {
  if (simTimeEl !== null) {
    const stateLabel = tickMsg.running ? `${tickMsg.speed}x` : "Paused";
    simTimeEl.textContent = `Day ${tickMsg.day} · ${tickMsg.sim_time} · ${stateLabel}`;
  }

  if (simTickEl !== null) {
    simTickEl.textContent = `Tick ${tickMsg.tick}`;
  }

  if (agentsBarEl !== null) {
    const chips = tickMsg.agents.map((agent) => {
      const chip = document.createElement("span");
      chip.className = "agent-chip";

      const nameEl = document.createElement("strong");
      nameEl.textContent = agent.name;

      const metaEl = document.createElement("span");
      metaEl.className = "agent-meta";
      metaEl.textContent = ` · ${agent.current_action} (${agent.x}, ${agent.y})`;

      chip.append(nameEl, metaEl);
      return chip;
    });
    agentsBarEl.replaceChildren(...chips);
  }
}

const villageScene = new VillageScene();
const activityFeed = new ActivityFeed(activityFeedEl);

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

const wsClient = new VillageWsClient({
  onStatusChange: (status) => {
    updateConnectionStatus(status);
  },
  onTick: (tickMsg) => {
    villageScene.applyTick(tickMsg);
    updateHud(tickMsg);
  },
  onDialogue: (dialogueMsg) => {
    villageScene.showDialogue(dialogueMsg);
    activityFeed.pushDialogue(dialogueMsg);
  },
  onEvent: (eventMsg) => {
    villageScene.showEvent(eventMsg);
    activityFeed.pushEvent(eventMsg);
  },
});

wsClient.connect();

window.addEventListener("beforeunload", () => {
  unmountEventInjector();
  wsClient.disconnect();
  game.destroy(true);
});
