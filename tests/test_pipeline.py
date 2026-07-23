"""Tests for the Market Catalyst pipeline. Runnable two ways:

    python3 tests/run_tests.py     # stdlib runner, zero dependencies
    pytest                         # if installed

Parser/matcher tests run against frozen copies of real exchange exports in
tests/fixtures/ — the hard-coded counts document the pipeline's behavior on
those exact files and never change when new data is dropped into data/raw/.
The full-ingest test runs on whatever is in data/raw/ and asserts structural
invariants only, so refreshing data can't break the suite.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import match, normalize as nz, sanitize  # noqa: E402
from pipeline.parsers import (bse_corpactions, bse_insider, nse_corpactions,  # noqa: E402
                              nse_insider, nse_pref)

FIX = ROOT / "tests/fixtures"
BSE_CSV = FIX / "BSE_SEBI_PIT170626.csv"
NSE_CSV = FIX / "NSE_CF-Insider-Trading-17-03-2026-to-17-06-2026.csv"
CORP_CSV = FIX / "BSE_All_Corporate_Actions.csv"
NSE_CORP_CSV = FIX / "NSE_CF-CA-equities-15-07-2025-to-15-07-2026.csv"
PREF_JSON = FIX / "NSE_PREF_01-01-2026_to_02-07-2026.json"


# --------------------------------------------------------------------------- #
# normalization
# --------------------------------------------------------------------------- #

def test_normco_strips_suffix_variants():
    assert nz.normco("Ravindra Energy Limited") == nz.normco("Ravindra Energy Ltd")
    assert nz.normco("Thomas Cook  (India)  Limited") == nz.normco("Thomas Cook (India) Ltd")
    assert nz.normco("Info Edge (India) Ltd") == nz.normco("Info Edge (India) Limited")


def test_txn_type_canonicalization():
    assert nz.canon_txn_type("Acquisition") == "BUY"
    assert nz.canon_txn_type("Buy") == "BUY"
    assert nz.canon_txn_type("Disposal") == "SELL"
    assert nz.canon_txn_type("Sell") == "SELL"
    assert nz.canon_txn_type("Pledge Revoke") == "REVOKE"
    assert nz.canon_txn_type("Pledge Invoke") == "INVOKE"


def test_category_canonicalization():
    assert nz.canon_category("KMP") == nz.canon_category("Key Managerial Personnel") == "KMP"
    assert nz.canon_category("Promoter") == nz.canon_category("Promoters") == "PROMOTER"
    assert nz.canon_category("Promoter & Director") == nz.canon_category("Promoter and Director")


def test_mode_canonicalization_and_market_flag():
    assert nz.canon_mode("Creation Of Pledge") == nz.canon_mode("Pledge Creation")
    assert nz.canon_mode("Inter-se Transfer") == nz.canon_mode("Inter-se-Transfer")
    assert nz.is_market_mode(nz.canon_mode("Market Purchase")) is True
    assert nz.is_market_mode(nz.canon_mode("ESOP")) is False
    assert nz.is_market_mode(nz.canon_mode("Gift")) is False


def test_date_parsing_both_formats():
    assert nz.parse_date("23 Dec 2024") == date(2024, 12, 23)
    assert nz.parse_date("29-Apr-2026") == date(2026, 4, 29)
    assert nz.parse_date("02-May-2026 16:46") == date(2026, 5, 2)
    assert nz.parse_date("-") is None and nz.parse_date("") is None


def test_corp_action_bucketing():
    assert nz.corp_action_bucket("Bonus issue 4:1") == "BONUS"
    assert nz.corp_action_bucket("Buy Back of Shares") == "BUYBACK"
    assert nz.corp_action_bucket("Right Issue of Equity Shares") == "RIGHTS"
    assert nz.corp_action_bucket("Interim Dividend - Rs 5") == "DIVIDEND"
    # NSE phrases REIT/InvIT payouts as unit distributions with dividend and
    # interest as components — they must not fall into DIVIDEND/DEBT.
    assert nz.corp_action_bucket(
        "Distribution - Rs 2 Per Unit Consisting Of Interest - Re 1.57 Per Unit "
        "/ Dividend - Re 0.28 Per Unit") == "REIT_INVIT"
    assert nz.corp_action_bucket("Income Distribution (InvIT)") == "REIT_INVIT"


# --------------------------------------------------------------------------- #
# parsing — counts and full vocabulary coverage on the real files
# --------------------------------------------------------------------------- #

def test_parser_row_counts():
    assert len(list(bse_insider.parse(BSE_CSV))) == 4815
    assert len(list(nse_insider.parse(NSE_CSV))) == 1592
    assert len(list(bse_corpactions.parse(CORP_CSV))) == 675
    assert len(list(nse_corpactions.parse(NSE_CORP_CSV))) == 1977


def test_nse_corpactions_records_keyable():
    # Every NSE calendar row must be mergeable: symbol, company key and ex-date
    # present (the feed has no security code — cross-exchange identity relies
    # on company_norm + category + ex_date).
    recs = list(nse_corpactions.parse(NSE_CORP_CSV))
    assert all(r["symbol"] and r["company_norm"] and r["ex_date"] for r in recs)
    assert all(match.corp_action_key(r) is not None for r in recs)


def test_no_unmapped_vocabulary_in_real_data():
    nz.reset_unmapped()
    list(bse_insider.parse(BSE_CSV))
    list(nse_insider.parse(NSE_CSV))
    unmapped = nz.unmapped()
    assert unmapped["txn_type"] == set(), unmapped["txn_type"]
    assert unmapped["category"] == set(), unmapped["category"]
    assert unmapped["mode"] == set(), unmapped["mode"]


def test_nse_annual_pit_export_rejected(tmp_path=None):
    # NSE's "Annual PIT" export looks like an insider file but is a coarser,
    # incompatible format; parsing must fail loudly, not degrade silently.
    import tempfile
    header = ('"COMPANY NAME \n","NAME OF PERSON \n","CATEGORY OF PERSON \n",'
              '"SECURITIES ACQUIRED / DISPOSED - BUY \nNo. of shares"\n'
              '"Foo Ltd","A B","Promoter","100"\n')
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as fh:
        fh.write(header)
        tmp = fh.name
    try:
        list(nse_insider.parse(tmp))
        raise AssertionError("annual-format file should have been rejected")
    except ValueError as e:
        assert "Annual PIT" in str(e)
    finally:
        Path(tmp).unlink()


def test_nse_extras_present():
    nse = list(nse_insider.parse(NSE_CSV))
    assert all(r["xbrl"] and r["xbrl"].startswith("http") for r in nse if r["xbrl"])
    assert sum(1 for r in nse if r["regulation"]) > 1500
    assert sum(1 for r in nse if r["xbrl"]) == 1592


# --------------------------------------------------------------------------- #
# matching / dedup
# --------------------------------------------------------------------------- #

def test_within_bse_dedup_collapses_known_duplicates():
    bse = list(bse_insider.parse(BSE_CSV))
    sanitize.sanitize(bse)
    _, stats = match.dedupe_within_source(bse)
    # Matches the user's observed "418 cases" of within-BSE duplication.
    assert stats["dup_groups"] == 346
    assert stats["collapsed_rows"] == 418


def test_cross_feed_merges_majority_of_nse():
    bse = list(bse_insider.parse(BSE_CSV))
    nse = list(nse_insider.parse(NSE_CSV))
    sanitize.sanitize(bse + nse)
    bse, _ = match.dedupe_within_source(bse)
    nse, _ = match.dedupe_within_source(nse)
    _, stats = match.merge_cross_feed(bse, nse)
    assert stats["merged"] == 1048
    assert stats["nse_only"] == 464
    # A clear majority of (deduped) NSE rows are folded into BSE.
    assert stats["merged"] > stats["nse_only"]


def test_merged_rows_carry_nse_xbrl():
    bse = list(bse_insider.parse(BSE_CSV))
    nse = list(nse_insider.parse(NSE_CSV))
    sanitize.sanitize(bse + nse)
    bse, _ = match.dedupe_within_source(bse)
    nse, _ = match.dedupe_within_source(nse)
    merged, _ = match.merge_cross_feed(bse, nse)
    both = [r for r in merged if r["source"] == "BSE+NSE"]
    assert both, "expected some BSE+NSE merged rows"
    assert sum(1 for r in both if r["xbrl"]) > 0.9 * len(both)


def test_impossible_dates_clamped_to_filing_evidence():
    # Real typo patterns from NSE data: a year mistyped into the future must be
    # clamped to the broadcast/intimation evidence, never dropped or served.
    recs = [
        # start-after-end (from typo'd one year forward)
        {"date_from": "2026-11-26", "date_to": "2025-11-26",
         "date_intimation": "2025-11-27", "broadcast": "28-Nov-2025 10:43"},
        # every filer-entered date typo'd; exchange broadcast is the backstop
        {"date_from": "2026-11-09", "date_to": "2026-11-09",
         "date_intimation": "2026-11-10", "broadcast": "11-Mar-2026 15:17"},
        # BSE-style row (no broadcast): intimation is the ceiling
        {"date_from": "2025-07-24", "date_to": "2028-07-28",
         "date_intimation": "2025-07-29", "broadcast": None},
        # sane row untouched
        {"date_from": "2026-01-05", "date_to": "2026-01-06",
         "date_intimation": "2026-01-07", "broadcast": "07-Jan-2026 12:00"},
    ]
    stats = sanitize.sanitize_dates(recs)
    assert stats == {"clamped": 3}
    assert recs[0]["date_from"] == recs[0]["date_to"] == "2025-11-26"
    assert (recs[1]["date_from"] == recs[1]["date_to"]
            == recs[1]["date_intimation"] == "2026-03-11")
    assert recs[2]["date_to"] == "2025-07-29" and recs[2]["date_from"] == "2025-07-24"
    assert recs[3]["date_from"] == "2026-01-05" and recs[3]["date_to"] == "2026-01-06"


def _ca(source, company, category, ex_date, **extra):
    return {"source": source, "company": company, "company_norm": nz.normco(company),
            "category": category, "ex_date": ex_date, "symbol": extra.pop("symbol", ""),
            **extra}


def test_corp_actions_cross_exchange_merge():
    bse = [_ca("BSE", "Anuh Pharma Ltd", "BONUS", "2025-07-15", security_code="506260"),
           _ca("BSE", "Foo Ltd", "DIVIDEND", "2025-08-01"),
           _ca("BSE", "Foo Ltd", "DIVIDEND", "2025-08-01")]  # final + special twin
    nse = [_ca("NSE", "Anuh Pharma Limited", "BONUS", "2025-07-15", symbol="ANUHPHR"),
           _ca("NSE", "Foo Limited", "DIVIDEND", "2025-08-01"),
           _ca("NSE", "Bar Limited", "SPLIT", "2025-09-01", symbol="BAR")]
    merged, stats = match.merge_corp_actions(bse, nse)
    assert stats == {"merged": 2, "nse_only": 1}
    assert len(merged) == 4  # 3 BSE rows kept + 1 NSE-only appended
    anuh = next(r for r in merged if r["company_norm"] == nz.normco("Anuh Pharma Ltd"))
    assert anuh["source"] == "BSE+NSE"
    assert anuh["security_code"] == "506260"  # BSE fields win
    assert anuh["symbol"] == "ANUHPHR"        # NSE contributes the symbol
    # Twin BSE events on one ex-date: only one absorbs the single NSE row.
    foo_sources = sorted(r["source"] for r in merged
                         if r["company_norm"] == nz.normco("Foo Ltd"))
    assert foo_sources == ["BSE", "BSE+NSE"]
    assert [r for r in merged if r["source"] == "NSE"][0]["symbol"] == "BAR"


# --------------------------------------------------------------------------- #
# sanitization
# --------------------------------------------------------------------------- #

def test_placeholder_repaired_from_twin():
    bse = list(bse_insider.parse(BSE_CSV))
    sanitize.sanitize(bse)
    # 3B Films Ltd: 696,000 shares recorded as worth ~3 rupees, but a twin row
    # (same person/date/shares) carries the real value -> should be repaired.
    placeholder = [r for r in bse if r["company"].startswith("3B Films")
                   and r["shares"] == 696000 and r["value_raw"] == 3.0]
    assert placeholder, "expected the 3B Films placeholder row in the sample"
    rec = placeholder[0]
    assert rec["value_status"] == "repaired"
    assert rec["value_in_totals"] is True
    assert rec["value"] and rec["value"] > 1000  # real value, not the placeholder


def test_flagged_values_excluded_from_totals():
    bse = list(bse_insider.parse(BSE_CSV))
    sanitize.sanitize(bse)
    flagged = [r for r in bse if r["value_status"] == "flagged"]
    assert flagged, "expected some un-repairable placeholder rows"
    # Every flagged row is a positive tiny/anomalous value, excluded from totals.
    assert all(r["value"] is None for r in flagged)
    assert all(r["value_in_totals"] is False for r in flagged)
    assert all(r["value_raw"] and r["value_raw"] > 0 for r in flagged)


def test_pledges_are_novalue_not_flagged():
    bse = list(bse_insider.parse(BSE_CSV))
    sanitize.sanitize(bse)
    pledges = [r for r in bse if r["txn_type"] == "PLEDGE" and not r["value_raw"]]
    assert pledges
    # A pledge with no rupee value is normal, not a data error.
    assert all(r["value_status"] in ("novalue", "repaired") for r in pledges)


def test_zero_value_buys_are_novalue():
    bse = list(bse_insider.parse(BSE_CSV))
    sanitize.sanitize(bse)
    zero_buys = [r for r in bse if r["txn_type"] == "BUY" and r["value_raw"] == 0]
    assert zero_buys
    assert all(r["value_status"] in ("novalue", "repaired") for r in zero_buys)


# --------------------------------------------------------------------------- #
# preferential issues (NSE API payload)
# --------------------------------------------------------------------------- #

def test_pref_parser_counts_and_fields():
    recs = list(nse_pref.parse(PREF_JSON))
    assert len(recs) == 349
    assert len({r["app_id"] for r in recs}) == 349  # appId is a unique key
    assert all(r["company_norm"] for r in recs)
    assert all(r["xbrl"].startswith("http") for r in recs if r["xbrl"])
    from collections import Counter
    status = Counter(r["amount_status"] for r in recs)
    assert status == {"ok": 288, "repaired": 32, "partial": 23, "novalue": 6}


def test_pref_lakh_unit_amounts_repaired():
    recs = list(nse_pref.parse(PREF_JSON))
    # UGRO Capital's filed amountRaised is 10^5x its shares x offer price —
    # a lakh-units entry error that must be repaired to the product.
    ugro = [r for r in recs if r["company_norm"].startswith("UGRO")
            and r["amount_status"] == "repaired"]
    assert ugro
    for r in ugro:
        assert r["amount_raised"] == r["issue_size"] == r["shares_allotted"] * r["offer_price"]
        assert r["issue_size"] < 1e11  # sane (< Rs 10,000 cr), not the quadrillions filed


def test_pref_partly_paid_amounts_kept():
    recs = list(nse_pref.parse(PREF_JSON))
    partial = [r for r in recs if r["amount_status"] == "partial"]
    assert partial
    # Warrants collect 10-50% upfront; the paid-in amount stays below issue size.
    assert all(r["amount_raised"] < r["issue_size"] for r in partial)


# --------------------------------------------------------------------------- #
# full pipeline
# --------------------------------------------------------------------------- #

def test_full_ingest_shape():
    """Runs on the LIVE data/raw/ contents: structural invariants only, so
    dropping new exchange exports never breaks the suite."""
    import json

    from pipeline import ingest
    meta = ingest.run()
    ins = meta["insider"]
    assert ins["records"] > 0
    assert set(ins["by_source"]) <= {"BSE", "BSE+NSE", "NSE"}
    assert sum(ins["by_source"].values()) == ins["records"]
    # Served window: a non-empty, size-bounded slice of the final records.
    assert 0 < ins["served"]["records"] <= ins["records"]
    assert sum(ins["served"]["by_source"].values()) == ins["served"]["records"]
    assert sum(ins["value_status"].values()) == ins["served"]["records"]
    assert meta["corporate_actions"]["records"] > 0
    assert meta["preferential"]["records"] > 0
    # Every raw value must be classified — an unmapped vocab value is a bug
    # (extend the maps in pipeline/normalize.py, they must cover real data).
    assert not meta["warnings"], meta["warnings"]

    served = json.loads((ROOT / "docs/data/insider.json").read_text("utf-8"))
    assert len(served) == ins["served"]["records"]
    assert set(served[0]) == set(ingest.SERVE_FIELDS)
    # The served JSON must stay comfortably below GitHub's 100 MB file limit.
    assert (ROOT / "docs/data/insider.json").stat().st_size < 50_000_000
    assert (ROOT / "docs/data/preferential.json").exists()
    assert (ROOT / "docs/data/meta.json").exists()
