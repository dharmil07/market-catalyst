"""Value sanitization.

The real exports contain placeholder transaction values (e.g. 696,000 shares
recorded as worth ₹3). Displayed at face value they wreck the net-buyer/seller
rankings. Policy (chosen with the user): repair a bad value from a "twin" (a
within-source duplicate or cross-feed counterpart sharing the same key) when one
has a sane value; otherwise flag it and exclude it from value totals (the
transaction is still counted). We never fabricate a number.

Each record gains:
  implied_price   value_raw / shares (None if not computable)
  value           the value to use in totals (None when excluded)
  value_status    one of:
                    "ok"         a trustworthy reported value
                    "repaired"   bad/absent value replaced from a sane twin
                    "flagged"    a suspicious placeholder we couldn't repair
                    "novalue"    no value reported (normal for ESOP/gift/pledge/
                                 revoke/invoke and other non-cash events)
                    "derivative" derivative-only row, handled separately
  value_in_totals bool (only "ok"/"repaired" with a positive value count)
"""
from __future__ import annotations

from statistics import median

from . import normalize as nz
from .match import transaction_key

# Bounds for an implied price (₹/share) we'll trust when building per-company
# medians. Indian equities span well under ₹1 to ~₹1.5 lakh (e.g. MRF); the
# ceiling is generous to avoid discarding genuine high-priced rows.
_SANE_MIN_PRICE = 0.5
_SANE_MAX_PRICE = 5_000_000.0

# Absolute placeholder rule: a tiny rupee value against a real share count.
_PLACEHOLDER_MAX_VALUE = 10.0
_PLACEHOLDER_MIN_SHARES = 100
# Relative rule: implied price far below the company's typical implied price.
_PLACEHOLDER_RATIO = 0.02


def sanitize_dates(records: list[dict]) -> dict:
    """Clamp impossible transaction dates using in-record evidence. Mutates
    `records`; returns stats.

    Filers typo years (a Nov-2025 trade filed as Nov-2026, which would then sit
    at the top of every "recent" view and drag the serve window into the
    future). Two invariants need no wall clock: a transaction can't start after
    it ends, and no disclosed date can postdate the filing itself — the
    exchange-set broadcast timestamp when present, else the intimation date.
    Violations are clamped to the evidence date; the row is never dropped (the
    disclosure is real, only its date is mistyped).
    """
    clamped = 0
    for rec in records:
        before = (rec.get("date_from"), rec.get("date_to"),
                  rec.get("date_intimation"))
        if rec.get("date_from") and rec.get("date_to") \
                and rec["date_from"] > rec["date_to"]:
            rec["date_from"] = rec["date_to"]
        filed = nz.iso(nz.parse_date(rec.get("broadcast") or ""))
        for field in ("date_intimation", "date_to", "date_from"):
            ceiling = filed or rec.get("date_intimation")
            if ceiling and rec.get(field) and rec[field] > ceiling:
                rec[field] = ceiling
        if (rec.get("date_from"), rec.get("date_to"),
                rec.get("date_intimation")) != before:
            clamped += 1
    return {"clamped": clamped}


def _implied(rec: dict) -> float | None:
    v, s = rec.get("value_raw"), rec.get("shares")
    if v is None or s is None or s <= 0:
        return None
    return v / s


def _is_sane_value(rec: dict) -> bool:
    v = rec.get("value_raw")
    if v is None or v <= _PLACEHOLDER_MAX_VALUE:
        return False
    ip = rec.get("implied_price")
    return ip is None or (_SANE_MIN_PRICE <= ip <= _SANE_MAX_PRICE)


def sanitize(records: list[dict]) -> dict:
    """Mutate `records` in place, assigning value fields. Returns stats."""
    for rec in records:
        rec["implied_price"] = _implied(rec)

    # Per-company median implied price from rows that look sane.
    by_company: dict[str, list[float]] = {}
    for rec in records:
        if _is_sane_value(rec) and rec["implied_price"] is not None:
            by_company.setdefault(rec["company_norm"], []).append(rec["implied_price"])
    medians = {c: median(v) for c, v in by_company.items() if v}

    def is_placeholder(rec: dict) -> bool:
        # Only positive values can be "placeholders"; absent/zero values are
        # handled as "novalue" (normal for non-cash events), not as errors.
        v, s = rec.get("value_raw"), rec.get("shares")
        if not v or v <= 0 or s is None or s <= 0:
            return False
        if v <= _PLACEHOLDER_MAX_VALUE and s >= _PLACEHOLDER_MIN_SHARES:
            return True
        med = medians.get(rec["company_norm"])
        if med and rec["implied_price"] is not None:
            return rec["implied_price"] < _PLACEHOLDER_RATIO * med
        return False

    # Twin map: key -> sane values available from any row sharing that key.
    twins: dict[tuple, list[float]] = {}
    for rec in records:
        key = transaction_key(rec)
        if key is not None and _is_sane_value(rec) and not is_placeholder(rec):
            twins.setdefault(key, []).append(rec["value_raw"])

    stats = {"ok": 0, "repaired": 0, "flagged": 0, "novalue": 0, "derivative": 0}
    for rec in records:
        key = transaction_key(rec)
        twin_value = max(twins.get(key, []), default=None) if key is not None else None
        v = rec.get("value_raw")

        if rec.get("is_derivative"):
            status, value = "derivative", None
        elif v is None or v == 0:
            # No value reported — normal for ESOP/gift/pledge/revoke/invoke. Fill
            # from a twin if one happens to carry a real value, else leave out.
            if twin_value is not None:
                status, value = "repaired", twin_value
            else:
                status, value = "novalue", None
        elif is_placeholder(rec):
            if twin_value is not None:
                status, value = "repaired", twin_value
            else:
                status, value = "flagged", None
        else:
            status, value = "ok", v

        rec["value"] = value
        rec["value_status"] = status
        rec["value_in_totals"] = status in ("ok", "repaired") and bool(value and value > 0)
        stats[status] += 1

    return stats
