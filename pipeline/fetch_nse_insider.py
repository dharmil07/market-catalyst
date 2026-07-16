"""Download NSE insider-trading disclosures as the regular CSV export.

Source page: https://www.nseindia.com/companies-listing/corporate-filings-insider-trading
API:         https://www.nseindia.com/api/corporates-pit?index=equities&csv=true

With csv=true the API returns the portal's regular "Insider Trading" CSV — the
format pipeline/parsers/nse_insider.py expects, NOT the coarser "Annual PIT"
export the website offers for 1-year ranges (the parser rejects that one). The
JSON variant of this endpoint returns empty for date-filtered queries, so CSV
is also the only working mode.

Long windows are fetched in ~3-month chunks (mirroring the portal's own limit
on this dataset); each chunk lands as its own file under data/raw/insider/nse/
where ingest reads them all and collapses any overlap in the dedup step.

Usage:
    python3 pipeline/fetch_nse_insider.py             # trailing 365 days
    python3 pipeline/fetch_nse_insider.py --days 90
    python3 pipeline/fetch_nse_insider.py --from 16-07-2025 --to 16-07-2026
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.fetch_nse_pref import _get, _opener  # noqa: E402

RAW_DIR = ROOT / "data" / "raw" / "insider" / "nse"

PAGE_URL = ("https://www.nseindia.com/companies-listing/"
            "corporate-filings-insider-trading")
API_URL = "https://www.nseindia.com/api/corporates-pit"

CHUNK_DAYS = 91
_FMT = "%d-%m-%Y"


def _chunks(start: date, end: date):
    """Split [start, end] into consecutive windows of at most CHUNK_DAYS."""
    lo = start
    while lo <= end:
        hi = min(lo + timedelta(days=CHUNK_DAYS - 1), end)
        yield lo, hi
        lo = hi + timedelta(days=1)


def fetch_chunk(opener, lo: date, hi: date) -> bytes:
    query = urllib.parse.urlencode({
        "index": "equities",
        "from_date": lo.strftime(_FMT),
        "to_date": hi.strftime(_FMT),
        "csv": "true",
    })
    body = _get(opener, f"{API_URL}?{query}",
                accept="text/csv,application/json, text/plain, */*",
                referer=PAGE_URL)
    head = body[:2048].decode("utf-8", errors="replace").upper()
    if "REGULATION" not in head or "SYMBOL" not in head:
        raise RuntimeError(f"Unexpected response (not the regular Insider "
                           f"Trading CSV): {head[:200]!r}")
    if "ACQUIRED / DISPOSED - BUY" in head:
        raise RuntimeError("API returned the Annual PIT format; aborting.")
    return body


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=365,
                    help="trailing window in days (default 365)")
    ap.add_argument("--from", dest="from_date", metavar="DD-MM-YYYY",
                    help="explicit window start (overrides --days)")
    ap.add_argument("--to", dest="to_date", metavar="DD-MM-YYYY",
                    help="explicit window end (default today)")
    args = ap.parse_args(argv)

    today = date.today()
    end = (datetime.strptime(args.to_date, _FMT).date()
           if args.to_date else today)
    start = (datetime.strptime(args.from_date, _FMT).date()
             if args.from_date else end - timedelta(days=args.days))

    opener = _opener()
    print(f"Fetching NSE insider trading {start.strftime(_FMT)} → "
          f"{end.strftime(_FMT)} in ≤{CHUNK_DAYS}-day chunks …")
    try:
        _get(opener, PAGE_URL, accept="text/html,application/xhtml+xml")  # cookies
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        total_rows = 0
        for lo, hi in _chunks(start, end):
            body = fetch_chunk(opener, lo, hi)
            out = RAW_DIR / (f"CF-Insider-Trading-{lo.strftime(_FMT)}"
                             f"-to-{hi.strftime(_FMT)}.csv")
            out.write_bytes(body)
            rows = max(body.count(b"\n") - 1, 0)
            total_rows += rows
            print(f"  ✓ {lo.strftime(_FMT)} → {hi.strftime(_FMT)}: "
                  f"~{rows} rows → {out.relative_to(ROOT)}")
            time.sleep(1)  # be polite; NSE throttles bursty clients
    except Exception as e:  # noqa: BLE001 — always explain, exchange APIs are moody
        print(f"Fetch failed: {e}\n"
              "NSE sometimes blocks non-browser clients; retry in a minute, or "
              "download the regular 'Insider Trading' CSVs manually (3-month "
              "windows) into data/raw/insider/nse/.", file=sys.stderr)
        return 1
    print(f"✓ ~{total_rows} rows total.")
    print("Run  python3 pipeline/ingest.py  (or ./update.sh) to rebuild the site data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
