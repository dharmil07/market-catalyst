// Preferential Issues tab: NSE further-issue filings (allotments + listings).
// Totals use issue_size (shares × offer price); amount_raised is display-only
// because the filer-entered figure is unreliable (see pipeline/parsers/nse_pref.py).
import { state, getWatch, toggleWatch } from "./data.js";
import * as charts from "./charts.js";
import { $, el, fmtInt, fmtCr, fmtDate, downloadCsv, daysAgoIso } from "./util.js";
import { writeHash } from "./hash.js";

const f = { from: "", to: "", search: "", watchOnly: false, sortKey: "date_allotment", sortDir: -1 };
let filtered = [], isActive = false, built = false, dataMax = "";

export function initPref(params) {
  const dates = state.preferential.map((r) => r.date_allotment).filter(Boolean).sort();
  dataMax = dates[dates.length - 1] || "";

  f.from = params.pffrom || ""; f.to = params.pfto || "";
  f.search = params.pfq || "";
  f.watchOnly = params.pfwatch === "1";

  if (!f.from && !f.to) { f.to = dataMax; f.from = daysAgoIso(182, dataMax); }

  $("#pfFrom").value = f.from; $("#pfTo").value = f.to; $("#pfSearch").value = f.search;
  $("#pfWatchOnly").checked = f.watchOnly;

  $("#pfFrom").addEventListener("change", (e) => { f.from = e.target.value; markPfPreset(null); render(); });
  $("#pfTo").addEventListener("change", (e) => { f.to = e.target.value; markPfPreset(null); render(); });
  $("#pfSearch").addEventListener("input", (e) => { f.search = e.target.value; render(); });
  $("#pfWatchOnly").addEventListener("change", (e) => { f.watchOnly = e.target.checked; render(); });
  $("#pfReset").addEventListener("click", () => {
    f.search = ""; f.watchOnly = false;
    f.to = ""; f.from = "";
    $("#pfFrom").value = f.from; $("#pfTo").value = f.to; $("#pfSearch").value = ""; $("#pfWatchOnly").checked = false;
    markPfPreset(document.querySelector('#pfDatePresets button[data-days="0"]'));
    render();
  });
  for (const b of document.querySelectorAll("#pfDatePresets button")) {
    b.addEventListener("click", () => {
      const days = Number(b.dataset.days);
      f.to = days ? dataMax : ""; f.from = days ? daysAgoIso(days, dataMax) : "";
      $("#pfFrom").value = f.from; $("#pfTo").value = f.to;
      markPfPreset(b); render();
    });
  }
  $("#pfExportCsv").addEventListener("click", exportCsv);
  built = true;
}

function markPfPreset(active) {
  for (const b of document.querySelectorAll("#pfDatePresets button")) b.classList.toggle("active", b === active);
}

export function showPref(params) {
  if (!built) initPref(params || {});
  isActive = true;
  render();
}
export function hidePref() { isActive = false; }

function applyFilters() {
  const watch = f.watchOnly ? getWatch() : null;
  const q = f.search.trim().toLowerCase();
  return state.preferential.filter((r) => {
    if (f.from && (!r.date_allotment || r.date_allotment < f.from)) return false;
    if (f.to && (!r.date_allotment || r.date_allotment > f.to)) return false;
    if (watch && !watch.has(r.company_norm)) return false;
    if (q && !r.company.toLowerCase().includes(q) && !(r.symbol || "").toLowerCase().includes(q)) return false;
    return true;
  });
}

function render() {
  filtered = applyFilters();
  renderKpis();
  renderCharts();
  renderTable();
  if (isActive) writeHash("preferential", {
    pffrom: f.from, pfto: f.to, pfq: f.search, pfwatch: f.watchOnly ? 1 : "",
  });
}

function renderKpis() {
  const today = new Date().toISOString().slice(0, 10);
  const total = filtered.reduce((s, r) => s + (r.issue_size || 0), 0);
  const companies = new Set(filtered.map((r) => r.company_norm)).size;
  const upcoming = filtered.filter((r) => r.date_listing && r.date_listing >= today).length;
  const repaired = filtered.filter((r) => r.amount_status === "repaired").length;
  const cards = [
    { label: "Issues", value: fmtInt(filtered.length) },
    { label: "Companies", value: fmtInt(companies) },
    { label: "Total issue size", value: fmtCr(total), sub: "shares × offer price" },
    { label: "Listing ≥ today", value: fmtInt(upcoming) },
    { label: "Amounts repaired", value: fmtInt(repaired), sub: "filer-entered figure off by 10⁴–10⁵×" },
  ];
  $("#pfKpis").innerHTML = "";
  for (const c of cards) $("#pfKpis").append(el("div", { class: "kpi" }, [
    el("div", { class: "label" }, c.label), el("div", { class: "value" }, c.value),
    c.sub ? el("div", { class: "sub" }, c.sub) : null,
  ]));
}

function renderCharts() {
  const byMonth = new Map();
  for (const r of filtered) {
    if (!r.date_allotment || !r.issue_size) continue;
    const m = r.date_allotment.slice(0, 7);
    byMonth.set(m, (byMonth.get(m) || 0) + r.issue_size);
  }
  charts.simpleBar("chartPfMonth",
    [...byMonth.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([m, v]) => [m, +(v / 1e7).toFixed(1)]),
    null, "#4c9aff");

  const top = filtered.filter((r) => r.issue_size)
    .sort((a, b) => b.issue_size - a.issue_size).slice(0, 12)
    .map((r) => ({ label: r.company.length > 28 ? r.company.slice(0, 27) + "…" : r.company, value: r.issue_size }));
  charts.topBar("chartPfTop", top, "#b98bff");
}

const PF_COLS = [
  { key: "_star", t: "" }, { key: "company", t: "Company" },
  { key: "date_allotment", t: "Allotment" }, { key: "date_listing", t: "Listing" },
  { key: "offer_price", t: "Offer ₹", num: true }, { key: "shares_allotted", t: "Shares", num: true },
  { key: "issue_size", t: "Issue size", num: true }, { key: "amount_raised", t: "Paid-in", num: true },
  { key: "stage", t: "Stage" }, { key: "_doc", t: "Doc" },
];

function amountCell(r) {
  if (r.amount_status === "repaired")
    return el("span", { class: "flag repaired", title: "Filer-entered amount was implausible (lakh-units error); repaired to shares × offer price" }, "✎ " + fmtCr(r.amount_raised));
  if (r.amount_status === "partial")
    return el("span", { title: "Partly-paid issue (e.g. warrants): upfront money only, rest due on conversion" }, fmtCr(r.amount_raised) + " ◐");
  if (r.amount_status === "unverified")
    return el("span", { class: "flag flagged", title: "No shares/price to cross-check this amount — not counted in totals" }, "⚠ " + fmtCr(r.amount_raised));
  return fmtCr(r.amount_raised);
}

function renderTable() {
  const dir = f.sortDir;
  filtered.sort((a, b) => {
    const x = a[f.sortKey], y = b[f.sortKey];
    if (typeof x === "number" || typeof y === "number") return dir * ((x ?? -Infinity) - (y ?? -Infinity));
    return dir * String(x ?? "").localeCompare(String(y ?? ""));
  });
  const table = $("#pfTable");
  const head = el("tr", {}, PF_COLS.map((c) => {
    const th = el("th", { class: (c.key.startsWith("_") ? "" : "sortable ") + (c.num ? "num" : "") },
      c.t + (f.sortKey === c.key ? (f.sortDir < 0 ? " ▼" : " ▲") : ""));
    if (!c.key.startsWith("_")) th.addEventListener("click", () => { f.sortKey === c.key ? (f.sortDir *= -1) : (f.sortKey = c.key, f.sortDir = c.num ? -1 : 1); render(); });
    return th;
  }));
  table.replaceChildren(head);
  const watch = getWatch();
  const frag = document.createDocumentFragment();
  for (const r of filtered.slice(0, 600)) {
    const star = el("span", { class: "star" + (watch.has(r.company_norm) ? " on" : "") }, "★");
    star.addEventListener("click", () => { toggleWatch(r.company_norm); render(); });
    const doc = r.xbrl ? el("a", { href: r.xbrl, target: "_blank", rel: "noopener", title: "Original XBRL filing" }, "🔗") : "";
    frag.append(el("tr", {}, [
      el("td", {}, star),
      el("td", {}, [el("div", {}, r.company), r.symbol ? el("small", {}, r.symbol) : null]),
      el("td", {}, fmtDate(r.date_allotment)),
      el("td", {}, fmtDate(r.date_listing)),
      el("td", { class: "num" }, r.offer_price == null ? "—" : r.offer_price.toLocaleString("en-IN")),
      el("td", { class: "num" }, fmtInt(r.shares_allotted)),
      el("td", { class: "num" }, fmtCr(r.issue_size)),
      el("td", { class: "num" }, amountCell(r)),
      el("td", {}, r.stage),
      el("td", {}, doc),
    ]));
  }
  table.append(frag);
  $("#pfRowCount").textContent = `· ${fmtInt(filtered.length)} issues`;
}

function exportCsv() {
  const rows = [["Company", "Symbol", "ISIN", "Allotment date", "Listing date", "Offer price",
                 "Shares allotted", "Issue size (₹)", "Amount paid-in (₹)", "Amount status", "Stage", "XBRL"]];
  for (const r of filtered) rows.push([
    r.company, r.symbol, r.isin, r.date_allotment || "", r.date_listing || "",
    r.offer_price ?? "", r.shares_allotted ?? "", r.issue_size ?? "", r.amount_raised ?? "",
    r.amount_status, r.stage, r.xbrl || ""]);
  downloadCsv("catalyst_tracker_preferential_issues.csv", rows);
}
