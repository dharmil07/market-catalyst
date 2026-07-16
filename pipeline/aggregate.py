"""Build the coverage/freshness metadata that powers the data-trust panel."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone


def _date_span(values) -> dict:
    dates = sorted(v for v in values if v)
    return {"min": dates[0] if dates else None, "max": dates[-1] if dates else None}


def build_meta(*, insider, served, corp, pref, raw_counts, dedup, merge,
               corp_merge, value_stats, unmapped) -> dict:
    """Assemble the meta.json structure from final data + pipeline stats."""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": {
            "insider_bse": {
                "rows_raw": raw_counts.get("bse", 0),
                "transaction_dates": _date_span(
                    r["date_from"] for r in insider if r["source"] != "NSE"
                ),
                "latest_intimation": _date_span(
                    r["date_intimation"] for r in insider if r["source"] != "NSE"
                )["max"],
            },
            "insider_nse": {
                "rows_raw": raw_counts.get("nse", 0),
                "latest_intimation": _date_span(
                    r["date_intimation"] for r in insider if r.get("xbrl")
                )["max"],
            },
            "corporate_actions_bse": {
                "rows_raw": raw_counts.get("corp", 0),
                "event_dates": _date_span(
                    r["ex_date"] for r in corp if r["source"] != "NSE"
                ),
            },
            "corporate_actions_nse": {
                "rows_raw": raw_counts.get("corp_nse", 0),
                "event_dates": _date_span(
                    r["ex_date"] for r in corp if r["source"] != "BSE"
                ),
            },
            "preferential_nse": {
                "rows_raw": raw_counts.get("pref", 0),
                "allotment_dates": _date_span(r["date_allotment"] for r in pref),
            },
        },
        "insider": {
            "records": len(insider),
            "by_source": dict(Counter(r["source"] for r in insider)),
            "within_bse": dedup.get("bse", {}),
            "within_nse": dedup.get("nse", {}),
            "cross_feed": merge,
            # Reported on the SERVED records — what the dashboard shows.
            # (ingest adds window_months/cutoff to "served" after this.)
            "served": {
                "records": len(served),
                "by_source": dict(Counter(r["source"] for r in served)),
            },
            "value_status": dict(Counter(r["value_status"] for r in served)),
            "value_status_raw": value_stats,
            "transaction_dates": _date_span(r["date_from"] for r in served),
            "full_transaction_dates": _date_span(r["date_from"] for r in insider),
        },
        "corporate_actions": {
            "records": len(corp),
            "by_source": dict(Counter(r["source"] for r in corp)),
            "cross_exchange": corp_merge,
            "buckets": dict(Counter(r["category"] for r in corp)),
            "event_dates": _date_span(r["ex_date"] for r in corp),
        },
        "preferential": {
            "records": len(pref),
            "companies": len({r["company_norm"] for r in pref}),
            "issue_size_total": sum(r["issue_size"] or 0 for r in pref),
            "amount_status": dict(Counter(r["amount_status"] for r in pref)),
            "allotment_dates": _date_span(r["date_allotment"] for r in pref),
            "listing_dates": _date_span(r["date_listing"] for r in pref),
        },
        "warnings": {
            "unmapped_" + k: sorted(v) for k, v in unmapped.items() if v
        },
    }
