// Corporate Actions tab: a dated event calendar (no rupee values).
import { state, getWatch, toggleWatch } from "./data.js";
import * as charts from "./charts.js";
import { $, el, fmtInt, fmtDate, downloadCsv, label } from "./util.js";
import { writeHash } from "./hash.js";

const f = { from: "", to: "", search: "", types: new Set(), watchOnly: false, sortKey: "ex_date", sortDir: 1 };
let filtered = [], isActive = false, built = false;

export function initCorp(params) {
  f.from = params.cafrom || ""; f.to = params.cato || "";
  f.search = params.caq || "";
  f.types = new Set((params.catypes || "").split(",").filter(Boolean));
  f.watchOnly = params.cawatch === "1";

  const types = [...new Set(state.corp.map((r) => r.category))].sort();
  buildChips("caTypeChips", types, f.types);
  $("#caFrom").value = f.from; $("#caTo").value = f.to; $("#caSearch").value = f.search;
  $("#caWatchOnly").checked = f.watchOnly;

  $("#caFrom").addEventListener("change", (e) => { f.from = e.target.value; render(); });
  $("#caTo").addEventListener("change", (e) => { f.to = e.target.value; render(); });
  $("#caSearch").addEventListener("input", (e) => { f.search = e.target.value; render(); });
  $("#caWatchOnly").addEventListener("change", (e) => { f.watchOnly = e.target.checked; render(); });
  $("#caReset").addEventListener("click", () => {
    f.from = f.to = f.search = ""; f.types.clear(); f.watchOnly = false;
    for (const c of document.querySelectorAll("#caTypeChips .chip.on")) c.classList.remove("on");
    $("#caFrom").value = ""; $("#caTo").value = ""; $("#caSearch").value = ""; $("#caWatchOnly").checked = false;
    render();
  });
  $("#caExportCsv").addEventListener("click", exportCsv);
  built = true;
}

export function showCorp(params) {
  if (!built) initCorp(params || {});
  isActive = true;
  render();
}
export function hideCorp() { isActive = false; }

function buildChips(id, codes, set) {
  const box = $("#" + id); box.innerHTML = "";
  for (const code of codes) {
    const chip = el("span", { class: "chip" }, label(code));
    if (set.has(code)) chip.classList.add("on");
    chip.addEventListener("click", () => { set.has(code) ? set.delete(code) : set.add(code); chip.classList.toggle("on"); render(); });
    box.append(chip);
  }
}

function applyFilters() {
  const watch = f.watchOnly ? getWatch() : null;
  const q = f.search.trim().toLowerCase();
  return state.corp.filter((r) => {
    if (f.from && (!r.ex_date || r.ex_date < f.from)) return false;
    if (f.to && (!r.ex_date || r.ex_date > f.to)) return false;
    if (f.types.size && !f.types.has(r.category)) return false;
    if (watch && !watch.has(r.company_norm)) return false;
    if (q && !r.company.toLowerCase().includes(q) && !(r.purpose || "").toLowerCase().includes(q)) return false;
    return true;
  });
}

function render() {
  filtered = applyFilters();
  renderKpis();
  renderCharts();
  renderTable();
  if (isActive) writeHash("corpactions", {
    cafrom: f.from, cato: f.to, caq: f.search, catypes: [...f.types], cawatch: f.watchOnly ? 1 : "",
  });
}

function renderKpis() {
  const today = new Date().toISOString().slice(0, 10);
  const upcoming = filtered.filter((r) => r.ex_date && r.ex_date >= today).length;
  const companies = new Set(filtered.map((r) => r.company_norm)).size;
  const byType = {};
  for (const r of filtered) byType[r.category] = (byType[r.category] || 0) + 1;
  const top = Object.entries(byType).sort((a, b) => b[1] - a[1])[0];
  const cards = [
    { label: "Events", value: fmtInt(filtered.length) },
    { label: "Companies", value: fmtInt(companies) },
    { label: "Upcoming (ex-date ≥ today)", value: fmtInt(upcoming) },
    { label: "Most common", value: top ? label(top[0]) : "—", sub: top ? top[1] + " events" : "" },
  ];
  $("#caKpis").innerHTML = "";
  for (const c of cards) $("#caKpis").append(el("div", { class: "kpi" }, [
    el("div", { class: "label" }, c.label), el("div", { class: "value" }, c.value),
    c.sub ? el("div", { class: "sub" }, c.sub) : null,
  ]));
}

function renderCharts() {
  const byType = new Map();
  for (const r of filtered) byType.set(r.category, (byType.get(r.category) || 0) + 1);
  charts.simpleBar("chartCaTypes", [...byType.entries()].sort((a, b) => b[1] - a[1]), label, "#4c9aff");

  const byMonth = new Map();
  for (const r of filtered) { if (!r.ex_date) continue; const m = r.ex_date.slice(0, 7); byMonth.set(m, (byMonth.get(m) || 0) + 1); }
  charts.simpleBar("chartCaMonth", [...byMonth.entries()].sort((a, b) => a[0].localeCompare(b[0])), null, "#2ecc8f");
}

const CA_COLS = [
  { key: "_star", t: "" }, { key: "company", t: "Company" }, { key: "purpose", t: "Purpose" },
  { key: "category", t: "Type" }, { key: "ex_date", t: "Ex-date" },
  { key: "record_date", t: "Record" }, { key: "payment_date", t: "Payment" },
];

function renderTable() {
  filtered.sort((a, b) => f.sortDir * String(a[f.sortKey] ?? "").localeCompare(String(b[f.sortKey] ?? "")));
  const table = $("#caTable");
  const head = el("tr", {}, CA_COLS.map((c) => {
    const th = el("th", { class: c.key === "_star" ? "" : "sortable" }, c.t + (f.sortKey === c.key ? (f.sortDir < 0 ? " ▼" : " ▲") : ""));
    if (c.key !== "_star") th.addEventListener("click", () => { f.sortKey === c.key ? (f.sortDir *= -1) : (f.sortKey = c.key, f.sortDir = 1); render(); });
    return th;
  }));
  table.replaceChildren(head);
  const watch = getWatch();
  const frag = document.createDocumentFragment();
  for (const r of filtered.slice(0, 800)) {
    const star = el("span", { class: "star" + (watch.has(r.company_norm) ? " on" : "") }, "★");
    star.addEventListener("click", () => { toggleWatch(r.company_norm); render(); });
    frag.append(el("tr", {}, [
      el("td", {}, star),
      el("td", {}, [el("div", {}, r.company), r.symbol ? el("small", {}, r.symbol) : null]),
      el("td", { title: r.purpose || "" }, r.purpose),
      el("td", {}, label(r.category)),
      el("td", {}, fmtDate(r.ex_date)),
      el("td", {}, fmtDate(r.record_date)),
      el("td", {}, fmtDate(r.payment_date)),
    ]));
  }
  table.append(frag);
  $("#caRowCount").textContent = `· ${fmtInt(filtered.length)} events`;
}

function exportCsv() {
  const rows = [["Company", "Symbol", "Security Code", "Purpose", "Type", "Ex-date", "Record date", "Payment date"]];
  for (const r of filtered) rows.push([r.company, r.symbol, r.security_code, r.purpose, label(r.category), r.ex_date || "", r.record_date || "", r.payment_date || ""]);
  downloadCsv("catalyst_tracker_corporate_actions.csv", rows);
}
