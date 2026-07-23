# Market Catalyst — Build Plan

> Originally built as "PromoterPulse"; renamed to **Market Catalyst** (repo `market-catalyst`).

## Context

Replace a manual Excel workflow (download BSE/NSE insider-trading CSVs → paste into a
master sheet → Power Query + pivots) with a free, self-hosted static dashboard that is
*better* than the reference site (https://ketalyst-cm.github.io/market-dashboards/insider-trading/dashboard.html),
shaped around how the user actually analyzes the data.

The user works in cybersecurity (technically comfortable) but is **new to Git/GitHub**, so
repo creation, structure, and deploy are handled here as much as tooling allows, with plain
explanations for the one interactive step that can't be automated (`gh auth login`).

## Decisions (locked with the user)

| Topic | Decision |
|---|---|
| Data refresh | **Manual upload, automation-ready.** Drop new CSVs, run one command. No live scraper (BSE/NSE block automation; would be fragile). Pipeline structured so a scheduled scraper can be added later. |
| Scope | **Multi-category from the start**, category-agnostic core. |
| Categories | **Insider Trading** (full) + **Corporate Actions** (full, from BSE calendar file) + **Preferential Issues** (full, fetched from NSE's JSON API by `pipeline/fetch_nse_pref.py`) + **Open Offers** (scaffolded, wired when user supplies exports). |
| Cross-exchange | **BSE = primary, NSE = secondary.** Verified: 1,103/1,592 (69%) NSE rows match a BSE row on normalized (company, person, from-date, shares); 96.5% of those agree on value. |
| Audience | Personal tool, **public** static site is fine. |
| Hosting | **GitHub Pages** (free, deploy from branch, `/docs` folder). |
| Processing | **Python pipeline → clean JSON** committed to repo; static JS frontend loads JSON. Real CSVs used as test fixtures. |
| Bad values | **Repair from twin, else flag & exclude** from value totals (still counted). Never fabricate. |
| Dedup | Keep BSE row; drop NSE duplicate but **attach NSE's XBRL link + Regulation + broadcast time** to it. Source badge = BSE / NSE / BSE+NSE. |
| Priority features | (1) Signal filters: market-only / promoter-only / cluster-buys. (2) Insider × Corporate-Actions cross-reference. (3) Pledge risk tracking. (4) Auto value-sanitization + data-trust panel. |

## Data realities verified against the real samples

- BSE insider: 4,815 rows, 26 cols, 769 companies. NSE insider: 1,592 rows, 29 cols, 360 companies.
- Exact uppercase company-name overlap = **1** → normalization (Ltd↔Limited, punctuation, case) is mandatory.
- Vocabulary mismatches to normalize: txn type (Acquisition/Buy, Disposal/Sell/Sale, Pledge/Revoke/Invoke variants);
  category (KMP↔Key Managerial Personnel, Promoter↔Promoters, Promoter & Director↔Promoter and Director, etc.);
  mode (Creation Of Pledge↔Pledge Creation, Inter-se Transfer↔Inter-se-Transfer, Revokation of Pledge↔Revokation, etc.).
- 764 within-BSE duplicate rows across 346 keys. 64 BSE rows with placeholder value (≤₹10 on large share counts).
- 33 BSE derivative-only rows (blank share/value) → separate handling.
- Date hygiene: BSE dates reach back to 2015 (101 rows pre-Dec-2025); NSE's latest row is 2026-04-30 (~6 wks before
  its filename) → freshness must be measured from data, shown in a coverage panel, not trusted from filename.
- Corporate Actions file: 675 rows, ex-date/record-date **calendar** (no value/volume). Purpose buckets: Dividend 466,
  Rights 53, Bonus 46, Split 32, Buyback 17, REIT/InvIT 43, Merger/Demerger 5, misc ~13.

## Architecture

```
market-catalyst/
  data/raw/                      # canonical inputs (user drops new exports here)
    insider/bse/*.csv  insider/nse/*.csv
    corporate_actions/bse/*.csv
    open_offers/  preferential/  # await user exports
  pipeline/
    ingest.py                    # entry point: raw/ -> docs/data/*.json
    parsers/  (bse_insider, nse_insider, bse_corpactions, ...)
    normalize.py                 # company/person/date + controlled-vocab maps + market-mode flag
    match.py                     # within-feed + cross-feed dedup, source tagging, NSE extras attach
    sanitize.py                  # placeholder detect, twin-repair, flag&exclude, derivative tagging
    aggregate.py                 # meta/coverage stats (heavy/global precompute)
  tests/                         # pytest; fixtures = the real sample CSVs
    test_normalize / test_match / test_sanitize / test_aggregate
  docs/                          # GitHub Pages serves THIS folder
    index.html  css/  js/(app, filters, charts, table, watchlist, crossref)
    lib/chart.umd.js             # vendored, no build step
    data/  insider.json  corporate_actions.json  open_offers.json  preferential.json  meta.json
  update.sh                      # run ingest + git add/commit/push in one go
  requirements.txt  README.md  .gitignore  .venv/(ignored)
```

Frontend ships **transaction-level JSON** (~5k insider records, small) and aggregates **in-browser**
so all filters recompute net buyers/sellers etc. live. Vanilla HTML/CSS/JS, vendored Chart.js, no build step.

## Pipeline behavior (key logic)

- **normalize.py**: `normco` (upper, strip punctuation + corp suffixes, collapse ws), `normp`, multi-format
  date→ISO, comma-number→float. Controlled-vocab dicts → canonical txn_type, category, mode. `is_market` flag
  (Market Purchase/Sale = true; ESOP/Gift/Inter-se/Off-Market/Allotment/Preferential/Conversion = false).
- **match.py**: key = (normco, normp, from_date, shares). Collapse within-BSE groups (prefer sane-value,
  non-derivative row; record dup_count). Index BSE; each NSE row either merges into its BSE twin (attach
  xbrl/regulation/broadcast, mark source BSE+NSE) or is added as NSE-only. Exact match first; ±1–2 day
  date-slack left as a config hook for later.
- **sanitize.py**: implied_price = value/shares; flag value if ≤₹10 on large shares OR ≪ security's median
  implied price. If twin has sane value → use it (value_repaired). Else value_flagged + excluded from value
  totals (counts unaffected). Derivative-only rows tagged, kept in a separate view.
- **aggregate.py / meta.json**: per-source counts, actual date ranges, latest filing per source, # merged,
  # repaired, # flagged → drives the data-trust panel.

## Frontend (tabs)

- **Insider Trading (full):** Filters (date range, txn type, category[multi], mode[multi]) + quick toggles
  (Market-only, Promoter-only, Exclude non-market). KPIs (total acq/disposal/net value, #companies, #filings,
  freshness). Charts: buy-vs-sell daily value; top companies by acquisition; acquisition-vs-disposal by company;
  top net buyers / net sellers (₹ cr); category breakdown. Panels: **cluster-buying** (≥N distinct insiders
  buying same company in window), **pledge risk** (net create vs revoke/invoke, % pledged, rising-pledge),
  **cross-reference** (companies with insider buying AND an upcoming corporate action, joined on Security Code).
  Sortable/searchable table with flag icons (repaired/flagged), source badge, XBRL click-through. CSV export of
  filtered view. Watchlist (localStorage). Deep-link filter state in URL hash. Data-trust panel from meta.json.
- **Corporate Actions (full):** bucketed-type + date + company filters; upcoming ex/record/payment date
  calendar+table; watchlist integration.
- **Open Offers / Preferential (scaffolded):** same shell wired to empty JSON; "awaiting data" state.

## Replicated Excel baseline (built regardless)

Per-company totals for acquisition/disposal/pledge/invoke/revoke (count AND value); ranked net buyers & net
sellers in crores; charts for total acquisition by company, acquisition-vs-disposal by company, net value for
top movers.

## Git / GitHub / deploy

1. Local: `git init`, `.gitignore` (.venv, __pycache__), structure, first commit — automated here.
2. Remote: requires **one** interactive step by the user — `! gh auth login` (browser login; needs a free
   GitHub account). After that, repo creation + push + Pages enablement are automated via `gh`. Fallback if
   `gh` is declined: user creates an empty public repo in browser; guided push instead.
3. Pages: enable Pages → deploy from `main` / `/docs` (via `gh` API or guided clicks). Site URL:
   `https://<user>.github.io/market-catalyst/`.
4. Refresh workflow: drop new CSVs in `data/raw/...` → run `./update.sh` (ingest → regenerate JSON → commit →
   push) → Pages redeploys automatically.

## Verification

- `pytest` over fixtures asserts the known truths: ~346 within-BSE dup keys collapse; ~1,103 NSE rows match BSE;
  the 64 placeholder rows are flagged; vocab maps cover all observed values; date parsing handles all formats.
- Run `python pipeline/ingest.py` on the real samples; sanity-check meta.json (counts, ranges, freshness).
- Serve `docs/` locally (`python -m http.server`), confirm each tab, filters, charts, cross-ref, watchlist,
  CSV export, and deep-links work; confirm net-buyer/seller numbers reconcile with the Excel sheet on a spot check.

## Open items needing user input later

- Open Offers exports (filenames once dropped in `data/raw/open_offers/`).
  (Preferential Issues no longer need exports — fetched from the NSE API.)
- A second/third month of data to confirm BSE-primary + matching assumptions hold over time.
