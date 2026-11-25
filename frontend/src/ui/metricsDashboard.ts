import {
  BarController,
  BarElement,
  CategoryScale,
  Chart,
  Filler,
  Legend,
  LinearScale,
  LineController,
  LineElement,
  PointElement,
  Tooltip,
  type ChartConfiguration,
} from "chart.js";
import { fetchMetrics } from "../net/apiClient";
import type {
  MetricsMessage,
  MetricsSnapshot,
  ModelMetrics,
  PurposeMetrics,
  TickMetricsPoint,
} from "../types/sim";

Chart.register(
  LineController,
  BarController,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Tooltip,
  Legend,
  Filler,
);

export interface MetricsDashboardOptions {
  onClose?: () => void;
}

interface KpiCardRefs {
  valueEl: HTMLDivElement;
  subEl: HTMLDivElement;
}

interface BudgetMeterRefs {
  valueEl: HTMLSpanElement;
  fillEl: HTMLDivElement;
}

const CHART_TICK_COLOR = "#94a3b8";
const CHART_GRID_COLOR = "rgba(51, 65, 85, 0.45)";
const CHART_LEGEND_COLOR = "#cbd5e1";

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

function formatCount(value: number): string {
  return Math.round(value).toLocaleString("en-US");
}

function formatPercent(ratio: number): string {
  const clamped = Math.max(0, Math.min(1, ratio));
  return `${(clamped * 100).toFixed(1)}%`;
}

function formatUsd(amount: number): string {
  return `$${Math.max(0, amount).toFixed(4)}`;
}

function formatLatencyMs(ms: number): string {
  return `${Math.max(0, ms).toFixed(1)} ms`;
}

function formatPurposeLabel(purpose: string): string {
  return purpose
    .split("_")
    .filter((part) => part.length > 0)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function computeBudgetPercent(used: number, limit: number): number {
  if (limit <= 0) {
    return 0;
  }
  return Math.max(0, Math.round((used / limit) * 100));
}

function getBudgetTone(pct: number): "ok" | "warn" | "danger" {
  if (pct >= 95) {
    return "danger";
  }
  if (pct >= 75) {
    return "warn";
  }
  return "ok";
}

/** Live Chart.js v4 Cost, Token, and Latency dashboard modal without innerHTML. */
export class MetricsDashboardPanel {
  private readonly containerEl: HTMLElement | null;
  private readonly options: MetricsDashboardOptions;

  private liveBadgeEl: HTMLSpanElement | null = null;
  private refreshBtnEl: HTMLButtonElement | null = null;
  private statusEl: HTMLDivElement | null = null;

  private callsKpi: KpiCardRefs | null = null;
  private cacheKpi: KpiCardRefs | null = null;
  private tokensKpi: KpiCardRefs | null = null;
  private costKpi: KpiCardRefs | null = null;
  private avgLatencyKpi: KpiCardRefs | null = null;
  private maxLatencyKpi: KpiCardRefs | null = null;

  private budgetTitleEl: HTMLDivElement | null = null;
  private tokenBudgetMeter: BudgetMeterRefs | null = null;
  private costBudgetMeter: BudgetMeterRefs | null = null;

  private historyCanvasEl: HTMLCanvasElement | null = null;
  private purposeCanvasEl: HTMLCanvasElement | null = null;
  private latencyCanvasEl: HTMLCanvasElement | null = null;

  private historyEmptyEl: HTMLDivElement | null = null;
  private purposeEmptyEl: HTMLDivElement | null = null;
  private latencyEmptyEl: HTMLDivElement | null = null;

  private modelTableBodyEl: HTMLTableSectionElement | null = null;

  private tokensChart: Chart<"line", number[], string> | null = null;
  private purposeChart: Chart<"bar", number[], string> | null = null;
  private latencyChart: Chart<"bar", number[], string> | null = null;

  private latestSnapshot: MetricsSnapshot | null = null;
  private openState = false;
  private disposed = false;
  private requestSeq = 0;
  private stateEpoch = 0;
  private rafId: number | null = null;
  private resizeListening = false;

  private readonly handleWindowResize = (): void => {
    if (!this.openState) {
      return;
    }
    this.scheduleChartSync(true);
  };

  constructor(
    containerEl: HTMLElement | null,
    options: MetricsDashboardOptions = {},
  ) {
    this.containerEl = containerEl;
    this.options = options;

    if (containerEl !== null) {
      this.buildShell(containerEl);
    }
  }

  /** Open the dashboard, un-hide it, sync cached/fetched metrics, and resize charts on RAF. */
  public async open(): Promise<void> {
    if (this.disposed || this.containerEl === null) {
      return;
    }

    this.openState = true;
    this.containerEl.classList.remove("hidden");
    this.attachResizeListener();

    if (this.latestSnapshot !== null) {
      this.renderSnapshotDom(this.latestSnapshot);
      this.scheduleChartSync(true);
    }

    await this.refresh();
  }

  /** Hide the dashboard modal and cancel pending RAF/fetch updates. */
  public close(): void {
    const wasOpen = this.openState;
    this.openState = false;
    this.requestSeq += 1;
    this.cancelScheduledRaf();
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

  /** Return whether the cost and telemetry dashboard is currently open. */
  public isOpen(): boolean {
    return (
      !this.disposed &&
      this.openState &&
      this.containerEl !== null &&
      !this.containerEl.classList.contains("hidden")
    );
  }

  /** Fetch GET /metrics and update KPIs, budget bars, model table, and Chart.js datasets. */
  public async refresh(): Promise<void> {
    if (this.disposed || this.containerEl === null || !this.openState) {
      return;
    }

    const seq = ++this.requestSeq;
    const startEpoch = this.stateEpoch;
    if (this.refreshBtnEl !== null) {
      this.refreshBtnEl.disabled = true;
    }

    if (this.latestSnapshot === null) {
      this.setStatusMessage("Loading LLM telemetry...", false);
    }

    try {
      const snapshot = await fetchMetrics();
      if (this.disposed || !this.openState || seq !== this.requestSeq) {
        return;
      }

      if (this.stateEpoch === startEpoch || this.latestSnapshot === null) {
        this.latestSnapshot = snapshot;
        this.clearStatusMessage();
        this.renderSnapshotDom(snapshot);
        this.scheduleChartSync(true);
      } else {
        this.clearStatusMessage();
      }
    } catch (err: unknown) {
      if (this.disposed || !this.openState || seq !== this.requestSeq) {
        return;
      }
      const message =
        err instanceof Error ? err.message : "Failed to load LLM metrics.";
      this.setErrorStatus(message);
    } finally {
      if (seq === this.requestSeq && this.refreshBtnEl !== null) {
        this.refreshBtnEl.disabled = false;
      }
    }
  }

  /** Cache live WebSocket metrics and update DOM/charts in-place if currently visible. */
  public applyMetrics(msg: MetricsMessage): void {
    if (this.disposed) {
      return;
    }

    this.latestSnapshot = msg;
    this.stateEpoch += 1;

    if (!this.isOpen()) {
      return;
    }

    this.clearStatusMessage();
    this.renderSnapshotDom(msg);

    if (this.hasAllCharts()) {
      this.updateChartsInPlace(msg);
    } else {
      this.scheduleChartSync(false);
    }
  }

  /** Destroy all Chart.js instances, event listeners, and DOM contents. */
  public destroy(): void {
    this.disposed = true;
    this.openState = false;
    this.requestSeq += 1;
    this.cancelScheduledRaf();
    this.detachResizeListener();

    this.tokensChart?.destroy();
    this.purposeChart?.destroy();
    this.latencyChart?.destroy();
    this.tokensChart = null;
    this.purposeChart = null;
    this.latencyChart = null;

    this.latestSnapshot = null;

    if (this.containerEl !== null) {
      this.containerEl.classList.add("hidden");
      this.containerEl.replaceChildren();
    }

    this.liveBadgeEl = null;
    this.refreshBtnEl = null;
    this.statusEl = null;
    this.callsKpi = null;
    this.cacheKpi = null;
    this.tokensKpi = null;
    this.costKpi = null;
    this.avgLatencyKpi = null;
    this.maxLatencyKpi = null;
    this.budgetTitleEl = null;
    this.tokenBudgetMeter = null;
    this.costBudgetMeter = null;
    this.historyCanvasEl = null;
    this.purposeCanvasEl = null;
    this.latencyCanvasEl = null;
    this.historyEmptyEl = null;
    this.purposeEmptyEl = null;
    this.latencyEmptyEl = null;
    this.modelTableBodyEl = null;
  }

  private buildShell(containerEl: HTMLElement): void {
    const header = document.createElement("div");
    header.className = "modal-header metrics-header";

    const titleGroup = document.createElement("div");
    titleGroup.className = "modal-title-group";
    const title = createTextElement("h2", "modal-title", "LLM Cost & Telemetry");
    const liveBadge = createTextElement(
      "span",
      "metrics-live-badge",
      "Tick 0 · Day 1 06:00",
    );
    this.liveBadgeEl = liveBadge;
    titleGroup.append(title, liveBadge);

    const actions = document.createElement("div");
    actions.className = "modal-actions";

    const refreshBtn = createTextElement("button", "modal-btn", "Refresh");
    refreshBtn.type = "button";
    refreshBtn.title = "Refresh LLM metrics";
    refreshBtn.setAttribute("aria-label", "Refresh LLM metrics");
    refreshBtn.addEventListener("click", () => {
      void this.refresh();
    });
    this.refreshBtnEl = refreshBtn;

    const closeBtn = createTextElement("button", "modal-icon-btn", "×");
    closeBtn.type = "button";
    closeBtn.title = "Close metrics dashboard (Esc)";
    closeBtn.setAttribute("aria-label", "Close metrics dashboard");
    closeBtn.addEventListener("click", () => {
      this.close();
    });

    actions.append(refreshBtn, closeBtn);
    header.append(titleGroup, actions);

    const status = document.createElement("div");
    status.className = "metrics-status hidden";
    this.statusEl = status;

    const kpiGrid = document.createElement("div");
    kpiGrid.className = "metrics-kpi-grid";
    this.callsKpi = this.createKpiCard(kpiGrid, "Total Calls", "0", "Cache hits: 0");
    this.cacheKpi = this.createKpiCard(kpiGrid, "Cache Hit Rate", "0.0%", "0 / 0 calls");
    this.tokensKpi = this.createKpiCard(kpiGrid, "Total Tokens", "0", "In 0 · Out 0");
    this.costKpi = this.createKpiCard(kpiGrid, "Estimated Cost", "$0.0000", "Day 1 cumulative");
    this.avgLatencyKpi = this.createKpiCard(kpiGrid, "Avg Latency", "0.0 ms", "Across 0 calls");
    this.maxLatencyKpi = this.createKpiCard(kpiGrid, "Max Latency", "0.0 ms", "Peak single call");

    const budgetCard = document.createElement("section");
    budgetCard.className = "metrics-budget-card";
    const budgetTitle = createTextElement(
      "div",
      "metrics-section-title",
      "Daily Budget (Budget Day 1)",
    );
    this.budgetTitleEl = budgetTitle;
    budgetCard.appendChild(budgetTitle);
    this.tokenBudgetMeter = this.createBudgetRow(
      budgetCard,
      "Daily Tokens",
      "0 / 0 (0%)",
    );
    this.costBudgetMeter = this.createBudgetRow(
      budgetCard,
      "Daily Cost Limit",
      "$0.0000 / $0.0000 (0%)",
    );

    const chartsGrid = document.createElement("div");
    chartsGrid.className = "metrics-charts-grid";

    const historyCard = this.createChartCard(
      "Tokens Over Time",
      "No tick telemetry recorded yet.",
    );
    this.historyCanvasEl = historyCard.canvasEl;
    this.historyEmptyEl = historyCard.emptyEl;

    const purposeCard = this.createChartCard(
      "Tokens & Calls by Purpose",
      "No LLM calls recorded yet.",
    );
    this.purposeCanvasEl = purposeCard.canvasEl;
    this.purposeEmptyEl = purposeCard.emptyEl;

    const latencyCard = this.createChartCard(
      "Average Latency by Purpose (ms)",
      "No LLM calls recorded yet.",
    );
    this.latencyCanvasEl = latencyCard.canvasEl;
    this.latencyEmptyEl = latencyCard.emptyEl;

    chartsGrid.append(historyCard.cardEl, purposeCard.cardEl, latencyCard.cardEl);

    const tableCard = document.createElement("section");
    tableCard.className = "metrics-table-card";
    tableCard.appendChild(
      createTextElement("div", "metrics-section-title", "By Model"),
    );

    const tableWrap = document.createElement("div");
    tableWrap.className = "metrics-table-wrap";

    const table = document.createElement("table");
    table.className = "metrics-table";

    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const col of [
      "Model",
      "Calls",
      "Cache Hits",
      "Tokens",
      "Avg ms",
      "Cost USD",
    ]) {
      headRow.appendChild(createTextElement("th", "", col));
    }
    thead.appendChild(headRow);

    const tbody = document.createElement("tbody");
    this.modelTableBodyEl = tbody;
    this.renderModelRows([]);

    table.append(thead, tbody);
    tableWrap.appendChild(table);
    tableCard.appendChild(tableWrap);

    containerEl.replaceChildren(
      header,
      status,
      kpiGrid,
      budgetCard,
      chartsGrid,
      tableCard,
    );
  }

  private createKpiCard(
    parent: HTMLElement,
    label: string,
    initialValue: string,
    initialSub: string,
  ): KpiCardRefs {
    const card = document.createElement("div");
    card.className = "metrics-kpi-card";
    const labelEl = createTextElement("div", "metrics-kpi-label", label);
    const valueEl = createTextElement("div", "metrics-kpi-value", initialValue);
    const subEl = createTextElement("div", "metrics-kpi-sub", initialSub);
    card.append(labelEl, valueEl, subEl);
    parent.appendChild(card);
    return { valueEl, subEl };
  }

  private createBudgetRow(
    parent: HTMLElement,
    label: string,
    initialValue: string,
  ): BudgetMeterRefs {
    const row = document.createElement("div");
    row.className = "metrics-budget-row";

    const header = document.createElement("div");
    header.className = "metrics-budget-header";
    const labelEl = createTextElement("span", "metrics-budget-label", label);
    const valueEl = createTextElement("span", "metrics-budget-value", initialValue);
    header.append(labelEl, valueEl);

    const track = document.createElement("div");
    track.className = "metrics-budget-track";
    const fillEl = document.createElement("div");
    fillEl.className = "metrics-budget-fill ok";
    fillEl.style.width = "0%";
    track.appendChild(fillEl);

    row.append(header, track);
    parent.appendChild(row);
    return { valueEl, fillEl };
  }

  private createChartCard(
    title: string,
    emptyText: string,
  ): {
    cardEl: HTMLElement;
    canvasEl: HTMLCanvasElement;
    emptyEl: HTMLDivElement;
  } {
    const cardEl = document.createElement("section");
    cardEl.className = "metrics-chart-card";

    const titleEl = createTextElement("h3", "metrics-chart-title", title);
    const boxEl = document.createElement("div");
    boxEl.className = "metrics-chart-box";

    const canvasEl = document.createElement("canvas");
    canvasEl.setAttribute("aria-label", title);

    const emptyEl = createTextElement("div", "metrics-chart-empty", emptyText);
    boxEl.append(canvasEl, emptyEl);

    cardEl.append(titleEl, boxEl);
    return { cardEl, canvasEl, emptyEl };
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

  private setStatusMessage(message: string, isError: boolean): void {
    if (this.statusEl === null) {
      return;
    }
    this.statusEl.className = isError ? "metrics-status error" : "metrics-status";
    this.statusEl.replaceChildren(createTextElement("span", "", message));
  }

  private setErrorStatus(message: string): void {
    if (this.statusEl === null) {
      return;
    }
    this.statusEl.className = "metrics-status error";
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
    this.statusEl.className = "metrics-status hidden";
    this.statusEl.replaceChildren();
  }

  private renderSnapshotDom(snapshot: MetricsSnapshot): void {
    if (this.liveBadgeEl !== null) {
      this.liveBadgeEl.textContent = `Tick ${snapshot.tick} · ${snapshot.sim_time}`;
    }

    if (this.callsKpi !== null) {
      this.callsKpi.valueEl.textContent = formatCount(snapshot.total_calls);
      this.callsKpi.subEl.textContent = `Cache hits: ${formatCount(snapshot.cache_hits)}`;
    }

    if (this.cacheKpi !== null) {
      this.cacheKpi.valueEl.textContent = formatPercent(snapshot.cache_hit_rate);
      this.cacheKpi.subEl.textContent = `${formatCount(snapshot.cache_hits)} / ${formatCount(snapshot.total_calls)} calls`;
    }

    if (this.tokensKpi !== null) {
      this.tokensKpi.valueEl.textContent = formatCount(snapshot.total_tokens);
      this.tokensKpi.subEl.textContent = `In ${formatCount(snapshot.tokens_in)} · Out ${formatCount(snapshot.tokens_out)}`;
    }

    if (this.costKpi !== null) {
      this.costKpi.valueEl.textContent = formatUsd(snapshot.cost_est);
      this.costKpi.subEl.textContent = `Day ${snapshot.day} cumulative`;
    }

    if (this.avgLatencyKpi !== null) {
      this.avgLatencyKpi.valueEl.textContent = formatLatencyMs(
        snapshot.avg_latency_ms,
      );
      this.avgLatencyKpi.subEl.textContent = `Across ${formatCount(snapshot.total_calls)} calls`;
    }

    if (this.maxLatencyKpi !== null) {
      this.maxLatencyKpi.valueEl.textContent = formatLatencyMs(
        snapshot.max_latency_ms,
      );
      this.maxLatencyKpi.subEl.textContent = "Peak single call";
    }

    if (this.budgetTitleEl !== null) {
      this.budgetTitleEl.textContent = `Daily Budget (Budget Day ${snapshot.budget_day})`;
    }

    if (this.tokenBudgetMeter !== null) {
      const tokenPct = computeBudgetPercent(
        snapshot.budget_tokens_used,
        snapshot.daily_token_limit,
      );
      const tokenLimitText =
        snapshot.daily_token_limit > 0
          ? `${formatCount(snapshot.daily_token_limit)} (${tokenPct}%)`
          : "Unlimited";
      this.tokenBudgetMeter.valueEl.textContent = `${formatCount(snapshot.budget_tokens_used)} / ${tokenLimitText}`;
      this.tokenBudgetMeter.fillEl.style.width = `${Math.min(100, tokenPct)}%`;
      this.tokenBudgetMeter.fillEl.className = `metrics-budget-fill ${getBudgetTone(tokenPct)}`;
    }

    if (this.costBudgetMeter !== null) {
      const costPct = computeBudgetPercent(
        snapshot.budget_cost_used,
        snapshot.daily_budget_usd,
      );
      const costLimitText =
        snapshot.daily_budget_usd > 0
          ? `${formatUsd(snapshot.daily_budget_usd)} (${costPct}%)`
          : "Unlimited";
      this.costBudgetMeter.valueEl.textContent = `${formatUsd(snapshot.budget_cost_used)} / ${costLimitText}`;
      this.costBudgetMeter.fillEl.style.width = `${Math.min(100, costPct)}%`;
      this.costBudgetMeter.fillEl.className = `metrics-budget-fill ${getBudgetTone(costPct)}`;
    }

    this.toggleChartEmptyState(snapshot);
    this.renderModelRows(snapshot.by_model);
  }

  private toggleChartEmptyState(snapshot: MetricsSnapshot): void {
    if (this.historyEmptyEl !== null) {
      this.historyEmptyEl.classList.toggle("hidden", snapshot.history.length > 0);
    }
    const hasPurpose = snapshot.by_purpose.length > 0;
    if (this.purposeEmptyEl !== null) {
      this.purposeEmptyEl.classList.toggle("hidden", hasPurpose);
    }
    if (this.latencyEmptyEl !== null) {
      this.latencyEmptyEl.classList.toggle("hidden", hasPurpose);
    }
  }

  private renderModelRows(models: ModelMetrics[]): void {
    if (this.modelTableBodyEl === null) {
      return;
    }

    if (models.length === 0) {
      const row = document.createElement("tr");
      const cell = createTextElement(
        "td",
        "metrics-table-empty",
        "No model calls recorded yet.",
      );
      cell.colSpan = 6;
      row.appendChild(cell);
      this.modelTableBodyEl.replaceChildren(row);
      return;
    }

    const fragment = document.createDocumentFragment();
    for (const item of models) {
      const row = document.createElement("tr");
      row.append(
        createTextElement("td", "metrics-model-name", item.model),
        createTextElement("td", "metrics-num", formatCount(item.calls)),
        createTextElement("td", "metrics-num", formatCount(item.cache_hits)),
        createTextElement("td", "metrics-num", formatCount(item.total_tokens)),
        createTextElement("td", "metrics-num", item.avg_latency_ms.toFixed(1)),
        createTextElement("td", "metrics-num", formatUsd(item.cost_est)),
      );
      fragment.appendChild(row);
    }
    this.modelTableBodyEl.replaceChildren(fragment);
  }

  private hasAllCharts(): boolean {
    return (
      this.tokensChart !== null &&
      this.purposeChart !== null &&
      this.latencyChart !== null
    );
  }

  private scheduleChartSync(forceResize: boolean): void {
    this.cancelScheduledRaf();
    this.rafId = window.requestAnimationFrame(() => {
      this.rafId = null;
      if (this.disposed || !this.isOpen()) {
        return;
      }

      const snapshot = this.latestSnapshot;
      if (snapshot === null) {
        return;
      }

      this.ensureChartsCreated(snapshot);
      this.updateChartsInPlace(snapshot);

      if (forceResize) {
        this.tokensChart?.resize();
        this.purposeChart?.resize();
        this.latencyChart?.resize();
      }
    });
  }

  private ensureChartsCreated(snapshot: MetricsSnapshot): void {
    if (
      this.tokensChart === null &&
      this.historyCanvasEl !== null
    ) {
      this.tokensChart = this.createTokensChart(
        this.historyCanvasEl,
        snapshot.history,
      );
    }

    if (
      this.purposeChart === null &&
      this.purposeCanvasEl !== null
    ) {
      this.purposeChart = this.createPurposeChart(
        this.purposeCanvasEl,
        snapshot.by_purpose,
      );
    }

    if (
      this.latencyChart === null &&
      this.latencyCanvasEl !== null
    ) {
      this.latencyChart = this.createLatencyChart(
        this.latencyCanvasEl,
        snapshot.by_purpose,
      );
    }
  }

  private updateChartsInPlace(snapshot: MetricsSnapshot): void {
    if (this.tokensChart !== null) {
      const labels = snapshot.history.map((pt) => `Tick ${pt.tick}`);
      this.tokensChart.data.labels = labels;
      if (this.tokensChart.data.datasets[0] !== undefined) {
        this.tokensChart.data.datasets[0].data = snapshot.history.map(
          (pt) => pt.tokens_in,
        );
      }
      if (this.tokensChart.data.datasets[1] !== undefined) {
        this.tokensChart.data.datasets[1].data = snapshot.history.map(
          (pt) => pt.tokens_out,
        );
      }
      this.tokensChart.update("none");
    }

    if (this.purposeChart !== null) {
      const labels = snapshot.by_purpose.map((p) =>
        formatPurposeLabel(p.purpose),
      );
      this.purposeChart.data.labels = labels;
      if (this.purposeChart.data.datasets[0] !== undefined) {
        this.purposeChart.data.datasets[0].data = snapshot.by_purpose.map(
          (p) => p.total_tokens,
        );
      }
      if (this.purposeChart.data.datasets[1] !== undefined) {
        this.purposeChart.data.datasets[1].data = snapshot.by_purpose.map(
          (p) => p.calls,
        );
      }
      this.purposeChart.update("none");
    }

    if (this.latencyChart !== null) {
      const labels = snapshot.by_purpose.map((p) =>
        formatPurposeLabel(p.purpose),
      );
      this.latencyChart.data.labels = labels;
      if (this.latencyChart.data.datasets[0] !== undefined) {
        this.latencyChart.data.datasets[0].data = snapshot.by_purpose.map(
          (p) => Number(p.avg_latency_ms.toFixed(1)),
        );
      }
      this.latencyChart.update("none");
    }
  }

  private createTokensChart(
    canvas: HTMLCanvasElement,
    history: TickMetricsPoint[],
  ): Chart<"line", number[], string> {
    const config: ChartConfiguration<"line", number[], string> = {
      type: "line",
      data: {
        labels: history.map((pt) => `Tick ${pt.tick}`),
        datasets: [
          {
            label: "Tokens In",
            data: history.map((pt) => pt.tokens_in),
            borderColor: "#38bdf8",
            backgroundColor: "rgba(56, 189, 248, 0.16)",
            fill: true,
            tension: 0.25,
            pointRadius: 2,
            borderWidth: 2,
          },
          {
            label: "Tokens Out",
            data: history.map((pt) => pt.tokens_out),
            borderColor: "#10b981",
            backgroundColor: "rgba(16, 185, 129, 0.14)",
            fill: true,
            tension: 0.25,
            pointRadius: 2,
            borderWidth: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: "index",
          intersect: false,
        },
        plugins: {
          legend: {
            labels: {
              color: CHART_LEGEND_COLOR,
              boxWidth: 12,
            },
          },
        },
        scales: {
          x: {
            ticks: { color: CHART_TICK_COLOR, maxRotation: 0, autoSkip: true },
            grid: { color: CHART_GRID_COLOR },
          },
          y: {
            beginAtZero: true,
            ticks: { color: CHART_TICK_COLOR },
            grid: { color: CHART_GRID_COLOR },
          },
        },
      },
    };
    return new Chart(canvas, config);
  }

  private createPurposeChart(
    canvas: HTMLCanvasElement,
    byPurpose: PurposeMetrics[],
  ): Chart<"bar", number[], string> {
    const config: ChartConfiguration<"bar", number[], string> = {
      type: "bar",
      data: {
        labels: byPurpose.map((p) => formatPurposeLabel(p.purpose)),
        datasets: [
          {
            label: "Total Tokens",
            data: byPurpose.map((p) => p.total_tokens),
            backgroundColor: "rgba(56, 189, 248, 0.78)",
            borderColor: "#38bdf8",
            borderWidth: 1,
            borderRadius: 4,
            yAxisID: "y",
          },
          {
            label: "Calls",
            data: byPurpose.map((p) => p.calls),
            backgroundColor: "rgba(245, 158, 11, 0.8)",
            borderColor: "#f59e0b",
            borderWidth: 1,
            borderRadius: 4,
            yAxisID: "y1",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: "index",
          intersect: false,
        },
        plugins: {
          legend: {
            labels: {
              color: CHART_LEGEND_COLOR,
              boxWidth: 12,
            },
          },
        },
        scales: {
          x: {
            ticks: { color: CHART_TICK_COLOR },
            grid: { color: CHART_GRID_COLOR },
          },
          y: {
            type: "linear",
            position: "left",
            beginAtZero: true,
            ticks: { color: CHART_TICK_COLOR },
            grid: { color: CHART_GRID_COLOR },
            title: {
              display: true,
              text: "Tokens",
              color: CHART_TICK_COLOR,
            },
          },
          y1: {
            type: "linear",
            position: "right",
            beginAtZero: true,
            ticks: { color: CHART_TICK_COLOR, precision: 0 },
            grid: { drawOnChartArea: false },
            title: {
              display: true,
              text: "Calls",
              color: CHART_TICK_COLOR,
            },
          },
        },
      },
    };
    return new Chart(canvas, config);
  }

  private createLatencyChart(
    canvas: HTMLCanvasElement,
    byPurpose: PurposeMetrics[],
  ): Chart<"bar", number[], string> {
    const config: ChartConfiguration<"bar", number[], string> = {
      type: "bar",
      data: {
        labels: byPurpose.map((p) => formatPurposeLabel(p.purpose)),
        datasets: [
          {
            label: "Avg Latency (ms)",
            data: byPurpose.map((p) => Number(p.avg_latency_ms.toFixed(1))),
            backgroundColor: "rgba(168, 85, 247, 0.78)",
            borderColor: "#a855f7",
            borderWidth: 1,
            borderRadius: 4,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            labels: {
              color: CHART_LEGEND_COLOR,
              boxWidth: 12,
            },
          },
        },
        scales: {
          x: {
            ticks: { color: CHART_TICK_COLOR },
            grid: { color: CHART_GRID_COLOR },
          },
          y: {
            beginAtZero: true,
            ticks: { color: CHART_TICK_COLOR },
            grid: { color: CHART_GRID_COLOR },
          },
        },
      },
    };
    return new Chart(canvas, config);
  }
}
