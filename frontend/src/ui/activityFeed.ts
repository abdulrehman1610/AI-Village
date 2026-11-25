import type {
  DialogueMessage,
  EventMessage,
  ReflectionMessage,
} from "../types/sim";

const MAX_FEED_ITEMS = 25;

/** Translucent overlay rendering live server event and dialogue updates without innerHTML. */
export class ActivityFeed {
  private readonly listEl: HTMLDivElement | null;
  private titleEl: HTMLSpanElement | null = null;
  private emptyEl: HTMLDivElement | null = null;

  constructor(containerEl: HTMLElement | null) {
    if (containerEl === null) {
      this.listEl = null;
      return;
    }

    const headerEl = document.createElement("div");
    headerEl.className = "feed-header";

    const titleEl = document.createElement("span");
    titleEl.textContent = "Live Activity";
    this.titleEl = titleEl;
    headerEl.appendChild(titleEl);

    const listEl = document.createElement("div");
    listEl.className = "feed-list";
    this.listEl = listEl;

    this.clear();

    containerEl.replaceChildren(headerEl, listEl);
  }

  /** Update the activity feed header label (e.g. Live Activity vs Replay Activity). */
  public setModeLabel(label: string): void {
    if (this.titleEl !== null) {
      this.titleEl.textContent = label;
    }
  }

  /** Clear all rendered activity entries and restore a fresh empty placeholder. */
  public clear(
    emptyText = "Waiting for live events and conversations...",
  ): void {
    if (this.listEl === null) {
      return;
    }
    const emptyEl = document.createElement("div");
    emptyEl.className = "feed-empty";
    emptyEl.textContent = emptyText;
    this.emptyEl = emptyEl;
    this.listEl.replaceChildren(emptyEl);
  }

  /** Prepend a god-mode or world event card to the feed. */
  public pushEvent(msg: EventMessage): void {
    if (this.listEl === null) {
      return;
    }

    const item = document.createElement("article");
    item.className = "feed-item event";

    const meta = this.createMetaRow(
      "EVENT",
      msg.sim_time,
      msg.location ?? "All Village",
    );

    const body = document.createElement("div");
    body.className = "feed-body";
    body.textContent = msg.text;

    const submeta = document.createElement("div");
    submeta.className = "feed-submeta";
    const count = msg.affected_agents.length;
    submeta.textContent =
      count > 0
        ? `Alerted ${count} villager(s)`
        : "No nearby witnesses";

    item.append(meta, body, submeta);
    this.prependItem(item);
  }

  /** Prepend a completed agent conversation card to the feed. */
  public pushDialogue(msg: DialogueMessage): void {
    if (this.listEl === null) {
      return;
    }

    const item = document.createElement("article");
    item.className = "feed-item dialogue";

    const meta = this.createMetaRow(
      "DIALOGUE",
      msg.sim_time,
      msg.location ?? "Village",
    );

    const subject = document.createElement("div");
    subject.className = "feed-subject";
    subject.textContent =
      msg.participant_names.length > 0
        ? msg.participant_names.join(" ↔ ")
        : "Conversation";

    const body = document.createElement("div");
    body.className = "feed-body";
    const fallbackTurn = msg.turns[0]
      ? `${msg.turns[0].speaker_name}: ${msg.turns[0].text}`
      : "";
    body.textContent = msg.summary.trim() || fallbackTurn;

    const submeta = document.createElement("div");
    submeta.className = "feed-submeta";
    const turnCount = msg.turns.length;
    submeta.textContent = `${turnCount} ${turnCount === 1 ? "turn" : "turns"}`;

    item.append(meta, subject, body, submeta);
    this.prependItem(item);
  }

  /** Prepend a synthesized agent reflection card to the feed. */
  public pushReflection(msg: ReflectionMessage): void {
    if (this.listEl === null) {
      return;
    }

    const item = document.createElement("article");
    item.className = "feed-item reflection";

    const meta = this.createMetaRow(
      "REFLECTION",
      msg.sim_time,
      msg.agent_name,
    );

    const body = document.createElement("div");
    body.className = "feed-body";
    body.textContent = msg.insight;

    const submeta = document.createElement("div");
    submeta.className = "feed-submeta";
    submeta.textContent =
      msg.cited_memory_ids.length > 0
        ? `Cited: #${msg.cited_memory_ids.join(", #")}`
        : "Synthesized insight";

    item.append(meta, body, submeta);
    this.prependItem(item);
  }

  private createMetaRow(
    badgeLabel: string,
    simTime: string,
    locationLabel: string,
  ): HTMLDivElement {
    const meta = document.createElement("div");
    meta.className = "feed-meta";

    const badge = document.createElement("span");
    badge.className = "feed-badge";
    badge.textContent = badgeLabel;

    const details = document.createElement("span");
    details.textContent = `${simTime} · ${locationLabel}`;

    meta.append(badge, details);
    return meta;
  }

  private prependItem(item: HTMLElement): void {
    if (this.listEl === null) {
      return;
    }

    if (this.emptyEl !== null) {
      this.emptyEl.remove();
      this.emptyEl = null;
    }

    this.listEl.prepend(item);
    while (this.listEl.children.length > MAX_FEED_ITEMS) {
      this.listEl.lastElementChild?.remove();
    }
  }
}
