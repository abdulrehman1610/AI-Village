import cytoscape from "cytoscape";
import { fetchRelationships } from "../net/apiClient";
import type {
  RelationshipEdge,
  RelationshipNode,
  RelationshipsResponse,
} from "../types/sim";

export interface RelationshipGraphOptions {
  onSelectAgent?: (agentId: string) => void;
  onClose?: () => void;
}

interface MoodPalette {
  bg: string;
  border: string;
}

const DIALOGUE_REFRESH_THROTTLE_MS = 1200;
const POSITIVE_AFFINITY_THRESHOLD = 0.05;
const NEGATIVE_AFFINITY_THRESHOLD = -0.05;

const POSITIVE_MOODS = new Set([
  "happy",
  "excited",
  "cheerful",
  "content",
  "joyful",
  "inspired",
  "optimistic",
  "grateful",
  "friendly",
  "energized",
]);

const NEGATIVE_MOODS = new Set([
  "sad",
  "angry",
  "anxious",
  "worried",
  "stressed",
  "frustrated",
  "tired",
  "upset",
  "nervous",
  "alarmed",
]);

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

function formatSignedAffinity(affinity: number): string {
  const prefix = affinity > 0 ? "+" : "";
  return `${prefix}${affinity.toFixed(2)}`;
}

function getAffinityTone(affinity: number): "positive" | "negative" | "neutral" {
  if (affinity > POSITIVE_AFFINITY_THRESHOLD) {
    return "positive";
  }
  if (affinity < NEGATIVE_AFFINITY_THRESHOLD) {
    return "negative";
  }
  return "neutral";
}

function getAffinityColor(affinity: number): string {
  const tone = getAffinityTone(affinity);
  if (tone === "positive") {
    return "#10b981";
  }
  if (tone === "negative") {
    return "#ef4444";
  }
  return "#94a3b8";
}

function getMoodPalette(mood: string): MoodPalette {
  const normalized = mood.trim().toLowerCase();
  if (POSITIVE_MOODS.has(normalized)) {
    return { bg: "#065f46", border: "#10b981" };
  }
  if (NEGATIVE_MOODS.has(normalized)) {
    return { bg: "#78350f", border: "#f59e0b" };
  }
  return { bg: "#1e3a5f", border: "#38bdf8" };
}

function makeEdgeId(edge: RelationshipEdge): string {
  return `${edge.agent_a}::${edge.agent_b}`;
}

function buildCytoscapeStylesheet(): cytoscape.StylesheetStyle[] {
  return [
    {
      selector: "node",
      style: {
        label: "data(name)",
        color: "#f8fafc",
        "font-size": 12,
        "font-weight": "bold",
        "text-valign": "bottom",
        "text-halign": "center",
        "text-margin-y": 6,
        "text-background-color": "#0f172a",
        "text-background-opacity": 0.85,
        "text-background-padding": "3px",
        "text-background-shape": "roundrectangle",
        width: 42,
        height: 42,
        "background-color": "data(bgColor)",
        "border-width": 3,
        "border-color": "data(borderColor)",
      },
    },
    {
      selector: "node:selected",
      style: {
        "border-width": 4,
        "border-color": "#f8fafc",
        "overlay-color": "#38bdf8",
        "overlay-opacity": 0.22,
        "overlay-padding": 6,
      },
    },
    {
      selector: "edge",
      style: {
        width: "data(width)",
        "line-color": "data(lineColor)",
        "curve-style": "bezier",
        "target-arrow-shape": "none",
        opacity: 0.9,
        label: "data(affinityLabel)",
        "font-size": 10,
        "font-weight": "bold",
        color: "#e2e8f0",
        "text-background-color": "#0f172a",
        "text-background-opacity": 0.88,
        "text-background-padding": "2px",
        "text-background-shape": "roundrectangle",
      },
    },
    {
      selector: "edge:selected",
      style: {
        "line-color": "#38bdf8",
        opacity: 1,
        "overlay-color": "#38bdf8",
        "overlay-opacity": 0.18,
        "overlay-padding": 4,
      },
    },
  ];
}

function buildElements(data: RelationshipsResponse): {
  nodeElements: cytoscape.ElementDefinition[];
  edgeElements: cytoscape.ElementDefinition[];
} {
  const nodeIds = new Set<string>();
  const nodeElements: cytoscape.ElementDefinition[] = [];

  for (const node of data.nodes) {
    nodeIds.add(node.id);
    const palette = getMoodPalette(node.mood);
    nodeElements.push({
      group: "nodes",
      grabbable: true,
      data: {
        id: node.id,
        name: node.name,
        role: node.role,
        mood: node.mood,
        bgColor: palette.bg,
        borderColor: palette.border,
      },
    });
  }

  const edgeElements: cytoscape.ElementDefinition[] = [];
  for (const edge of data.edges) {
    if (!nodeIds.has(edge.agent_a) || !nodeIds.has(edge.agent_b)) {
      continue;
    }
    const width = 2 + Math.min(1, Math.abs(edge.affinity)) * 5;
    edgeElements.push({
      group: "edges",
      data: {
        id: makeEdgeId(edge),
        source: edge.agent_a,
        target: edge.agent_b,
        affinity: edge.affinity,
        affinityLabel: formatSignedAffinity(edge.affinity),
        lineColor: getAffinityColor(edge.affinity),
        width,
      },
    });
  }

  return { nodeElements, edgeElements };
}

/** Interactive Cytoscape.js modal displaying pairwise villager relationships without innerHTML. */
export class RelationshipGraphModal {
  private readonly containerEl: HTMLElement | null;
  private readonly options: RelationshipGraphOptions;

  private summaryPillEl: HTMLSpanElement | null = null;
  private refreshBtnEl: HTMLButtonElement | null = null;
  private statusEl: HTMLDivElement | null = null;
  private canvasEl: HTMLDivElement | null = null;
  private detailEl: HTMLDivElement | null = null;

  private cy: cytoscape.Core | null = null;
  private latestData: RelationshipsResponse | null = null;
  private renderedNodeSignature = "";
  private selectedKind: "node" | "edge" | null = null;
  private selectedId: string | null = null;

  private openState = false;
  private disposed = false;
  private requestSeq = 0;
  private inFlight = false;
  private lastFetchAt = 0;
  private rafId: number | null = null;
  private dialogueRefreshTimer: number | null = null;
  private resizeListening = false;

  private readonly handleWindowResize = (): void => {
    if (!this.openState || this.cy === null) {
      return;
    }
    this.scheduleResizeAndFit();
  };

  constructor(
    containerEl: HTMLElement | null,
    options: RelationshipGraphOptions = {},
  ) {
    this.containerEl = containerEl;
    this.options = options;

    if (containerEl !== null) {
      this.buildShell(containerEl);
    }
  }

  /** Open the relationship modal, un-hide it, fetch fresh relationships, and render Cytoscape. */
  public async open(): Promise<void> {
    if (this.disposed || this.containerEl === null) {
      return;
    }

    this.openState = true;
    this.containerEl.classList.remove("hidden");
    this.attachResizeListener();

    if (this.cy !== null) {
      this.scheduleResizeAndFit();
    }

    await this.refresh();
  }

  /** Hide the relationship modal and cancel pending async/animation updates. */
  public close(): void {
    const wasOpen = this.openState;
    this.openState = false;
    this.requestSeq += 1;
    this.inFlight = false;
    this.cancelScheduledRaf();
    this.clearDialogueRefreshTimer();
    this.detachResizeListener();

    if (this.refreshBtnEl !== null) {
      this.refreshBtnEl.disabled = false;
    }

    if (this.containerEl !== null) {
      this.containerEl.classList.add("hidden");
    }

    if (wasOpen) {
      this.options.onClose?.();
    }
  }

  /** Return whether the relationship network modal is currently open. */
  public isOpen(): boolean {
    return (
      !this.disposed &&
      this.openState &&
      this.containerEl !== null &&
      !this.containerEl.classList.contains("hidden")
    );
  }

  /** Fetch GET /relationships and update the Cytoscape graph if still open and current. */
  public async refresh(): Promise<void> {
    if (this.disposed || this.containerEl === null || !this.openState) {
      return;
    }

    const seq = ++this.requestSeq;
    this.inFlight = true;
    if (this.refreshBtnEl !== null) {
      this.refreshBtnEl.disabled = true;
    }

    if (this.latestData === null) {
      this.setStatusMessage("Loading relationship network...", false);
    }

    try {
      const data = await fetchRelationships();
      if (this.disposed || !this.openState || seq !== this.requestSeq) {
        return;
      }

      this.latestData = data;
      this.updateSummaryPill(data);
      this.updateEmptyStatus(data);
      this.renderSelectedDetail();

      this.scheduleGraphSync(data);
    } catch (err: unknown) {
      if (this.disposed || !this.openState || seq !== this.requestSeq) {
        return;
      }
      const message =
        err instanceof Error ? err.message : "Failed to load relationships.";
      this.setErrorStatus(message);
    } finally {
      if (seq === this.requestSeq) {
        this.inFlight = false;
        this.lastFetchAt = Date.now();
        if (this.refreshBtnEl !== null) {
          this.refreshBtnEl.disabled = false;
        }
      }
    }
  }

  /** Trigger a throttled refresh when a live dialogue event completes while the modal is open. */
  public handleDialogue(): void {
    if (this.disposed || !this.isOpen()) {
      return;
    }

    const elapsed = Date.now() - this.lastFetchAt;
    if (!this.inFlight && elapsed >= DIALOGUE_REFRESH_THROTTLE_MS) {
      this.clearDialogueRefreshTimer();
      void this.refresh();
      return;
    }

    if (this.dialogueRefreshTimer !== null) {
      return;
    }

    const delay = Math.max(150, DIALOGUE_REFRESH_THROTTLE_MS - elapsed);
    this.dialogueRefreshTimer = window.setTimeout(() => {
      this.dialogueRefreshTimer = null;
      if (this.isOpen()) {
        void this.refresh();
      }
    }, delay);
  }

  /** Destroy Cytoscape instance, timers, listeners, and DOM contents. */
  public destroy(): void {
    this.disposed = true;
    this.openState = false;
    this.requestSeq += 1;
    this.inFlight = false;
    this.cancelScheduledRaf();
    this.clearDialogueRefreshTimer();
    this.detachResizeListener();

    if (this.cy !== null) {
      this.cy.destroy();
      this.cy = null;
    }

    this.latestData = null;
    this.renderedNodeSignature = "";
    this.selectedKind = null;
    this.selectedId = null;

    if (this.containerEl !== null) {
      this.containerEl.classList.add("hidden");
      this.containerEl.replaceChildren();
    }

    this.summaryPillEl = null;
    this.refreshBtnEl = null;
    this.statusEl = null;
    this.canvasEl = null;
    this.detailEl = null;
  }

  private buildShell(containerEl: HTMLElement): void {
    const header = document.createElement("div");
    header.className = "modal-header graph-header";

    const titleGroup = document.createElement("div");
    titleGroup.className = "modal-title-group";
    const title = createTextElement("h2", "modal-title", "Relationship Network");
    const summaryPill = createTextElement(
      "span",
      "graph-summary-pill",
      "0 villagers · 0 links",
    );
    this.summaryPillEl = summaryPill;
    titleGroup.append(title, summaryPill);

    const actions = document.createElement("div");
    actions.className = "modal-actions";

    const refreshBtn = createTextElement("button", "modal-btn", "Refresh");
    refreshBtn.type = "button";
    refreshBtn.title = "Refresh relationship network";
    refreshBtn.setAttribute("aria-label", "Refresh relationship network");
    refreshBtn.addEventListener("click", () => {
      void this.refresh();
    });
    this.refreshBtnEl = refreshBtn;

    const closeBtn = createTextElement("button", "modal-icon-btn", "×");
    closeBtn.type = "button";
    closeBtn.title = "Close relationship network (Esc)";
    closeBtn.setAttribute("aria-label", "Close relationship network");
    closeBtn.addEventListener("click", () => {
      this.close();
    });

    actions.append(refreshBtn, closeBtn);
    header.append(titleGroup, actions);

    const legend = document.createElement("div");
    legend.className = "graph-legend";
    legend.append(
      this.createLegendItem("positive", "Positive (> +0.05)"),
      this.createLegendItem("neutral", "Neutral (-0.05 to +0.05)"),
      this.createLegendItem("negative", "Negative (< -0.05)"),
    );

    const status = document.createElement("div");
    status.className = "graph-status hidden";
    this.statusEl = status;

    const canvas = document.createElement("div");
    canvas.className = "graph-canvas";
    canvas.setAttribute("aria-label", "Villager relationship graph");
    this.canvasEl = canvas;

    const detail = document.createElement("div");
    detail.className = "graph-detail";
    this.detailEl = detail;
    this.renderDefaultDetail();

    containerEl.replaceChildren(header, legend, status, canvas, detail);
  }

  private createLegendItem(
    tone: "positive" | "neutral" | "negative",
    label: string,
  ): HTMLElement {
    const item = document.createElement("span");
    item.className = "graph-legend-item";
    const swatch = createTextElement("span", `graph-legend-swatch ${tone}`, "");
    const text = createTextElement("span", "graph-legend-label", label);
    item.append(swatch, text);
    return item;
  }

  private attachResizeListener(): void {
    if (!this.resizeListening) {
      window.addEventListener("resize", this.handleWindowResize);
      this.resizeListening = true;
    }
  }

  private detachResizeListener(): void {
    if (this.resizeListening) {
      window.removeEventListener("resize", this.handleWindowResize);
      this.resizeListening = false;
    }
  }

  private cancelScheduledRaf(): void {
    if (this.rafId !== null) {
      window.cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
  }

  private clearDialogueRefreshTimer(): void {
    if (this.dialogueRefreshTimer !== null) {
      window.clearTimeout(this.dialogueRefreshTimer);
      this.dialogueRefreshTimer = null;
    }
  }

  private scheduleResizeAndFit(): void {
    this.cancelScheduledRaf();
    this.rafId = window.requestAnimationFrame(() => {
      this.rafId = null;
      if (this.disposed || !this.isOpen() || this.cy === null) {
        return;
      }
      this.cy.resize();
      this.cy.fit(undefined, 28);
    });
  }

  private scheduleGraphSync(data: RelationshipsResponse): void {
    this.cancelScheduledRaf();
    this.rafId = window.requestAnimationFrame(() => {
      this.rafId = null;
      if (this.disposed || !this.isOpen() || this.canvasEl === null) {
        return;
      }
      this.syncCytoscape(data);
    });
  }

  private syncCytoscape(data: RelationshipsResponse): void {
    if (this.canvasEl === null) {
      return;
    }

    const { nodeElements, edgeElements } = buildElements(data);
    const nextSignature = data.nodes
      .map((n) => n.id)
      .sort()
      .join("|");

    if (this.cy === null) {
      this.cy = cytoscape({
        container: this.canvasEl,
        elements: [...nodeElements, ...edgeElements],
        style: buildCytoscapeStylesheet(),
        layout: {
          name: "circle",
          animate: false,
          padding: 28,
          avoidOverlap: true,
        },
        minZoom: 0.4,
        maxZoom: 2.5,
        wheelSensitivity: 0.25,
      });

      this.bindCytoscapeEvents(this.cy);
      this.renderedNodeSignature = nextSignature;
      this.cy.resize();
      this.cy.fit(undefined, 28);
      return;
    }

    const cy = this.cy;
    const nodesChanged = nextSignature !== this.renderedNodeSignature;

    cy.batch(() => {
      if (nodesChanged) {
        cy.elements().remove();
        cy.add([...nodeElements, ...edgeElements]);
      } else {
        for (const node of data.nodes) {
          const existing = cy.getElementById(node.id);
          if (existing.nonempty()) {
            const palette = getMoodPalette(node.mood);
            existing.data({
              name: node.name,
              role: node.role,
              mood: node.mood,
              bgColor: palette.bg,
              borderColor: palette.border,
            });
          }
        }
        cy.edges().remove();
        cy.add(edgeElements);
      }
    });

    if (nodesChanged) {
      this.renderedNodeSignature = nextSignature;
      cy.layout({
        name: "circle",
        animate: false,
        padding: 28,
        avoidOverlap: true,
      }).run();
    }

    cy.resize();
    cy.fit(undefined, 28);
  }

  private bindCytoscapeEvents(cy: cytoscape.Core): void {
    cy.on("tap", "node", (evt: cytoscape.EventObject) => {
      const targetId = this.extractTargetId(evt);
      if (targetId === null) {
        return;
      }
      this.selectedKind = "node";
      this.selectedId = targetId;
      this.renderSelectedDetail();
      this.options.onSelectAgent?.(targetId);
    });

    cy.on("tap", "edge", (evt: cytoscape.EventObject) => {
      const targetId = this.extractTargetId(evt);
      if (targetId === null) {
        return;
      }
      this.selectedKind = "edge";
      this.selectedId = targetId;
      this.renderSelectedDetail();
    });

    cy.on("tap", (evt: cytoscape.EventObject) => {
      if (evt.target === cy) {
        this.selectedKind = null;
        this.selectedId = null;
        this.renderDefaultDetail();
      }
    });
  }

  private extractTargetId(evt: cytoscape.EventObject): string | null {
    const candidate = evt.target as { id?: () => unknown } | null | undefined;
    if (candidate === null || candidate === undefined) {
      return null;
    }
    if (typeof candidate.id !== "function") {
      return null;
    }
    const idVal = candidate.id();
    return typeof idVal === "string" && idVal.length > 0 ? idVal : null;
  }

  private updateSummaryPill(data: RelationshipsResponse): void {
    if (this.summaryPillEl === null) {
      return;
    }
    const nodeCount = data.nodes.length;
    const edgeCount = data.edges.length;
    const nodeWord = nodeCount === 1 ? "villager" : "villagers";
    const edgeWord = edgeCount === 1 ? "link" : "links";
    this.summaryPillEl.textContent = `${nodeCount} ${nodeWord} · ${edgeCount} ${edgeWord}`;
  }

  private updateEmptyStatus(data: RelationshipsResponse): void {
    if (data.nodes.length === 0) {
      this.setStatusMessage("No villagers found in simulation.", false);
      return;
    }
    if (data.edges.length === 0) {
      this.setStatusMessage(
        "No conversations recorded yet — villagers will connect as they interact.",
        false,
      );
      return;
    }
    this.clearStatusMessage();
  }

  private setStatusMessage(message: string, isError: boolean): void {
    if (this.statusEl === null) {
      return;
    }
    this.statusEl.className = isError ? "graph-status error" : "graph-status";
    this.statusEl.replaceChildren(createTextElement("span", "", message));
  }

  private setErrorStatus(message: string): void {
    if (this.statusEl === null) {
      return;
    }
    this.statusEl.className = "graph-status error";
    const msgEl = createTextElement("span", "", message);
    const retryBtn = createTextElement("button", "inspector-retry-btn", "Retry");
    retryBtn.type = "button";
    retryBtn.addEventListener("click", () => {
      void this.refresh();
    });
    this.statusEl.replaceChildren(msgEl, retryBtn);
  }

  private clearStatusMessage(): void {
    if (this.statusEl === null) {
      return;
    }
    this.statusEl.className = "graph-status hidden";
    this.statusEl.replaceChildren();
  }

  private renderSelectedDetail(): void {
    if (this.detailEl === null) {
      return;
    }
    if (this.latestData === null || this.selectedKind === null || this.selectedId === null) {
      this.renderDefaultDetail();
      return;
    }

    if (this.selectedKind === "node") {
      const node = this.latestData.nodes.find((n) => n.id === this.selectedId);
      if (node !== undefined) {
        this.renderNodeDetail(node, this.latestData.edges);
        return;
      }
    } else if (this.selectedKind === "edge") {
      const edge = this.latestData.edges.find(
        (e) => makeEdgeId(e) === this.selectedId,
      );
      if (edge !== undefined) {
        this.renderEdgeDetail(edge);
        return;
      }
    }

    this.selectedKind = null;
    this.selectedId = null;
    this.renderDefaultDetail();
  }

  private renderDefaultDetail(): void {
    if (this.detailEl === null) {
      return;
    }
    this.detailEl.replaceChildren(
      createTextElement(
        "div",
        "graph-detail-empty",
        "Tap a villager node to inspect or an edge to read relationship notes.",
      ),
    );
  }

  private renderNodeDetail(
    node: RelationshipNode,
    edges: RelationshipEdge[],
  ): void {
    if (this.detailEl === null) {
      return;
    }

    const header = document.createElement("div");
    header.className = "graph-detail-header";
    const titleGroup = document.createElement("div");
    titleGroup.className = "graph-detail-title-group";
    titleGroup.append(
      createTextElement("strong", "graph-detail-title", node.name),
      createTextElement("span", "graph-detail-role", node.role),
    );
    const moodPill = createTextElement("span", "mood-pill", node.mood);
    header.append(titleGroup, moodPill);

    const connected = edges
      .filter((e) => e.agent_a === node.id || e.agent_b === node.id)
      .slice()
      .sort((a, b) => Math.abs(b.affinity) - Math.abs(a.affinity));

    if (connected.length === 0) {
      this.detailEl.replaceChildren(
        header,
        createTextElement(
          "div",
          "graph-detail-empty",
          `${node.name} has no recorded relationships yet.`,
        ),
      );
      return;
    }

    const list = document.createElement("div");
    list.className = "graph-rel-list";

    for (const edge of connected) {
      const peerName =
        edge.agent_a === node.id ? edge.agent_b_name : edge.agent_a_name;
      const tone = getAffinityTone(edge.affinity);

      const item = document.createElement("div");
      item.className = "graph-rel-item";

      const rowTop = document.createElement("div");
      rowTop.className = "graph-rel-item-top";
      rowTop.append(
        createTextElement("span", "graph-rel-peer", peerName),
        createTextElement(
          "span",
          `affinity-score ${tone}`,
          formatSignedAffinity(edge.affinity),
        ),
      );

      const noteText = edge.notes.trim() || "No relationship notes yet.";
      const notesEl = createTextElement("div", "graph-detail-notes", noteText);
      const metaEl = createTextElement(
        "div",
        "graph-detail-meta",
        `Last interaction: Tick ${edge.last_interaction_tick}`,
      );

      item.append(rowTop, notesEl, metaEl);
      list.appendChild(item);
    }

    this.detailEl.replaceChildren(header, list);
  }

  private renderEdgeDetail(edge: RelationshipEdge): void {
    if (this.detailEl === null) {
      return;
    }

    const tone = getAffinityTone(edge.affinity);

    const header = document.createElement("div");
    header.className = "graph-detail-header";
    header.append(
      createTextElement(
        "strong",
        "graph-detail-title",
        `${edge.agent_a_name} ↔ ${edge.agent_b_name}`,
      ),
      createTextElement(
        "span",
        `affinity-score ${tone}`,
        formatSignedAffinity(edge.affinity),
      ),
    );

    const meta = createTextElement(
      "div",
      "graph-detail-meta",
      `Last interaction: Tick ${edge.last_interaction_tick}`,
    );

    const notes = createTextElement(
      "div",
      "graph-detail-notes",
      edge.notes.trim() || "No relationship notes recorded yet.",
    );

    this.detailEl.replaceChildren(header, meta, notes);
  }
}
