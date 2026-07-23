# Market Catalyst

A free, self-hosted dashboard for **Indian insider-trading disclosures and corporate
actions**, built from BSE & NSE exports. It replaces a manual Excel + Power Query
workflow: drop in the exchange CSVs, run one command, and get a filterable dashboard
with charts, signal panels, and CSV export — deployable as a static site on GitHub Pages.

> Data is informational only and **not investment advice**.

---

## What it does

- **Insider Trading** (BSE primary, NSE secondary) — net buyers/sellers in ₹cr, per-company
  acquisition/disposal/pledge totals, daily buy-vs-sell, category breakdown, and your full
  Excel views, plus:
  - **Signal filters** — *Market trades only* (strips ESOP/gift/inter-se noise), *Promoters only*,
    and **cluster buying** detection (multiple distinct insiders buying the same company).
  - **Pledge activity** — shares pledged vs released per company.
  - **Insider × Corporate Action** cross-reference — companies appearing in both feeds.
  - **Auto value-sanitization** — repairs placeholder values (e.g. 696,000 shares "worth ₹3")
    from a matching twin row, or flags & excludes them so rankings stay clean.
  - **Data-quality & coverage panel** — exactly what was merged, repaired, flagged, and how fresh
    each source is.
- **Corporate Actions** — dividends, bonus, splits, rights, buybacks, mergers/demergers,
  REIT/InvIT distributions, with an ex-date/record-date calendar.
- **Preferential Issues** — allotments, offer price, issue size, and listing dates pulled
  straight from NSE's JSON API (`pipeline/fetch_nse_pref.py`), with lakh-units filing errors
  auto-repaired against shares × offer price.
- **Open Offers** — scaffolded tab, ready to populate (see below).
- Watchlist (saved in your browser), shareable deep-links, and CSV export on every table.

---

## How the data flows

```
data/raw/**/*.csv  ──►  python3 pipeline/ingest.py  ──►  docs/data/*.json  ──►  docs/ (static site)
   (you drop here)         normalize → sanitize →            (committed)         (GitHub Pages)
                           dedup → cross-feed merge
```

All processing is **standard-library Python** (no dependencies). The browser loads the generated
JSON and does all filtering/aggregation client-side.

### Updating the data

1. Download fresh exports:
   - BSE insider: <https://www.bseindia.com/corporates/insider_trading_new>
   - NSE insider: <https://www.nseindia.com/companies-listing/corporate-filings-insider-trading>
   - BSE corporate actions: <https://www.bseindia.com/corporates/corporate_act>
   - NSE corporate actions: <https://www.nseindia.com/companies-listing/corporate-actions>
2. Put them in the matching folder (filenames don't matter; all CSVs in a folder are read,
   and overlapping date ranges are fine — duplicates collapse in the dedup step):
   - `data/raw/insider/bse/`
   - `data/raw/insider/nse/` — use the regular *Insider Trading* export; the "Annual PIT"
     export (what the website serves for 1-year ranges) is a coarser, incompatible format
     and the pipeline rejects it with an error. Easier: skip the manual download and run
     `python3 pipeline/fetch_nse_insider.py` — it pulls the regular format straight from
     the NSE API in 3-month chunks (`./update.sh --fetch` does this too).

     **Known upstream gap (as of Jul 2026):** NSE stopped feeding the regular dataset on
     02-May-2026 and now publishes insider filings only in the coarse "PIT Annual" system
     (no symbol/mode/XBRL; sales merged with pledge invocations — the very reasons the
     pipeline rejects that format). Decision: stay BSE-covered — dual-listed companies are
     fully current via BSE; NSE-only listings have no insider data after early May 2026.
     The "NSE filed" date on the dashboard reflects this, not a stale download. Revisit
     (ingest Annual as a supplementary, deduped feed) if the gap starts to matter.
   - `data/raw/corporate_actions/bse/`
   - `data/raw/corporate_actions/nse/` — events listed on both exchanges are collapsed
     into one `BSE+NSE` record (matched on company + category + ex-date).

   However much history the raw files hold, the dashboard serves only the most recent
   **18 months** (full-history BSE dumps reach 170k+ rows — too big to ship to a browser).
   Change `SERVE_MONTHS` in `pipeline/ingest.py` to widen it.
3. Run:
   ```bash
   ./update.sh          # add --fetch to also refresh preferential issues from the NSE API
   ```
   This re-ingests, runs the tests, commits, and (once GitHub is connected) pushes so the live
   site redeploys.

Preferential issues need no manual export — `python3 pipeline/fetch_nse_pref.py` (or the
`--fetch` flag above) downloads them from the NSE API into `data/raw/preferential/nse/`.
Default window is the trailing 180 days; use `--days N` or `--from/--to DD-MM-YYYY` for more.
Overlapping fetches are fine — filings dedupe on their NSE application id.

---

## Run / preview locally

```bash
python3 pipeline/ingest.py          # regenerate docs/data/*.json
python3 -m http.server -d docs 8000 # serve the site
# open http://localhost:8000
```

## Tests

```bash
python3 tests/run_tests.py          # zero-dependency runner
# or: pytest                        # if you have it installed
```
Tests run against the real sample CSVs in `data/raw/` and assert the known behaviour
(dedup counts, cross-feed matches, placeholder handling, full vocabulary coverage).

---

## Connecting to GitHub & going live (first time)

You only do this **once**. It needs a free GitHub account.

1. **Log in to GitHub from your terminal** (interactive, opens a browser):
   ```bash
   gh auth login
   ```
   Choose: **GitHub.com → HTTPS → Login with a web browser**, then paste the code shown.
2. **Create the repo and push** (run from this folder):
   ```bash
   gh repo create market-catalyst --public --source=. --remote=origin --push
   ```
3. **Turn on GitHub Pages** to serve the `docs/` folder:
   ```bash
   gh api -X POST repos/:owner/market-catalyst/pages -f source.branch=main -f source.path=/docs
   ```
   (Or in the browser: repo **Settings → Pages → Source: Deploy from a branch → `main` / `/docs`**.)

After this, every `./update.sh` pushes new data and the site redeploys automatically.

> **Git in one line:** Git tracks snapshots ("commits") of your files locally; GitHub is the
> cloud copy ("remote", named `origin`) that also hosts the website. `update.sh` handles
> committing and pushing for you.

---

## Adding Open Offers

This tab is scaffolded and wired to empty data. To populate it:
1. Drop an export into `data/raw/open_offers/`.
2. Add a parser in `pipeline/parsers/` (mirror `bse_corpactions.py` for a CSV, or
   `nse_pref.py` for an NSE API payload) mapping its fields to a record dict, and emit it to
   `docs/data/open_offers.json` from `pipeline/ingest.py`.
3. The shared filter/table/chart framework renders it automatically.

---

## Project layout

```
data/raw/            raw exchange CSVs (the canonical inputs, committed)
pipeline/            ingestion: normalize, parsers/, match, sanitize, aggregate, ingest
tests/               stdlib test suite + runner
  fixtures/          frozen copies of real exports the tests run against —
                     refreshing data/raw/ never breaks the suite
docs/                the static site GitHub Pages serves
  data/              generated JSON (committed)
  js/ css/ lib/      app modules, styles, vendored Chart.js
update.sh            re-ingest + test + commit + push
PLAN.md              the design decisions behind this build
```

## Data notes & caveats

- **BSE is primary**; ~69% of NSE rows in the sample restate a BSE disclosure and are merged
  (NSE's XBRL link, Regulation, and broadcast time are folded into the BSE row).
- Matching is on normalized **company + person + transaction date + share count**. An ISIN map
  could improve this later but isn't required.
- Exchange exports aren't always cleanly date-bounded (some BSE rows date back years; NSE can lag
  its filename by weeks) — the **freshness panel** shows the dates actually present, so trust that
  over the filename.
