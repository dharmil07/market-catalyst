// Boot: load data, wire tabs, populate freshness + data-trust panel.
import { loadAll, state } from "./data.js";
import { initInsider, showInsider, hideInsider } from "./insider.js";
import { showCorp, hideCorp } from "./corpactions.js";
import { showPref, hidePref } from "./preferential.js";
import { parseHash } from "./hash.js";
import { initTheme } from "./theme.js";
import { $, el, fmtInt, fmtDate, label } from "./util.js";

const TABS = ["insider", "corpactions", "openoffers", "preferential"];
let currentTab = "insider";
let bootParams = {};

async function boot() {
  try {
    await loadAll();
  } catch (e) {
    document.querySelector("main").innerHTML =
      `<div class="empty">Could not load data files. Run <code>python3 pipeline/ingest.py</code> first, ` +
      `then serve this folder. <br><small>${e.message}</small></div>`;
    return;
  }

  renderFreshness();
  renderTrust();
  renderScaffold("openoffers", state.openoffers, "Open Offers");
  $("#genstamp").textContent = state.meta ? "data generated " + fmtIST(state.meta.generated_at) : "";

  const { tab, params } = parseHash();
  bootParams = params;
  initInsider(params);              // default tab is always prepared first
  wireTabs(params);
  switchTab(TABS.includes(tab) ? tab : "insider", params);

  // Theme picker: re-render the active tab so charts pick up new colours.
  initTheme(() => switchTab(currentTab, bootParams));
}

function wireTabs(params) {
  for (const btn of document.querySelectorAll(".tab")) {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab, params));
  }
}

function fmtIST(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString("en-IN", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
    hour12: true, timeZone: "Asia/Kolkata",
  }) + " IST";
}

function switchTab(tab, params) {
  currentTab = tab;
  for (const b of document.querySelectorAll(".tab")) b.classList.toggle("active", b.dataset.tab === tab);
  for (const s of document.querySelectorAll(".tabpanel")) s.classList.toggle("active", s.id === "tab-" + tab);
  hideInsider(); hideCorp(); hidePref();
  if (tab === "insider") showInsider();
  else if (tab === "corpactions") showCorp(params);
  else if (tab === "preferential") showPref(params);
}

function renderFreshness() {
  const m = state.meta; if (!m) return;
  const ib = m.sources.insider_bse, inn = m.sources.insider_nse, ca = m.corporate_actions;
  const pf = m.sources.preferential_nse;
  $("#freshness").innerHTML =
    `Insider BSE → <b>${fmtDate(ib.transaction_dates?.max)}</b> · ` +
    `NSE filed → <b>${fmtDate(inn.latest_intimation)}</b><br>` +
    `Corp actions → <b>${fmtDate(ca.event_dates?.min)} – ${fmtDate(ca.event_dates?.max)}</b>` +
    (pf ? ` · Pref issues → <b>${fmtDate(pf.allotment_dates?.max)}</b>` : "");
}

function renderTrust() {
  const m = state.meta; if (!m) return;
  const i = m.insider, vs = i.value_status || {};
  const card = (title, pairs) => {
    const box = el("div", { class: "tb" }, el("h4", {}, title));
    for (const [k, v] of pairs) box.append(el("div", {}, [el("span", {}, k), el("b", {}, String(v))]));
    return box;
  };
  $("#trustBody").replaceChildren(
    card("Insider sources", [
      ["BSE rows (raw)", fmtInt(m.sources.insider_bse.rows_raw)],
      ["NSE rows (raw)", fmtInt(m.sources.insider_nse.rows_raw)],
      ["BSE only", fmtInt(i.by_source.BSE || 0)],
      ["Matched BSE+NSE", fmtInt(i.by_source["BSE+NSE"] || 0)],
      ["NSE only", fmtInt(i.by_source.NSE || 0)],
    ]),
    card("De-duplication", [
      ["Within-BSE rows collapsed", fmtInt(i.within_bse.collapsed_rows || 0)],
      ["Within-BSE duplicate groups", fmtInt(i.within_bse.dup_groups || 0)],
      ["NSE rows merged into BSE", fmtInt(i.cross_feed.merged || 0)],
      ["NSE-only rows kept", fmtInt(i.cross_feed.nse_only || 0)],
    ]),
    card("Value quality (dashboard rows)", [
      ["Trusted", fmtInt(vs.ok || 0)],
      ["Repaired from twin", fmtInt(vs.repaired || 0)],
      ["Flagged & excluded", fmtInt(vs.flagged || 0)],
      ["No value reported", fmtInt(vs.novalue || 0)],
      ["Derivative (separate)", fmtInt(vs.derivative || 0)],
    ]),
    card("Coverage", [
      ["Insider date range", `${fmtDate(i.transaction_dates?.min)} – ${fmtDate(i.transaction_dates?.max)}`],
      i.served && i.served.window_months
        ? ["Dashboard window", `last ${i.served.window_months} months · ${fmtInt(i.served.records)} of ${fmtInt(i.records)} filings`]
        : null,
      ["BSE latest intimation", fmtDate(m.sources.insider_bse.latest_intimation)],
      ["NSE latest intimation", fmtDate(m.sources.insider_nse.latest_intimation)],
      ["Corp-action events", fmtInt(m.corporate_actions.records)],
      ["Corp actions matched BSE+NSE", fmtInt(m.corporate_actions.by_source?.["BSE+NSE"] || 0)],
      ["Corp actions NSE-only", fmtInt(m.corporate_actions.by_source?.NSE || 0)],
    ].filter(Boolean)),
  );
  const p = m.preferential;
  if (p && p.records) {
    const ps = p.amount_status || {};
    $("#trustBody").append(card("Preferential issues (NSE API)", [
      ["Filings", fmtInt(p.records)],
      ["Amounts cross-checked OK", fmtInt(ps.ok || 0)],
      ["Repaired (lakh-units error)", fmtInt(ps.repaired || 0)],
      ["Partly-paid (warrants)", fmtInt(ps.partial || 0)],
      ["No usable amount", fmtInt((ps.novalue || 0) + (ps.unverified || 0))],
    ]));
  }
  if (m.warnings && Object.keys(m.warnings).length) {
    $("#trustBody").append(card("⚠ Warnings", Object.entries(m.warnings).map(([k, v]) => [k, Array.isArray(v) ? v.join(", ") : v])));
  }
}

function renderScaffold(name, data, title) {
  const mount = $("#scaffold-" + name);
  if (data && data.length) {
    mount.innerHTML = `<h2>${title}</h2><p>${fmtInt(data.length)} records loaded.</p>`;
    return; // a future build can render a full table here
  }
  mount.innerHTML =
    `<h2>${title}</h2>` +
    `<p>This tab is scaffolded and ready. To populate it, drop an export into ` +
    `<code>data/raw/${name === "openoffers" ? "open_offers" : "preferential"}/</code> ` +
    `and re-run <code>./update.sh</code>.</p>` +
    `<p class="muted">The shared filter/table/chart framework will light up automatically once data is present.</p>`;
}

window.addEventListener("DOMContentLoaded", boot);
