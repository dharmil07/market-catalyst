// Thin wrapper over Chart.js (loaded globally as window.Chart) that keeps one
// instance per canvas and re-renders on filter changes.

const Chart = window.Chart;
const registry = new Map();

// Fixed, vivid data colours that read well on every theme.
const C = { buy: "#2ecc8f", sell: "#ff6b6b", accent: "#4c9aff" };
const PALETTE = ["#4c9aff", "#2ecc8f", "#f5a623", "#b98bff", "#ff6b6b", "#4dd0e1",
                 "#ffd54f", "#a5d6a7", "#f48fb1", "#90caf9"];

// Theme-driven colours, refreshed from CSS variables before each render.
let gridColor = "rgba(255,255,255,.06)";
let cardColor = "#1b232e";

Chart.defaults.font.family = "-apple-system, Segoe UI, Roboto, sans-serif";
Chart.defaults.font.size = 11;

const cssVar = (name, fallback) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

function syncTheme() {
  gridColor = cssVar("--grid", gridColor);
  cardColor = cssVar("--card", cardColor);
  const muted = cssVar("--muted", "");
  if (muted) Chart.defaults.color = muted;
}

function render(canvasId, config) {
  syncTheme();
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  if (registry.has(canvasId)) registry.get(canvasId).destroy();
  config.options = Object.assign({
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { labels: { boxWidth: 12 } } },
  }, config.options || {});
  registry.set(canvasId, new Chart(ctx, config));
}

const linScales = (stacked = false) => {
  const g = cssVar("--grid", gridColor);
  return {
    // No ticks.callback here: on the category axis of horizontal (indexAxis:"y")
    // charts an identity callback would bypass the index -> label mapping and
    // print bare row numbers instead of company names.
    x: { stacked, grid: { color: g } },
    y: { stacked, grid: { color: g } },
  };
};

export function dailyBuySell(id, series) {
  render(id, {
    type: "bar",
    data: {
      labels: series.map((s) => s[0]),
      datasets: [
        { label: "Buy", data: series.map((s) => +(s[1].buy / 1e7).toFixed(2)), backgroundColor: C.buy },
        { label: "Sell", data: series.map((s) => -(s[1].sell / 1e7).toFixed(2)), backgroundColor: C.sell },
      ],
    },
    options: { scales: linScales(true), plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${Math.abs(c.parsed.y)} cr` } } } },
  });
}

export function categoryDoughnut(id, entries, labelFn) {
  render(id, {
    type: "doughnut",
    data: {
      labels: entries.map((e) => labelFn(e[0])),
      datasets: [{ data: entries.map((e) => +(e[1] / 1e7).toFixed(2)), backgroundColor: PALETTE, borderColor: cssVar("--card", cardColor), borderWidth: 2 }],
    },
    options: { plugins: { legend: { position: "right" }, tooltip: { callbacks: { label: (c) => `${c.label}: ${c.parsed} cr` } } } },
  });
}

export function topBar(id, items, color) {
  render(id, {
    type: "bar",
    data: { labels: items.map((i) => i.label), datasets: [{ data: items.map((i) => +(i.value / 1e7).toFixed(2)), backgroundColor: color || C.accent }] },
    options: { indexAxis: "y", plugins: { legend: { display: false }, tooltip: { callbacks: {
      title: (ctx) => items[ctx[0].dataIndex].fullName,
      label: (c) => `${c.parsed.x} cr`,
    } } }, scales: linScales() },
  });
}

export function acqVsDisp(id, items) {
  render(id, {
    type: "bar",
    data: {
      labels: items.map((i) => i.label),
      datasets: [
        { label: "Acquired", data: items.map((i) => +(i.buy / 1e7).toFixed(2)), backgroundColor: C.buy },
        { label: "Disposed", data: items.map((i) => +(i.sell / 1e7).toFixed(2)), backgroundColor: C.sell },
      ],
    },
    options: { indexAxis: "y", scales: linScales(), plugins: { tooltip: { callbacks: {
      title: (ctx) => items[ctx[0].dataIndex].fullName,
      label: (c) => `${c.dataset.label}: ${c.parsed.x} cr`,
    } } } },
  });
}

export function netBar(id, items, positive) {
  render(id, {
    type: "bar",
    data: { labels: items.map((i) => i.label), datasets: [{ data: items.map((i) => +(Math.abs(i.value) / 1e7).toFixed(2)), backgroundColor: positive ? C.buy : C.sell }] },
    options: { indexAxis: "y", plugins: { legend: { display: false }, tooltip: { callbacks: {
      title: (ctx) => items[ctx[0].dataIndex].fullName,
      label: (c) => `${c.parsed.x} cr`,
    } } }, scales: linScales() },
  });
}

export function simpleBar(id, entries, labelFn, color) {
  render(id, {
    type: "bar",
    data: { labels: entries.map((e) => labelFn ? labelFn(e[0]) : e[0]), datasets: [{ data: entries.map((e) => e[1]), backgroundColor: color || C.accent }] },
    options: { plugins: { legend: { display: false } }, scales: linScales() },
  });
}
