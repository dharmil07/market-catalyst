// Insider Trading tab: filters -> KPIs, charts, signal panels, table, CSV.
import {
  state, applyInsiderFilters, totals, byCompany, dailySeries, categoryValue,
  clusterBuying, pledgeActivity, crossref, getWatch, toggleWatch,
} from "./data.js";
import * as charts from "./charts.js";
import {
  $, el, fmtCr, fmtInt, fmtPct, fmtDate, daysAgoIso, downloadCsv, label,
} from "./util.js";
import { writeHash } from "./hash.js";

const TYPE_ORDER = ["BUY", "SELL", "PLEDGE", "REVOKE", "INVOKE"];

const f = {
  from: "", to: "", types: new Set(), cats: new Set(), modes: new Set(),
  marketOnly: false, promoterOnly: false, watchOnly: false, search: "",
  sortKey: "date_from", sortDir: -1,
};
let dataMax = "", filtered = [];
let isActive = false;

export function initInsider(params) {
  // distinct categories / modes present in the data, for filter chips
  const cats = [...new Set(state.insider.map((r) => r.category))].sort();
  const modes = [...new Set(state.insider.map((r) => r.mode))].sort();
  const types = TYPE_ORDER.filter((t) => state.insider.some((r) => r.txn_type === t));
  const dates = state.insider.map((r) => r.date_from).filter(Boolean).sort();
  dataMax = dates[dates.length - 1] || "";

  hydrate(params);
  if (!f.from && !f.to) { f.to = dataMax; f.from = daysAgoIso(90, dataMax); }

  buildChips("typeChips", types, f.types, (c) => c.toLowerCase());
  buildChips("catChips", cats, f.cats);
  buildChips("modeChips", modes, f.modes);
  wireControls();
  syncControls();
  render();
}

export function showInsider() { isActive = true; render(); }
export function hideInsider() { isActive = false; }

/* --------------------------- hash <-> state --------------------------- */
function hydrate(p) {
  if (p.from) f.from = p.from;
  if (p.to) f.to = p.to;
  f.types = new Set((p.types || "").split(",").filter(Boolean));
  f.cats = new Set((p.cats || "").split(",").filter(Boolean));
  f.modes = new Set((p.modes || "").split(",").filter(Boolean));
  f.marketOnly = p.market === "1";
  f.promoterOnly = p.promoter === "1";
  f.watchOnly = p.watch === "1";
  f.search = p.q || "";
  if (p.sort) f.sortKey = p.sort;
  if (p.dir) f.sortDir = Number(p.dir);
}
function persist() {
  if (!isActive) return;
  writeHash("insider", {
    from: f.from, to: f.to, types: [...f.types], cats: [...f.cats], modes: [...f.modes],
    market: f.marketOnly ? 1 : "", promoter: f.promoterOnly ? 1 : "", watch: f.watchOnly ? 1 : "",
    q: f.search, sort: f.sortKey, dir: f.sortDir,
  });
}

/* ------------------------------- chips -------------------------------- */
function buildChips(id, codes, set, clsFn) {
  const box = $("#" + id);
  box.innerHTML = "";
  for (const code of codes) {
    const chip = el("span", { class: "chip " + (clsFn ? clsFn(code) : "") }, label(code));
    if (set.has(code)) chip.classList.add("on");
    chip.addEventListener("click", () => {
      set.has(code) ? set.delete(code) : set.add(code);
      chip.classList.toggle("on");
      render();
    });
    box.append(chip);
  }
}

/* ------------------------------ controls ------------------------------ */
function wireControls() {
  $("#dateFrom").addEventListener("change", (e) => { f.from = e.target.value; markPreset(null); render(); });
  $("#dateTo").addEventListener("change", (e) => { f.to = e.target.value; markPreset(null); render(); });
  $("#search").addEventListener("input", debounce((e) => { f.search = e.target.value; render(); }, 200));
  $("#marketOnly").addEventListener("change", (e) => { f.marketOnly = e.target.checked; render(); });
  $("#promoterOnly").addEventListener("change", (e) => { f.promoterOnly = e.target.checked; render(); });
  $("#watchOnly").addEventListener("change", (e) => { f.watchOnly = e.target.checked; render(); });
  $("#resetFilters").addEventListener("click", resetFilters);
  $("#exportCsv").addEventListener("click", exportCsv);
  $("#copyLink").addEventListener("click", copyLink);
  for (const b of document.querySelectorAll("#datePresets button")) {
    b.addEventListener("click", () => {
      const days = Number(b.dataset.days);
      f.to = days ? dataMax : ""; f.from = days ? daysAgoIso(days, dataMax) : "";
      markPreset(b); syncControls(); render();
    });
  }
}
function markPreset(active) {
  for (const b of document.querySelectorAll("#datePresets button")) b.classList.toggle("active", b === active);
}
function syncControls() {
  $("#dateFrom").value = f.from; $("#dateTo").value = f.to;
  $("#search").value = f.search;
  $("#marketOnly").checked = f.marketOnly;
  $("#promoterOnly").checked = f.promoterOnly;
  $("#watchOnly").checked = f.watchOnly;
}
function resetFilters() {
  f.types.clear(); f.cats.clear(); f.modes.clear();
  f.marketOnly = f.promoterOnly = f.watchOnly = false; f.search = "";
  f.to = dataMax; f.from = daysAgoIso(90, dataMax);
  for (const c of document.querySelectorAll(".chip.on")) c.classList.remove("on");
  markPreset(document.querySelector('#datePresets button[data-days="90"]'));
  syncControls(); render();
}
function copyLink() {
  persist();
  navigator.clipboard?.writeText(location.href).then(() => {
    const btn = $("#copyLink"); const t = btn.textContent;
    btn.textContent = "✓ Copied"; setTimeout(() => (btn.textContent = t), 1400);
  });
}

/* ------------------------------- render ------------------------------- */
function render() {
  filtered = applyInsiderFilters(state.insider, f);
  renderKpis();
  renderCharts();
  renderPanels();
  renderTable();
  $("#watchCount").textContent = getWatch().size || "";
  persist();
}

function renderKpis() {
  const t = totals(filtered);
  const cards = [
    { label: "Net value", value: fmtCr(t.net), cls: t.net >= 0 ? "buy" : "sell", sub: "acquired − disposed" },
    { label: "Total acquired", value: fmtCr(t.buy), cls: "buy" },
    { label: "Total disposed", value: fmtCr(t.sell), cls: "sell" },
    { label: "Companies", value: fmtInt(t.companies) },
    { label: "Filings", value: fmtInt(t.rows) },
    { label: "Flagged values", value: fmtInt(t.flagged), sub: "excluded from totals" },
  ];
  $("#insiderKpis").innerHTML = "";
  for (const c of cards) {
    $("#insiderKpis").append(el("div", { class: "kpi" }, [
      el("div", { class: "label" }, c.label),
      el("div", { class: "value " + (c.cls || "") }, c.value),
      c.sub ? el("div", { class: "sub" }, c.sub) : null,
    ]));
  }
}

function topN(map, key, n = 10, positive = true) {
  return [...map.values()]
    .filter((e) => (positive ? e[key] > 0 : e[key] < 0))
    .sort((a, b) => (positive ? b[key] - a[key] : a[key] - b[key]))
    .slice(0, n)
    .map((e) => ({ label: e.name.length > 22 ? e.name.slice(0, 21) + "…" : e.name, value: e[key], buy: e.buy, sell: e.sell }));
}

function renderCharts() {
  const m = byCompany(filtered);
  charts.dailyBuySell("chartDaily", dailySeries(filtered));
  charts.categoryDoughnut("chartCategory", categoryValue(filtered).slice(0, 9), label);
  charts.topBar("chartTopAcq", topN(m, "buy", 10), "#2ecc8f");
  charts.acqVsDisp("chartAcqDisp", topN(m, "buy", 10));
  charts.netBar("chartNetBuyers", topN(m, "net", 10, true), true);
  charts.netBar("chartNetSellers", topN(m, "net", 10, false), false);
}

function miniTable(rows, headers) {
  if (!rows.length) return el("div", { class: "empty" }, "No matching activity in this view.");
  const t = el("table", { class: "mini-table" });
  t.append(el("tr", {}, headers.map((h) => el("th", { class: h.num ? "num" : "" }, h.t))));
  for (const r of rows) t.append(el("tr", {}, r.map((c, i) => el("td", { class: headers[i].num ? "num" : "" }, c))));
  return t;
}

function renderPanels() {
  const cluster = clusterBuying(filtered).slice(0, 15)
    .map((c) => [c.name, String(c.buyers), fmtCr(c.value)]);
  $("#panelCluster").replaceChildren(miniTable(cluster,
    [{ t: "Company" }, { t: "Insiders", num: true }, { t: "Buy value", num: true }]));

  const pledge = pledgeActivity(filtered).slice(0, 15)
    .map((p) => [p.name, fmtInt(p.created), fmtInt(p.released), String(p.events)]);
  $("#panelPledge").replaceChildren(miniTable(pledge,
    [{ t: "Company" }, { t: "Pledged sh.", num: true }, { t: "Released sh.", num: true }, { t: "Events", num: true }]));

  const cross = crossref(filtered, state.corp).slice(0, 25)
    .map((c) => [c.name, fmtCr(c.net), label(c.action), fmtDate(c.date)]);
  $("#panelCrossref").replaceChildren(miniTable(cross,
    [{ t: "Company" }, { t: "Net buy", num: true }, { t: "Action" }, { t: "Ex-date" }]));
}

/* -------------------------------- table ------------------------------- */
const COLS = [
  { key: "_star", t: "", sortable: false },
  { key: "date_from", t: "Date" },
  { key: "company", t: "Company" },
  { key: "person", t: "Person" },
  { key: "category", t: "Category" },
  { key: "txn_type", t: "Type" },
  { key: "mode", t: "Mode" },
  { key: "shares", t: "Shares", num: true },
  { key: "value", t: "Value", num: true },
  { key: "post_pct", t: "% Post", num: true },
  { key: "source", t: "Src" },
  { key: "_doc", t: "Doc", sortable: false },
];
const RENDER_CAP = 600;

function sortFiltered() {
  const k = f.sortKey, dir = f.sortDir;
  filtered.sort((a, b) => {
    let x = a[k], y = b[k];
    x = x == null ? -Infinity : x; y = y == null ? -Infinity : y;
    if (typeof x === "string" || typeof y === "string") return dir * String(x).localeCompare(String(y));
    return dir * (x - y);
  });
}

function renderTable() {
  sortFiltered();
  const table = $("#insiderTable");
  const head = el("tr", {}, COLS.map((c) => {
    const th = el("th", { class: (c.num ? "num " : "") + (c.sortable === false ? "" : "sortable") },
      c.t + (f.sortKey === c.key ? (f.sortDir < 0 ? " ▼" : " ▲") : ""));
    if (c.sortable !== false) th.addEventListener("click", () => {
      if (f.sortKey === c.key) f.sortDir *= -1; else { f.sortKey = c.key; f.sortDir = c.num ? -1 : 1; }
      render();
    });
    return th;
  }));
  table.replaceChildren(head);

  const watch = getWatch();
  const rows = filtered.slice(0, RENDER_CAP);
  const frag = document.createDocumentFragment();
  for (const r of rows) {
    const star = el("span", { class: "star" + (watch.has(r.company_norm) ? " on" : ""), title: "Add to watchlist" }, "★");
    star.addEventListener("click", () => { toggleWatch(r.company_norm); render(); });

    let valueCell;
    if (r.value_status === "flagged") valueCell = el("span", { class: "flag flagged", title: "Suspicious placeholder value — excluded" }, "⚠ —");
    else if (r.value_status === "repaired") valueCell = el("span", { class: "flag repaired", title: "Repaired from a matching twin row" }, "✎ " + fmtCr(r.value));
    else if (r.value_in_totals) valueCell = document.createTextNode(fmtCr(r.value));
    else valueCell = document.createTextNode("—");

    const typeTag = el("span", { class: "tag " + r.txn_type.toLowerCase() }, label(r.txn_type));
    const doc = r.xbrl ? el("a", { href: r.xbrl, target: "_blank", rel: "noopener", title: "Original XBRL filing" }, "🔗")
                       : document.createTextNode("");
    const companyCell = el("td", {}, [
      el("div", {}, r.company),
      (r.symbol || r.security_code) ? el("small", {}, r.symbol || r.security_code) : null,
    ]);

    const tr = el("tr", {}, [
      el("td", {}, star),
      el("td", {}, fmtDate(r.date_from)),
      companyCell,
      el("td", {}, r.person),
      el("td", {}, label(r.category)),
      el("td", {}, typeTag),
      el("td", {}, label(r.mode)),
      el("td", { class: "num" }, fmtInt(r.shares)),
      el("td", { class: "num" }, valueCell),
      el("td", { class: "num" }, fmtPct(r.post_pct)),
      el("td", {}, el("span", { class: "src", title: r.source }, r.source)),
      el("td", {}, doc),
    ]);
    frag.append(tr);
  }
  table.append(frag);

  const note = filtered.length > RENDER_CAP ? ` (showing first ${RENDER_CAP})` : "";
  $("#rowCount").textContent = `· ${fmtInt(filtered.length)} rows${note}`;
}

function exportCsv() {
  const header = ["Date", "Company", "Symbol/Code", "Person", "Category", "Type", "Mode",
    "Shares", "Value (Rs)", "Value status", "% Post", "Source", "Regulation", "XBRL"];
  const rows = [header];
  for (const r of filtered) {
    rows.push([r.date_from, r.company, r.symbol || r.security_code, r.person, label(r.category),
      label(r.txn_type), label(r.mode), r.shares ?? "", r.value_in_totals ? r.value : "",
      r.value_status, r.post_pct ?? "", r.source, r.regulation || "", r.xbrl || ""]);
  }
  downloadCsv("catalyst_tracker_insider.csv", rows);
}

function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
