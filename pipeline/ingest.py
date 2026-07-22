"""Catalyst Tracker ingestion entry point.

Reads the raw exchange CSVs under data/raw/, runs the full normalize -> sanitize
-> dedup -> cross-feed-merge pipeline, and writes the JSON that the static site
loads from docs/data/.

Usage:  python3 pipeline/ingest.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Absolute imports (with ROOT on sys.path) so this works both as a module
# (python3 -m pipeline.ingest, or imported by the tests) and as a plain
# script (python3 pipeline/ingest.py, as update.sh runs it).
sys.path.insert(0, str(ROOT))

# The dashboard serves only the most recent transactions. Full-history BSE
# exports run to 170k+ rows (back to 2001) — as JSON that is >100 MB, which a
# browser can't reasonably load and GitHub refuses to store. The raw CSVs keep
# the full history; widen this window and re-run if you want more served.
SERVE_MONTHS = 12

# Fields the site actually reads (see docs/js/*). Raw-echo and pipeline-debug
# fields stay out of the served JSON to keep the download small.
SERVE_FIELDS = (
    "id", "source", "security_code", "symbol", "company", "company_norm",
    "person", "person_norm", "category", "txn_type", "mode", "is_market",
    "is_promoter", "shares", "value", "value_status", "value_in_totals",
    "post_pct", "date_from", "regulation", "xbrl",
)

from pipeline import aggregate, match, normalize as nz, sanitize  # noqa: E402
from pipeline.parsers import (bse_corpactions, bse_insider, nse_corpactions,  # noqa: E402
                              nse_insider, nse_pref)
from pipeline.util import find_csvs, find_files  # noqa: E402
RAW = ROOT / "data" / "raw"
OUT = ROOT / "docs" / "data"


def _parse_all(folder: Path, parser) -> list[dict]:
    records: list[dict] = []
    for csv_path in find_csvs(folder):
        records.extend(parser(csv_path))
    return records


def run() -> dict:
    nz.reset_unmapped()

    bse = _parse_all(RAW / "insider" / "bse", bse_insider.parse)
    nse = _parse_all(RAW / "insider" / "nse", nse_insider.parse)
    corp_bse = _parse_all(RAW / "corporate_actions" / "bse", bse_corpactions.parse)
    corp_nse = _parse_all(RAW / "corporate_actions" / "nse", nse_corpactions.parse)
    pref, pref_raw = _load_preferential()
    raw_counts = {"bse": len(bse), "nse": len(nse), "corp": len(corp_bse),
                  "corp_nse": len(corp_nse), "pref": pref_raw}
    corp, corp_merge = match.merge_corp_actions(corp_bse, corp_nse)

    # Sanitize dates before any matching: dedup/merge keys include date_from,
    # so a typo'd year must be repaired first or twins won't pair up.
    date_stats = sanitize.sanitize_dates(bse + nse)
    # Sanitize values across the combined pool so twin-repair can borrow a sane
    # value from either feed before any rows are collapsed.
    value_stats = sanitize.sanitize(bse + nse)

    bse, bse_dedup = match.dedupe_within_source(bse)
    nse, nse_dedup = match.dedupe_within_source(nse)
    insider, merge_stats = match.merge_cross_feed(bse, nse)

    for i, rec in enumerate(insider):
        rec["id"] = i

    served, cutoff = _serve_window(insider)
    corp_served = _serve_corp_window(corp)

    meta = aggregate.build_meta(
        insider=insider, served=served, corp=corp_served, pref=pref,
        raw_counts=raw_counts,
        dedup={"bse": bse_dedup, "nse": nse_dedup}, merge=merge_stats,
        corp_merge=corp_merge,
        value_stats=value_stats, date_stats=date_stats, unmapped=nz.unmapped(),
    )
    meta["insider"]["served"].update(window_months=SERVE_MONTHS, cutoff=cutoff)

    OUT.mkdir(parents=True, exist_ok=True)
    _write(OUT / "insider.json", served)
    _write(OUT / "corporate_actions.json", _serve_corp_window(corp))
    _write(OUT / "preferential.json", pref)
    # Scaffolded category — empty until the user supplies exports.
    _write(OUT / "open_offers.json", [])
    _write(OUT / "meta.json", meta)

    return meta


def _serve_window(insider: list[dict]) -> tuple[list[dict], str | None]:
    """Slim the final records to the SERVE_MONTHS most recent transactions.
    ...
    """
    dates = sorted(r["date_from"] for r in insider if r["date_from"])
    if not dates:
        return [{k: r.get(k) for k in SERVE_FIELDS} for r in insider], None
    y, m, d = map(int, dates[-1].split("-"))
    m -= SERVE_MONTHS
    while m <= 0:
        m += 12
        y -= 1
    cutoff = f"{y:04d}-{m:02d}-{d:02d}"
    return [{k: r.get(k) for k in SERVE_FIELDS}
            for r in insider if r["date_from"] and r["date_from"] >= cutoff], cutoff


def _serve_corp_window(corp_actions: list[dict]) -> list[dict]:
    """Slim corporate actions to the SERVE_MONTHS most recent by ex-date."""
    dates = sorted(r["ex_date"] for r in corp_actions if r["ex_date"])
    if not dates:
        return corp_actions
    y, m, d = map(int, dates[-1].split("-"))
    m -= SERVE_MONTHS
    while m <= 0:
        m += 12
        y -= 1
    cutoff = f"{y:04d}-{m:02d}-{d:02d}"
    return [r for r in corp_actions if r["ex_date"] and r["ex_date"] >= cutoff]


def _load_preferential() -> tuple[list[dict], int]:
    """Parse all fetched NSE PREF payloads, dedupe on appId across files.

    Overlapping fetch windows produce identical filings in multiple files; the
    last-parsed copy wins (files sort by name, so the newest window prevails
    for any filing whose stage advanced between fetches).
    """
    by_id: dict[str, dict] = {}
    raw = 0
    for path in find_files(RAW / "preferential" / "nse", "*.json"):
        for rec in nse_pref.parse(path):
            raw += 1
            by_id[rec["app_id"] or f"noid-{raw}"] = rec
    records = sorted(by_id.values(),
                     key=lambda r: (r["date_allotment"] or "", r["company"]),
                     reverse=True)
    for i, rec in enumerate(records):
        rec["id"] = i
    return records, raw


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")


def _print_summary(meta: dict) -> None:
    ins = meta["insider"]
    print("Catalyst Tracker ingest complete")
    print(f"  Insider records:      {ins['records']}  {ins['by_source']}")
    print(f"  Served to dashboard:  {ins['served']['records']} "
          f"(last {ins['served']['window_months']} months, "
          f"since {ins['served']['cutoff']})")
    print(f"  Within-BSE collapsed: {ins['within_bse']}")
    print(f"  Cross-feed:           {ins['cross_feed']}")
    print(f"  Value status:         {ins['value_status']}")
    print(f"  Insider date range:   {ins['transaction_dates']}")
    ca = meta["corporate_actions"]
    print(f"  Corp actions:         {ca['records']}  {ca['by_source']}")
    print(f"  Corp-action buckets:  {ca['buckets']}")
    pf = meta["preferential"]
    print(f"  Preferential issues:  {pf['records']}  "
          f"(₹{pf['issue_size_total'] / 1e7:,.0f} cr, "
          f"amounts {pf['amount_status']})")
    if meta["warnings"]:
        print(f"  WARNINGS:             {meta['warnings']}")


if __name__ == "__main__":
    meta = run()
    _print_summary(meta)
    if meta["warnings"]:
        # Unmapped vocabulary won't break the build but should be addressed.
        print("\nNote: unmapped values fell back to OTHER; extend the maps in "
              "pipeline/normalize.py to classify them.", file=sys.stderr)
