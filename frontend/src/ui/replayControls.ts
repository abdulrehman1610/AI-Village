import { fetchReplayDay, fetchReplayDays } from "../net/apiClient";
import type {
  DialogueMessage,
  EventMessage,
  ReflectionMessage,
  ReplayDaySummary,
  ReplayFrame,
  TickMessage,
} from "../types/sim";

export interface ReplayControllerOptions {
  onEnter?: () => void;
  onExit?: () => void;
  onResetTimeline?: () => void;
  onApplyTick: (msg: TickMessage, immediate: boolean) => void;
  onApplyDialogue: (msg: DialogueMessage) => void;
  onApplyEvent: (msg: EventMessage) => void;
  onApplyReflection: (msg: ReflectionMessage) => void;
}

type ReplaySpeed = 1 | 4 | 16;

const REPLAY_SPEEDS: readonly ReplaySpeed[] = [1, 4, 16];
const REPLAY_DELAY_MS: Record<ReplaySpeed, number> = {
  1: 1000,
  4: 250,
  16: 63,
};

interface IndexedReplayTimeline {
  tickOrder: number[];
  exactTicks: Map<number, TickMessage>;
  tickSnapshots: Map<number, TickMessage>;
  eventsByTick: Map<number, ReplayFrame[]>;
}

function indexReplayFrames(
  frames: readonly ReplayFrame[],
): IndexedReplayTimeline {
  const tickSet = new Set<number>();
  const exactTicks = new Map<number, TickMessage>();
  const eventsByTick = new Map<number, ReplayFrame[]>();
  let firstTickMsg: TickMessage | null = null;

  for (const frame of frames) {
    tickSet.add(frame.tick);
    if (frame.type === "tick") {
      if (firstTickMsg === null) {
        firstTickMsg = frame;
      }
      exactTicks.set(frame.tick, frame);
    } else {
      const bucket = eventsByTick.get(frame.tick);
      if (bucket === undefined) {
        eventsByTick.set(frame.tick, [frame]);
      } else {
        bucket.push(frame);
      }
    }
  }

  const tickOrder = Array.from(tickSet).sort((a, b) => a - b);
  const tickSnapshots = new Map<number, TickMessage>();
  let latestTick: TickMessage | null = null;

  for (const tick of tickOrder) {
    const exact = exactTicks.get(tick);
    if (exact !== undefined) {
      latestTick = exact;
    }
    const snapshot = latestTick ?? firstTickMsg;
    if (snapshot !== null) {
      tickSnapshots.set(tick, snapshot);
    }
  }

  return { tickOrder, exactTicks, tickSnapshots, eventsByTick };
}

/** Client-side JSONL Day Replay controller without mutating server /sim/* state. */
export class ReplayController {
  private readonly containerEl: HTMLElement | null;
  private readonly options: ReplayControllerOptions;

  private readonly daySelectEl: HTMLSelectElement | null;
  private readonly refreshBtnEl: HTMLButtonElement | null;
  private readonly playBtnEl: HTMLButtonElement | null;
  private readonly speedButtons = new Map<ReplaySpeed, HTMLButtonElement>();
  private readonly speedClickHandlers = new Map<ReplaySpeed, () => void>();
  private readonly scrubberEl: HTMLInputElement | null;
  private readonly readoutEl: HTMLSpanElement | null;
  private readonly statusEl: HTMLSpanElement | null;
  private readonly exitBtnEl: HTMLButtonElement | null;

  private active = false;
  private disposed = false;
  private playing = false;
  private loading = false;
  private refreshingDays = false;
  private playbackSpeed: ReplaySpeed = 1;
  private requestSeq = 0;
  private playbackTimerId: number | null = null;

  private days: ReplayDaySummary[] = [];
  private selectedDay: number | null = null;
  private tickOrder: number[] = [];
  private exactTicks = new Map<number, TickMessage>();
  private tickSnapshots = new Map<number, TickMessage>();
  private eventsByTick = new Map<number, ReplayFrame[]>();
  private currentIndex = 0;

  private readonly handleDayChange = (): void => {
    if (this.disposed || !this.active || this.daySelectEl === null) {
      return;
    }
    const parsedDay = Number.parseInt(this.daySelectEl.value, 10);
    if (!Number.isInteger(parsedDay) || parsedDay < 1) {
      return;
    }
    void this.loadDay(parsedDay);
  };

  private readonly handleRefreshClick = (): void => {
    if (this.disposed || !this.active) {
      return;
    }
    void this.refreshDays();
  };

  private readonly handlePlayClick = (): void => {
    if (this.disposed || !this.active || this.loading) {
      return;
    }
    this.togglePlayback();
  };

  private readonly handleScrubberInput = (): void => {
    if (this.disposed || !this.active || this.scrubberEl === null) {
      return;
    }
    const nextIdx = Number.parseInt(this.scrubberEl.value, 10);
    if (Number.isFinite(nextIdx)) {
      this.scrubToIndex(nextIdx);
    }
  };

  private readonly handleScrubberChange = (): void => {
    if (this.disposed || !this.active || this.scrubberEl === null) {
      return;
    }
    const nextIdx = Number.parseInt(this.scrubberEl.value, 10);
    if (!Number.isFinite(nextIdx)) {
      return;
    }
    if (this.playing || nextIdx !== this.currentIndex) {
      this.scrubToIndex(nextIdx);
    }
  };

  private readonly handleExitClick = (): void => {
    this.exit();
  };

  constructor(
    containerEl: HTMLElement | null,
    options: ReplayControllerOptions,
  ) {
    this.containerEl = containerEl;
    this.options = options;

    if (containerEl === null) {
      this.daySelectEl = null;
      this.refreshBtnEl = null;
      this.playBtnEl = null;
      this.scrubberEl = null;
      this.readoutEl = null;
      this.statusEl = null;
      this.exitBtnEl = null;
      return;
    }

    const badgeEl = document.createElement("span");
    badgeEl.className = "replay-badge";
    badgeEl.textContent = "REPLAY MODE";

    const dayGroup = document.createElement("div");
    dayGroup.className = "replay-day-group";

    const daySelectEl = document.createElement("select");
    daySelectEl.className = "replay-day-select";
    daySelectEl.setAttribute("aria-label", "Recorded simulation day");
    daySelectEl.addEventListener("change", this.handleDayChange);
    this.daySelectEl = daySelectEl;

    const refreshBtnEl = document.createElement("button");
    refreshBtnEl.type = "button";
    refreshBtnEl.className = "sim-btn replay-refresh-btn";
    refreshBtnEl.textContent = "Refresh";
    refreshBtnEl.setAttribute("aria-label", "Refresh recorded replay days");
    refreshBtnEl.addEventListener("click", this.handleRefreshClick);
    this.refreshBtnEl = refreshBtnEl;

    dayGroup.append(daySelectEl, refreshBtnEl);

    const transportGroup = document.createElement("div");
    transportGroup.className = "replay-transport-group";

    const playBtnEl = document.createElement("button");
    playBtnEl.type = "button";
    playBtnEl.className = "sim-btn replay-play-btn";
    playBtnEl.addEventListener("click", this.handlePlayClick);
    this.playBtnEl = playBtnEl;

    const speedGroup = document.createElement("div");
    speedGroup.className = "sim-speed-group";
    speedGroup.setAttribute("role", "group");
    speedGroup.setAttribute("aria-label", "Replay playback speed");

    for (const speed of REPLAY_SPEEDS) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "sim-btn replay-speed-btn";
      btn.dataset.speed = String(speed);
      btn.textContent = `${speed}x`;

      const handler = (): void => {
        this.setSpeed(speed);
      };
      btn.addEventListener("click", handler);
      this.speedClickHandlers.set(speed, handler);
      this.speedButtons.set(speed, btn);
      speedGroup.appendChild(btn);
    }

    transportGroup.append(playBtnEl, speedGroup);

    const timelineGroup = document.createElement("div");
    timelineGroup.className = "replay-timeline-group";

    const scrubberEl = document.createElement("input");
    scrubberEl.type = "range";
    scrubberEl.className = "replay-scrubber";
    scrubberEl.min = "0";
    scrubberEl.max = "0";
    scrubberEl.value = "0";
    scrubberEl.step = "1";
    scrubberEl.setAttribute("aria-label", "Replay timeline scrubber");
    scrubberEl.addEventListener("input", this.handleScrubberInput);
    scrubberEl.addEventListener("change", this.handleScrubberChange);
    this.scrubberEl = scrubberEl;

    const readoutEl = document.createElement("span");
    readoutEl.className = "replay-readout";
    readoutEl.textContent = "Tick 0 / 0 · --:--";
    this.readoutEl = readoutEl;

    timelineGroup.append(scrubberEl, readoutEl);

    const metaGroup = document.createElement("div");
    metaGroup.className = "replay-meta-group";

    const statusEl = document.createElement("span");
    statusEl.className = "replay-status";
    statusEl.setAttribute("role", "status");
    statusEl.setAttribute("aria-live", "polite");
    this.statusEl = statusEl;

    const exitBtnEl = document.createElement("button");
    exitBtnEl.type = "button";
    exitBtnEl.className = "sim-btn replay-exit-btn";
    exitBtnEl.textContent = "Exit to Live";
    exitBtnEl.addEventListener("click", this.handleExitClick);
    this.exitBtnEl = exitBtnEl;

    metaGroup.append(statusEl, exitBtnEl);

    containerEl.replaceChildren(
      badgeEl,
      dayGroup,
      transportGroup,
      timelineGroup,
      metaGroup,
    );
    containerEl.classList.add("hidden");

    this.populateDaySelect();
    this.renderControls();
  }

  /** Return whether Replay Mode is currently active. */
  public isActive(): boolean {
    return !this.disposed && this.active;
  }

  /** Enter Replay Mode, load recorded days from GET /replay, and open the latest day. */
  public async open(): Promise<void> {
    if (this.disposed || this.containerEl === null) {
      return;
    }

    const wasActive = this.active;
    this.stopPlayback();
    this.active = true;
    this.containerEl.classList.remove("hidden");

    if (!wasActive) {
      this.options.onEnter?.();
    }

    await this.refreshDays();
  }

  /** Exit Replay Mode cleanly, stop playback timers, and restore live callbacks. */
  public exit(): void {
    if (this.disposed) {
      return;
    }

    const wasActive = this.active;
    this.stopPlayback();
    this.requestSeq += 1;
    this.loading = false;
    this.refreshingDays = false;
    this.active = false;
    this.selectedDay = null;
    this.clearStatus();

    if (this.containerEl !== null) {
      this.containerEl.classList.add("hidden");
    }
    this.renderControls();

    if (wasActive) {
      this.options.onExit?.();
    }
  }

  /** Remove all DOM listeners, cancel pending timers, and dispose resources. */
  public destroy(): void {
    if (this.disposed) {
      return;
    }

    this.disposed = true;
    this.stopPlayback();
    this.requestSeq += 1;
    this.active = false;
    this.loading = false;
    this.refreshingDays = false;

    this.daySelectEl?.removeEventListener("change", this.handleDayChange);
    this.refreshBtnEl?.removeEventListener("click", this.handleRefreshClick);
    this.playBtnEl?.removeEventListener("click", this.handlePlayClick);
    this.scrubberEl?.removeEventListener("input", this.handleScrubberInput);
    this.scrubberEl?.removeEventListener("change", this.handleScrubberChange);
    this.exitBtnEl?.removeEventListener("click", this.handleExitClick);

    for (const [speed, btn] of this.speedButtons.entries()) {
      const handler = this.speedClickHandlers.get(speed);
      if (handler !== undefined) {
        btn.removeEventListener("click", handler);
      }
    }
    this.speedClickHandlers.clear();
    this.speedButtons.clear();

    this.days = [];
    this.tickOrder = [];
    this.exactTicks.clear();
    this.tickSnapshots.clear();
    this.eventsByTick.clear();

    if (this.containerEl !== null) {
      this.containerEl.classList.add("hidden");
      this.containerEl.replaceChildren();
    }
  }

  private async refreshDays(): Promise<void> {
    if (this.disposed || !this.active || this.containerEl === null) {
      return;
    }

    this.stopPlayback();
    const seq = ++this.requestSeq;
    this.refreshingDays = true;
    this.loading = true;
    this.setStatus("Loading recorded days...", false);
    this.renderControls();

    try {
      const response = await fetchReplayDays();
      if (this.disposed || !this.active || seq !== this.requestSeq) {
        return;
      }

      this.days = [...response.days].sort((a, b) => a.day - b.day);
      this.populateDaySelect();

      if (this.days.length === 0) {
        this.selectedDay = null;
        this.loading = false;
        this.refreshingDays = false;
        this.clearTimeline();
        this.options.onResetTimeline?.();
        this.setStatus("No replay logs recorded yet", false);
        this.renderControls();
        return;
      }

      const hasExistingSelection =
        this.selectedDay !== null &&
        this.days.some((item) => item.day === this.selectedDay);
      const targetDay = hasExistingSelection
        ? (this.selectedDay as number)
        : this.days[this.days.length - 1].day;

      this.refreshingDays = false;
      await this.loadDay(targetDay);
    } catch (err: unknown) {
      if (this.disposed || !this.active || seq !== this.requestSeq) {
        return;
      }
      this.loading = false;
      this.refreshingDays = false;
      const message =
        err instanceof Error ? err.message : "Failed to load replay days.";
      this.setStatus(message, true);
      this.renderControls();
    }
  }

  private async loadDay(day: number): Promise<void> {
    if (this.disposed || !this.active || this.containerEl === null) {
      return;
    }

    this.stopPlayback();
    const seq = ++this.requestSeq;
    this.selectedDay = day;
    if (this.daySelectEl !== null) {
      this.daySelectEl.value = String(day);
    }

    this.loading = true;
    this.setStatus(`Loading Day ${day}...`, false);
    this.renderControls();

    try {
      const log = await fetchReplayDay(day);
      if (this.disposed || !this.active || seq !== this.requestSeq) {
        return;
      }

      const indexed = indexReplayFrames(log.frames);
      this.tickOrder = indexed.tickOrder;
      this.exactTicks = indexed.exactTicks;
      this.tickSnapshots = indexed.tickSnapshots;
      this.eventsByTick = indexed.eventsByTick;
      this.currentIndex = 0;
      this.loading = false;

      if (this.tickOrder.length === 0) {
        this.options.onResetTimeline?.();
        this.clearStatus();
        this.setStatus(`Day ${day} has no recorded ticks`, false);
        this.updateScrubberAndReadout();
        this.renderControls();
        return;
      }

      this.clearStatus();
      this.scrubToIndex(0);
      this.renderControls();
    } catch (err: unknown) {
      if (this.disposed || !this.active || seq !== this.requestSeq) {
        return;
      }
      this.loading = false;
      this.clearTimeline();
      this.options.onResetTimeline?.();
      const message =
        err instanceof Error
          ? err.message
          : `Failed to load replay for Day ${day}.`;
      this.setStatus(message, true);
      this.renderControls();
    }
  }

  private togglePlayback(): void {
    if (this.tickOrder.length <= 1) {
      return;
    }

    if (this.playing) {
      this.stopPlayback();
      return;
    }

    if (this.currentIndex >= this.tickOrder.length - 1) {
      this.scrubToIndex(0);
    }

    this.playing = true;
    this.renderControls();
    this.scheduleNextStep();
  }

  private setSpeed(speed: ReplaySpeed): void {
    if (this.disposed) {
      return;
    }
    this.playbackSpeed = speed;
    this.renderControls();
    if (this.playing) {
      this.scheduleNextStep();
    }
  }

  private scheduleNextStep(): void {
    this.clearPlaybackTimer();
    if (
      this.disposed ||
      !this.active ||
      !this.playing ||
      this.currentIndex >= this.tickOrder.length - 1
    ) {
      return;
    }
    const delayMs = REPLAY_DELAY_MS[this.playbackSpeed];
    this.playbackTimerId = window.setTimeout(() => {
      this.playbackTimerId = null;
      this.stepForward();
    }, delayMs);
  }

  private stepForward(): void {
    if (
      this.disposed ||
      !this.active ||
      !this.playing ||
      this.tickOrder.length === 0
    ) {
      return;
    }

    if (this.currentIndex >= this.tickOrder.length - 1) {
      this.stopPlayback();
      return;
    }

    this.currentIndex += 1;
    this.updateScrubberAndReadout();
    this.applyIndex(this.currentIndex, false);

    if (this.currentIndex >= this.tickOrder.length - 1) {
      this.stopPlayback();
      return;
    }

    this.scheduleNextStep();
  }

  private scrubToIndex(idx: number): void {
    if (this.disposed || !this.active || this.tickOrder.length === 0) {
      return;
    }

    this.stopPlayback();
    const clamped = Math.max(
      0,
      Math.min(this.tickOrder.length - 1, Math.trunc(idx)),
    );
    this.currentIndex = clamped;
    this.updateScrubberAndReadout();
    this.options.onResetTimeline?.();
    this.applyIndex(clamped, true);
  }

  private applyIndex(idx: number, immediate: boolean): void {
    const tick = this.tickOrder[idx];
    if (tick === undefined) {
      return;
    }

    const events = this.eventsByTick.get(tick) ?? [];
    const exactTick = this.exactTicks.get(tick);
    const baseSnapshot = exactTick ?? this.tickSnapshots.get(tick);
    if (baseSnapshot !== undefined) {
      const resolvedSimTime =
        exactTick?.sim_time ?? events[0]?.sim_time ?? baseSnapshot.sim_time;
      const tickMsg: TickMessage =
        exactTick !== undefined &&
        exactTick.speed === this.playbackSpeed &&
        exactTick.running === this.playing
          ? exactTick
          : {
              ...baseSnapshot,
              tick,
              sim_time: resolvedSimTime,
              running: this.playing,
              speed: this.playbackSpeed,
            };
      this.options.onApplyTick(tickMsg, immediate);
    }

    for (const frame of events) {
      switch (frame.type) {
        case "dialogue":
          this.options.onApplyDialogue(frame);
          break;
        case "event":
          this.options.onApplyEvent(frame);
          break;
        case "reflection":
          this.options.onApplyReflection(frame);
          break;
        case "tick":
          break;
      }
    }
  }

  private stopPlayback(): void {
    this.clearPlaybackTimer();
    if (this.playing) {
      this.playing = false;
      this.renderControls();
    }
  }

  private clearPlaybackTimer(): void {
    if (this.playbackTimerId !== null) {
      window.clearTimeout(this.playbackTimerId);
      this.playbackTimerId = null;
    }
  }

  private clearTimeline(): void {
    this.tickOrder = [];
    this.exactTicks.clear();
    this.tickSnapshots.clear();
    this.eventsByTick.clear();
    this.currentIndex = 0;
    this.updateScrubberAndReadout();
  }

  private populateDaySelect(): void {
    if (this.daySelectEl === null) {
      return;
    }

    if (this.days.length === 0) {
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "No days recorded";
      this.daySelectEl.replaceChildren(placeholder);
      this.daySelectEl.disabled = true;
      return;
    }

    const options: HTMLOptionElement[] = [];
    for (const summary of this.days) {
      const opt = document.createElement("option");
      opt.value = String(summary.day);
      const tickLabel = summary.tick_count === 1 ? "tick" : "ticks";
      opt.textContent = `Day ${summary.day} (${summary.tick_count} ${tickLabel})`;
      options.push(opt);
    }
    this.daySelectEl.replaceChildren(...options);
    this.daySelectEl.disabled = false;

    if (
      this.selectedDay !== null &&
      this.days.some((item) => item.day === this.selectedDay)
    ) {
      this.daySelectEl.value = String(this.selectedDay);
    }
  }

  private updateScrubberAndReadout(): void {
    const total = this.tickOrder.length;
    if (this.scrubberEl !== null) {
      this.scrubberEl.min = "0";
      this.scrubberEl.max = String(Math.max(0, total - 1));
      this.scrubberEl.value = String(
        total > 0 ? Math.min(this.currentIndex, total - 1) : 0,
      );
      this.scrubberEl.disabled = this.loading || total <= 1;
    }

    if (this.readoutEl !== null) {
      if (total === 0) {
        this.readoutEl.textContent = "Tick 0 / 0 · --:--";
      } else {
        const currentTick = this.tickOrder[this.currentIndex] ?? 0;
        const lastTick = this.tickOrder[total - 1] ?? currentTick;
        const exact = this.exactTicks.get(currentTick);
        const events = this.eventsByTick.get(currentTick);
        const snapshot = this.tickSnapshots.get(currentTick);
        const simTime =
          exact?.sim_time ??
          events?.[0]?.sim_time ??
          snapshot?.sim_time ??
          "--:--";
        this.readoutEl.textContent = `Tick ${currentTick} / ${lastTick} · ${simTime}`;
      }
    }
  }

  private renderControls(): void {
    const hasTimeline = this.tickOrder.length > 0;
    const canStep = !this.loading && this.tickOrder.length > 1;

    if (this.daySelectEl !== null) {
      this.daySelectEl.disabled = this.refreshingDays || this.days.length === 0;
    }

    if (this.refreshBtnEl !== null) {
      this.refreshBtnEl.disabled = this.refreshingDays;
    }

    if (this.playBtnEl !== null) {
      this.playBtnEl.textContent = this.playing ? "Pause" : "Play";
      this.playBtnEl.classList.toggle("active", this.playing);
      this.playBtnEl.setAttribute("aria-pressed", String(this.playing));
      this.playBtnEl.setAttribute(
        "aria-label",
        this.playing ? "Pause replay" : "Play replay",
      );
      this.playBtnEl.disabled = !canStep;
    }

    for (const [speed, btn] of this.speedButtons.entries()) {
      const isSelected = this.playbackSpeed === speed;
      btn.classList.toggle("active", isSelected);
      btn.setAttribute("aria-pressed", String(isSelected));
      btn.disabled = this.loading;
    }

    if (this.scrubberEl !== null) {
      this.scrubberEl.disabled = this.loading || !hasTimeline || this.tickOrder.length <= 1;
    }
  }

  private setStatus(message: string, isError: boolean): void {
    if (this.statusEl === null) {
      return;
    }
    this.statusEl.textContent = message;
    this.statusEl.classList.toggle("error", isError);
    this.statusEl.classList.toggle("visible", message.length > 0);
  }

  private clearStatus(): void {
    this.setStatus("", false);
  }
}
