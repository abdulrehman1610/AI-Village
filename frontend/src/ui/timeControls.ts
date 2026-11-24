import { pauseSim, setSimSpeed, startSim } from "../net/apiClient";
import type { SimControlResponse, SimSpeed } from "../types/sim";

export interface TimeControlsOptions {
  onStateChange?: (state: SimControlResponse) => void;
}

const SPEED_OPTIONS: readonly SimSpeed[] = [1, 4, 16];

/** HUD playback controls synced to authoritative server running/speed state. */
export class TimeControls {
  private readonly containerEl: HTMLElement | null;
  private readonly options: TimeControlsOptions;
  private readonly toggleBtn: HTMLButtonElement | null;
  private readonly speedButtons = new Map<SimSpeed, HTMLButtonElement>();
  private readonly errorEl: HTMLSpanElement | null;

  private running = false;
  private speed = 1;
  private pending = false;
  private disposed = false;

  private readonly handleToggleClick = (): void => {
    void this.togglePlayPause();
  };

  private readonly speedClickHandlers = new Map<SimSpeed, () => void>();

  constructor(
    containerEl: HTMLElement | null,
    options: TimeControlsOptions = {},
  ) {
    this.containerEl = containerEl;
    this.options = options;

    if (containerEl === null) {
      this.toggleBtn = null;
      this.errorEl = null;
      return;
    }

    const toggleBtn = document.createElement("button");
    toggleBtn.id = "sim-toggle-btn";
    toggleBtn.type = "button";
    toggleBtn.className = "sim-btn sim-toggle-btn";
    toggleBtn.addEventListener("click", this.handleToggleClick);
    this.toggleBtn = toggleBtn;

    const speedGroup = document.createElement("div");
    speedGroup.className = "sim-speed-group";
    speedGroup.setAttribute("role", "group");
    speedGroup.setAttribute("aria-label", "Simulation speed");

    for (const option of SPEED_OPTIONS) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "sim-btn sim-speed-btn";
      btn.dataset.speed = String(option);
      btn.textContent = `${option}x`;

      const handler = (): void => {
        void this.changeSpeed(option);
      };
      btn.addEventListener("click", handler);
      this.speedClickHandlers.set(option, handler);
      this.speedButtons.set(option, btn);
      speedGroup.appendChild(btn);
    }

    const errorEl = document.createElement("span");
    errorEl.className = "sim-control-error";
    errorEl.setAttribute("role", "status");
    errorEl.setAttribute("aria-live", "polite");
    this.errorEl = errorEl;

    containerEl.replaceChildren(toggleBtn, speedGroup, errorEl);
    this.renderState();
  }

  /** Synchronize button labels and active speed pill with server state. */
  public sync(state: { running: boolean; speed: number }): void {
    if (this.disposed) {
      return;
    }
    this.running = state.running;
    this.speed = state.speed;
    this.renderState();
  }

  /** Remove DOM listeners and prevent further updates after teardown. */
  public destroy(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.toggleBtn?.removeEventListener("click", this.handleToggleClick);
    for (const [option, btn] of this.speedButtons.entries()) {
      const handler = this.speedClickHandlers.get(option);
      if (handler !== undefined) {
        btn.removeEventListener("click", handler);
      }
    }
    this.speedClickHandlers.clear();
    this.speedButtons.clear();
    this.containerEl?.replaceChildren();
  }

  private async togglePlayPause(): Promise<void> {
    if (this.disposed || this.pending) {
      return;
    }
    this.pending = true;
    this.clearError();
    this.renderState();

    try {
      const response = this.running ? await pauseSim() : await startSim();
      if (this.disposed) {
        return;
      }
      this.running = response.running;
      this.speed = response.speed;
      this.options.onStateChange?.(response);
    } catch (err: unknown) {
      if (!this.disposed) {
        const message =
          err instanceof Error
            ? err.message
            : "Failed to update playback state.";
        this.setError(message);
      }
    } finally {
      this.pending = false;
      if (!this.disposed) {
        this.renderState();
      }
    }
  }

  private async changeSpeed(nextSpeed: SimSpeed): Promise<void> {
    if (this.disposed || this.pending) {
      return;
    }
    this.pending = true;
    this.clearError();
    this.renderState();

    try {
      const response = await setSimSpeed(nextSpeed);
      if (this.disposed) {
        return;
      }
      this.running = response.running;
      this.speed = response.speed;
      this.options.onStateChange?.(response);
    } catch (err: unknown) {
      if (!this.disposed) {
        const message =
          err instanceof Error
            ? err.message
            : "Failed to change simulation speed.";
        this.setError(message);
      }
    } finally {
      this.pending = false;
      if (!this.disposed) {
        this.renderState();
      }
    }
  }

  private renderState(): void {
    if (this.toggleBtn !== null) {
      this.toggleBtn.textContent = this.running ? "Pause" : "Play";
      this.toggleBtn.classList.toggle("active", this.running);
      this.toggleBtn.setAttribute("aria-pressed", String(this.running));
      this.toggleBtn.setAttribute(
        "aria-label",
        this.running ? "Pause simulation" : "Play simulation",
      );
      this.toggleBtn.disabled = this.pending;
    }

    for (const [option, btn] of this.speedButtons.entries()) {
      const isActive = this.speed === option;
      btn.classList.toggle("active", isActive);
      btn.setAttribute("aria-pressed", String(isActive));
      btn.disabled = this.pending;
    }
  }

  private setError(message: string): void {
    if (this.errorEl === null) {
      return;
    }
    this.errorEl.textContent = message;
    this.errorEl.classList.add("visible");
  }

  private clearError(): void {
    if (this.errorEl === null) {
      return;
    }
    this.errorEl.textContent = "";
    this.errorEl.classList.remove("visible");
  }
}
