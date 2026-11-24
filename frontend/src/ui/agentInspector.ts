import { fetchAgentDetail } from "../net/apiClient";
import type {
  AgentDetail,
  AgentMemoryItem,
  AgentPlanBlock,
  AgentRelationshipItem,
  DialogueMessage,
  ReflectionMessage,
  TickMessage,
} from "../types/sim";

export interface AgentInspectorOptions {
  onClose?: () => void;
}

interface LiveStatusRefs {
  moodPillEl: HTMLSpanElement;
  targetEl: HTMLElement;
  coordsEl: HTMLElement;
  actionEl: HTMLElement;
  refreshBtnEl: HTMLButtonElement;
}

const REFRESH_INTERVAL_MS = 3000;

function formatHour(hour: number): string {
  return `${String(hour).padStart(2, "0")}:00`;
}

function formatAffinity(affinity: number): string {
  const prefix = affinity > 0 ? "+" : "";
  return `${prefix}${affinity.toFixed(2)}`;
}

function createTextElement<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className: string,
  text: string,
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  if (className) {
    el.className = className;
  }
  el.textContent = text;
  return el;
}

/** Left-docked inspector panel displaying live agent state without innerHTML. */
export class AgentInspector {
  private readonly containerEl: HTMLElement | null;
  private readonly options: AgentInspectorOptions;

  private selectedAgentId: string | null = null;
  private detail: AgentDetail | null = null;
  private liveRefs: LiveStatusRefs | null = null;
  private requestSeq = 0;
  private inFlight = false;
  private lastFetchAt = 0;
  private disposed = false;

  constructor(
    containerEl: HTMLElement | null,
    options: AgentInspectorOptions = {},
  ) {
    this.containerEl = containerEl;
    this.options = options;
  }

  /** Return the currently inspected agent id, or null when closed. */
  public getSelectedAgentId(): string | null {
    return this.selectedAgentId;
  }

  /** Open the inspector for an agent and fetch authoritative detail from REST. */
  public async open(agentId: string): Promise<void> {
    if (this.disposed || this.containerEl === null) {
      return;
    }

    const isSameAgent = this.selectedAgentId === agentId && this.detail !== null;
    this.selectedAgentId = agentId;
    this.containerEl.classList.remove("hidden");

    if (!isSameAgent) {
      this.detail = null;
      this.liveRefs = null;
      this.renderLoadingState(agentId);
    }

    await this.loadDetail(agentId);
  }

  /** Close the inspector drawer and notify listeners. */
  public close(): void {
    const wasOpen =
      this.selectedAgentId !== null ||
      (this.containerEl !== null &&
        !this.containerEl.classList.contains("hidden"));

    this.requestSeq += 1;
    this.selectedAgentId = null;
    this.detail = null;
    this.liveRefs = null;
    this.inFlight = false;

    if (this.containerEl !== null) {
      this.containerEl.classList.add("hidden");
      this.containerEl.replaceChildren();
    }

    if (wasOpen) {
      this.options.onClose?.();
    }
  }

  /** Re-fetch full details for the currently selected agent. */
  public async refresh(): Promise<void> {
    if (this.disposed || this.selectedAgentId === null) {
      return;
    }
    await this.loadDetail(this.selectedAgentId);
  }

  /** Patch live movement/action/mood fields on ticks and throttled-refresh when running. */
  public applyTick(tickMsg: TickMessage): void {
    if (this.disposed || this.selectedAgentId === null) {
      return;
    }

    const snap = tickMsg.agents.find((a) => a.id === this.selectedAgentId);
    if (snap !== undefined) {
      if (this.detail !== null) {
        this.detail.x = snap.x;
        this.detail.y = snap.y;
        this.detail.target_location = snap.target_location;
        this.detail.current_action = snap.current_action;
        if (snap.mood !== undefined) {
          this.detail.mood = snap.mood;
        }
      }

      if (this.liveRefs !== null) {
        this.liveRefs.coordsEl.textContent = `(${snap.x}, ${snap.y})`;
        this.liveRefs.targetEl.textContent = snap.target_location ?? "None";
        this.liveRefs.actionEl.textContent = snap.current_action;
        if (snap.mood !== undefined) {
          this.liveRefs.moodPillEl.textContent = snap.mood;
        }
      }
    }

    if (
      tickMsg.running &&
      !this.inFlight &&
      Date.now() - this.lastFetchAt >= REFRESH_INTERVAL_MS
    ) {
      void this.refresh();
    }
  }

  /** Refresh immediately when a live dialogue involves the inspected agent. */
  public handleDialogue(msg: DialogueMessage): void {
    if (
      this.disposed ||
      this.selectedAgentId === null ||
      !msg.participants.includes(this.selectedAgentId)
    ) {
      return;
    }
    void this.refresh();
  }

  /** Refresh immediately when the inspected agent synthesizes a reflection. */
  public handleReflection(msg: ReflectionMessage): void {
    if (this.disposed || this.selectedAgentId !== msg.agent_id) {
      return;
    }
    void this.refresh();
  }

  /** Tear down inspector state on page unload. */
  public destroy(): void {
    this.disposed = true;
    this.requestSeq += 1;
    this.selectedAgentId = null;
    this.detail = null;
    this.liveRefs = null;
    this.inFlight = false;
    if (this.containerEl !== null) {
      this.containerEl.classList.add("hidden");
      this.containerEl.replaceChildren();
    }
  }

  private async loadDetail(agentId: string): Promise<void> {
    if (this.disposed || this.containerEl === null) {
      return;
    }

    const seq = ++this.requestSeq;
    this.inFlight = true;
    if (this.liveRefs !== null) {
      this.liveRefs.refreshBtnEl.disabled = true;
    }

    try {
      const detail = await fetchAgentDetail(agentId);
      if (
        this.disposed ||
        seq !== this.requestSeq ||
        this.selectedAgentId !== agentId
      ) {
        return;
      }
      this.detail = detail;
      this.renderDetail(detail);
    } catch (err: unknown) {
      if (
        this.disposed ||
        seq !== this.requestSeq ||
        this.selectedAgentId !== agentId
      ) {
        return;
      }
      const message =
        err instanceof Error ? err.message : "Failed to load agent details.";
      this.renderErrorBanner(agentId, message);
    } finally {
      if (seq === this.requestSeq) {
        this.inFlight = false;
        this.lastFetchAt = Date.now();
        if (this.liveRefs !== null) {
          this.liveRefs.refreshBtnEl.disabled = false;
        }
      }
    }
  }

  private renderLoadingState(agentId: string): void {
    if (this.containerEl === null) {
      return;
    }

    const header = document.createElement("div");
    header.className = "inspector-header";

    const titleGroup = document.createElement("div");
    titleGroup.className = "inspector-title-group";
    titleGroup.append(
      createTextElement("h2", "inspector-name", agentId),
      createTextElement("div", "inspector-role", "Loading profile..."),
    );

    const actions = document.createElement("div");
    actions.className = "inspector-actions";
    actions.appendChild(this.createCloseButton());

    header.append(titleGroup, actions);

    const loadingCard = createTextElement(
      "div",
      "inspector-empty",
      "Fetching agent memories, plan, and relationships...",
    );

    this.containerEl.replaceChildren(header, loadingCard);
  }

  private renderErrorBanner(agentId: string, message: string): void {
    if (this.containerEl === null) {
      return;
    }

    const errorBox = document.createElement("div");
    errorBox.className = "inspector-error";

    const msgEl = createTextElement("span", "", message);
    const retryBtn = createTextElement(
      "button",
      "inspector-retry-btn",
      "Retry",
    );
    retryBtn.type = "button";
    retryBtn.addEventListener("click", () => {
      void this.loadDetail(agentId);
    });
    errorBox.append(msgEl, retryBtn);

    if (this.detail === null) {
      const header = document.createElement("div");
      header.className = "inspector-header";
      const titleGroup = document.createElement("div");
      titleGroup.className = "inspector-title-group";
      titleGroup.append(
        createTextElement("h2", "inspector-name", agentId),
        createTextElement("div", "inspector-role", "Inspector unavailable"),
      );
      const actions = document.createElement("div");
      actions.className = "inspector-actions";
      actions.appendChild(this.createCloseButton());
      header.append(titleGroup, actions);
      this.containerEl.replaceChildren(header, errorBox);
      return;
    }

    const existingError = this.containerEl.querySelector(".inspector-error");
    existingError?.remove();
    const firstCard = this.containerEl.querySelector(".inspector-card");
    if (firstCard !== null) {
      this.containerEl.insertBefore(errorBox, firstCard);
    } else {
      this.containerEl.appendChild(errorBox);
    }
  }

  private renderDetail(detail: AgentDetail): void {
    if (this.containerEl === null) {
      return;
    }

    const previousScrollTop = this.containerEl.scrollTop;

    const header = document.createElement("div");
    header.className = "inspector-header";

    const titleGroup = document.createElement("div");
    titleGroup.className = "inspector-title-group";

    const nameRow = document.createElement("div");
    nameRow.className = "inspector-name-row";
    const nameEl = createTextElement("h2", "inspector-name", detail.name);
    const moodPillEl = createTextElement("span", "mood-pill", detail.mood);
    nameRow.append(nameEl, moodPillEl);

    const roleEl = createTextElement("div", "inspector-role", detail.role);
    titleGroup.append(nameRow, roleEl);

    const actions = document.createElement("div");
    actions.className = "inspector-actions";

    const refreshBtnEl = createTextElement(
      "button",
      "inspector-icon-btn",
      "↻",
    );
    refreshBtnEl.type = "button";
    refreshBtnEl.title = "Refresh agent details";
    refreshBtnEl.setAttribute("aria-label", "Refresh agent details");
    refreshBtnEl.addEventListener("click", () => {
      void this.refresh();
    });

    actions.append(refreshBtnEl, this.createCloseButton());
    header.append(titleGroup, actions);

    const statusRefs = this.buildStatusCard(detail);
    const personaCard = this.buildPersonaCard(detail);
    const planCard = this.buildPlanCard(detail);
    const reflectionsCard = this.buildReflectionsCard(detail.reflections);
    const memoriesCard = this.buildMemoriesCard(
      detail.recent_memories,
      detail.top_memories,
    );
    const relationshipsCard = this.buildRelationshipsCard(detail.relationships);

    this.liveRefs = {
      moodPillEl,
      targetEl: statusRefs.targetEl,
      coordsEl: statusRefs.coordsEl,
      actionEl: statusRefs.actionEl,
      refreshBtnEl,
    };

    this.containerEl.replaceChildren(
      header,
      statusRefs.cardEl,
      personaCard,
      planCard,
      reflectionsCard,
      memoriesCard,
      relationshipsCard,
    );
    this.containerEl.scrollTop = previousScrollTop;
  }

  private createCloseButton(): HTMLButtonElement {
    const closeBtn = createTextElement("button", "inspector-icon-btn", "×");
    closeBtn.type = "button";
    closeBtn.title = "Close inspector (Esc)";
    closeBtn.setAttribute("aria-label", "Close inspector");
    closeBtn.addEventListener("click", () => {
      this.close();
    });
    return closeBtn;
  }

  private buildStatusCard(detail: AgentDetail): {
    cardEl: HTMLElement;
    targetEl: HTMLElement;
    coordsEl: HTMLElement;
    actionEl: HTMLElement;
  } {
    const card = this.createCard("Live Status");
    const grid = document.createElement("div");
    grid.className = "inspector-kv-grid";

    const addRow = (label: string, value: string): HTMLElement => {
      const row = document.createElement("div");
      row.className = "inspector-kv-row";
      const labelEl = createTextElement("span", "inspector-kv-label", label);
      const valEl = createTextElement("span", "inspector-kv-value", value);
      row.append(labelEl, valEl);
      grid.appendChild(row);
      return valEl;
    };

    addRow("Location", detail.current_location);
    const targetEl = addRow("Target", detail.target_location ?? "None");
    const coordsEl = addRow("Coords", `(${detail.x}, ${detail.y})`);
    const actionEl = addRow("Action", detail.current_action);

    const meterWrap = document.createElement("div");
    meterWrap.className = "reflection-meter-wrap";

    const threshold = Math.max(1, detail.reflection_threshold);
    const accumulated = Math.max(0, detail.accumulated_importance);
    const pct = Math.min(100, Math.round((accumulated / threshold) * 100));

    const meterHeader = document.createElement("div");
    meterHeader.className = "reflection-meter-header";
    meterHeader.append(
      createTextElement("span", "inspector-kv-label", "Reflection Meter"),
      createTextElement(
        "span",
        "inspector-kv-value",
        `${Math.round(accumulated)} / ${threshold}`,
      ),
    );

    const meterTrack = document.createElement("div");
    meterTrack.className = "reflection-meter";
    const meterFill = document.createElement("div");
    meterFill.className = "reflection-meter-fill";
    meterFill.style.width = `${pct}%`;
    meterTrack.appendChild(meterFill);

    meterWrap.append(meterHeader, meterTrack);
    card.append(grid, meterWrap);

    return { cardEl: card, targetEl, coordsEl, actionEl };
  }

  private buildPersonaCard(detail: AgentDetail): HTMLElement {
    const card = this.createCard("Persona");

    const meta = createTextElement(
      "div",
      "inspector-subtext",
      `Age ${detail.persona.age} · Home: ${detail.persona.home_location || detail.home_location}`,
    );
    const bio = createTextElement("p", "inspector-bio", detail.persona.bio);

    card.append(meta, bio);

    if (detail.persona.traits.length > 0) {
      const traitsList = document.createElement("div");
      traitsList.className = "traits-list";
      for (const trait of detail.persona.traits) {
        traitsList.appendChild(createTextElement("span", "trait-chip", trait));
      }
      card.appendChild(traitsList);
    }

    if (detail.persona.starting_goals.length > 0) {
      const goalsHeading = createTextElement(
        "div",
        "inspector-subheading",
        "Goals",
      );
      const goalsList = document.createElement("ul");
      goalsList.className = "goals-list";
      for (const goal of detail.persona.starting_goals) {
        goalsList.appendChild(createTextElement("li", "", goal));
      }
      card.append(goalsHeading, goalsList);
    }

    return card;
  }

  private buildPlanCard(detail: AgentDetail): HTMLElement {
    const card = this.createCard("Current Plan");

    if (detail.plan.hourly_focus) {
      card.appendChild(
        createTextElement(
          "div",
          "plan-focus-pill",
          `Focus: ${detail.plan.hourly_focus}`,
        ),
      );
    }

    if (detail.plan.current_step !== null) {
      const step = detail.plan.current_step;
      const stepBox = createTextElement(
        "div",
        "plan-step-box",
        `Now: ${step.action} · ${step.location} (${step.duration_minutes}m · ${step.arrived ? "arrived" : "en route"})`,
      );
      card.appendChild(stepBox);
    }

    if (detail.plan.daily_plan.length === 0) {
      card.appendChild(
        createTextElement(
          "div",
          "inspector-empty-inline",
          "No daily plan generated yet.",
        ),
      );
      return card;
    }

    const list = document.createElement("div");
    list.className = "plan-list";
    detail.plan.daily_plan.forEach((block, index) => {
      list.appendChild(
        this.createPlanBlockEl(block, index === detail.plan.active_block_index),
      );
    });
    card.appendChild(list);
    return card;
  }

  private createPlanBlockEl(
    block: AgentPlanBlock,
    isActive: boolean,
  ): HTMLElement {
    const el = document.createElement("div");
    el.className = isActive ? "plan-block active" : "plan-block";

    const header = document.createElement("div");
    header.className = "plan-block-header";
    header.append(
      createTextElement(
        "span",
        "plan-block-time",
        `${formatHour(block.start_hour)}–${formatHour(block.end_hour)}`,
      ),
      createTextElement("span", "plan-block-loc", block.location),
    );

    const desc = createTextElement(
      "div",
      "plan-block-desc",
      block.description,
    );
    el.append(header, desc);

    if (block.hourly_focus) {
      el.appendChild(
        createTextElement(
          "div",
          "plan-block-focus",
          `Hourly focus: ${block.hourly_focus}`,
        ),
      );
    }

    return el;
  }

  private buildReflectionsCard(reflections: AgentMemoryItem[]): HTMLElement {
    const card = this.createCard("Reflections");
    if (reflections.length === 0) {
      card.appendChild(
        createTextElement(
          "div",
          "inspector-empty-inline",
          "No reflections synthesized yet.",
        ),
      );
      return card;
    }

    const list = document.createElement("div");
    list.className = "memory-list";
    for (const item of reflections) {
      list.appendChild(this.createMemoryItemEl(item));
    }
    card.appendChild(list);
    return card;
  }

  private buildMemoriesCard(
    recent: AgentMemoryItem[],
    top: AgentMemoryItem[],
  ): HTMLElement {
    const card = this.createCard("Memories");

    if (recent.length === 0 && top.length === 0) {
      card.appendChild(
        createTextElement(
          "div",
          "inspector-empty-inline",
          "No memories recorded yet.",
        ),
      );
      return card;
    }

    if (recent.length > 0) {
      card.appendChild(
        createTextElement("div", "inspector-subheading", "Recent"),
      );
      const recentList = document.createElement("div");
      recentList.className = "memory-list";
      for (const item of recent) {
        recentList.appendChild(this.createMemoryItemEl(item));
      }
      card.appendChild(recentList);
    }

    if (top.length > 0) {
      card.appendChild(
        createTextElement("div", "inspector-subheading", "Top by Importance"),
      );
      const topList = document.createElement("div");
      topList.className = "memory-list";
      for (const item of top) {
        topList.appendChild(this.createMemoryItemEl(item));
      }
      card.appendChild(topList);
    }

    return card;
  }

  private createMemoryItemEl(item: AgentMemoryItem): HTMLElement {
    const el = document.createElement("div");
    el.className = "memory-item";

    const meta = document.createElement("div");
    meta.className = "memory-item-meta";

    const typeBadge = createTextElement(
      "span",
      `memory-type-badge ${item.type}`,
      item.type,
    );
    const idPart = item.id !== null ? `#${item.id} · ` : "";
    const stats = createTextElement(
      "span",
      "memory-item-stats",
      `${idPart}Imp ${item.importance} · Tick ${item.created_tick}`,
    );
    meta.append(typeBadge, stats);

    const body = createTextElement("div", "memory-item-text", item.text);
    el.append(meta, body);

    if (item.cited_memory_ids.length > 0) {
      const citeList = document.createElement("div");
      citeList.className = "cite-list";
      for (const citedId of item.cited_memory_ids) {
        citeList.appendChild(
          createTextElement("span", "cite-badge", `#${citedId}`),
        );
      }
      el.appendChild(citeList);
    }

    return el;
  }

  private buildRelationshipsCard(
    relationships: AgentRelationshipItem[],
  ): HTMLElement {
    const card = this.createCard("Relationships");

    if (relationships.length === 0) {
      card.appendChild(
        createTextElement(
          "div",
          "inspector-empty-inline",
          "No recorded interactions yet.",
        ),
      );
      return card;
    }

    const list = document.createElement("div");
    list.className = "relationship-list";
    for (const rel of relationships) {
      list.appendChild(this.createRelationshipRowEl(rel));
    }
    card.appendChild(list);
    return card;
  }

  private createRelationshipRowEl(rel: AgentRelationshipItem): HTMLElement {
    const row = document.createElement("div");
    row.className = "relationship-row";

    const tone =
      rel.affinity > 0.05
        ? "positive"
        : rel.affinity < -0.05
          ? "negative"
          : "neutral";

    const header = document.createElement("div");
    header.className = "relationship-header";
    header.append(
      createTextElement("span", "relationship-peer", rel.peer_name),
      createTextElement(
        "span",
        `affinity-score ${tone}`,
        formatAffinity(rel.affinity),
      ),
    );

    const bar = document.createElement("div");
    bar.className = "affinity-bar";
    const fill = document.createElement("div");
    fill.className = `affinity-bar-fill ${tone}`;
    const clampedPct = Math.max(
      4,
      Math.min(100, Math.round(((rel.affinity + 1) / 2) * 100)),
    );
    fill.style.width = `${clampedPct}%`;
    bar.appendChild(fill);

    const notes = createTextElement(
      "div",
      "relationship-notes",
      rel.notes.trim() || "No relationship notes yet.",
    );
    const meta = createTextElement(
      "div",
      "relationship-meta",
      `Last interaction: Tick ${rel.last_interaction_tick}`,
    );

    row.append(header, bar, notes, meta);
    return row;
  }

  private createCard(title: string): HTMLElement {
    const card = document.createElement("section");
    card.className = "inspector-card";
    card.appendChild(createTextElement("h3", "inspector-card-title", title));
    return card;
  }
}
