"""Normalization layer for Catalyst Tracker.

BSE and NSE describe the same disclosures with different vocabularies and
formats. Everything downstream (matching, dedup, filtering, grouping) depends on
collapsing those differences into a single canonical form. This module is the
one place that knowledge lives.

Design notes:
- Company/person matching keys (`normco`, `normp`) are deliberately aggressive
  (strip suffixes, punctuation, case) because exact name overlap between the two
  exchanges is ~0 (only 1 company matched on raw uppercase in the real samples).
- Controlled-vocab maps are tolerant: the raw value is uppercased and whitespace
  collapsed before lookup, and anything unmapped falls back to a sentinel while
  being recorded by `unmapped()` so ingest can warn and the maps can be extended.
  The test suite asserts there are zero unmapped values across the real data.
"""
from __future__ import annotations

import re
from datetime import date, datetime

# --------------------------------------------------------------------------- #
# Name / number / date normalization
# --------------------------------------------------------------------------- #

# Corporate suffixes stripped so "Ravindra Energy Limited" == "Ravindra Energy Ltd".
_CO_SUFFIX = re.compile(
    r"\b(LIMITED|LIMTED|LTD|PRIVATE|PVT|CORPORATION|CORP|INCORPORATED|INC|"
    r"COMPANY|INDIA|INDIAN)\b\.?"
)
_NON_ALNUM = re.compile(r"[^A-Z0-9 ]+")
_WS = re.compile(r"\s+")


def normco(name: str) -> str:
    """Normalized company key: upper, de-punctuated, suffix-stripped, ws-collapsed."""
    if not name:
        return ""
    s = _NON_ALNUM.sub(" ", name.upper())
    s = _CO_SUFFIX.sub(" ", s)
    return _WS.sub(" ", s).strip()


def normp(name: str) -> str:
    """Normalized person key: upper, de-punctuated, ws-collapsed.

    We intentionally do NOT reorder tokens; in the real samples plain
    normalization already matches the vast majority of cross-exchange pairs, and
    token-sorting risks false positives (e.g. two relatives sharing a surname).
    """
    if not name:
        return ""
    s = _NON_ALNUM.sub(" ", name.upper())
    return _WS.sub(" ", s).strip()


# Date formats seen across BSE ("23 Dec 2024") and NSE ("29-Apr-2026"), plus a
# few defensive extras.
_DATE_FORMATS = (
    "%d %b %Y",
    "%d-%b-%Y",
    "%d/%b/%Y",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%Y-%m-%d",
    "%d %B %Y",
    "%d-%B-%Y",
)


def parse_date(value: str) -> date | None:
    """Parse a date string in any known exchange format -> date, else None."""
    if not value:
        return None
    s = value.strip()
    if not s or s in {"-", "NA", "N/A"}:
        return None
    # Drop a trailing time component if present ("02-May-2026 16:46").
    s = s.split()[0] if (" " in s and ("-" in s.split()[0] or ":" in s)) else s
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def parse_num(value: str) -> float | None:
    """Parse an Indian-format number ('1,23,456.00') -> float, else None."""
    if value is None:
        return None
    s = str(value).replace(",", "").strip()
    if not s or s in {"-", "NA", "N/A"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Controlled vocabularies
# --------------------------------------------------------------------------- #

# Records raw->canonical lookups that missed, so ingest can surface them.
_unmapped: dict[str, set[str]] = {"txn_type": set(), "category": set(), "mode": set()}


def unmapped() -> dict[str, set[str]]:
    return {k: set(v) for k, v in _unmapped.items()}


def reset_unmapped() -> None:
    for v in _unmapped.values():
        v.clear()


def _key(raw: str) -> str:
    return _WS.sub(" ", (raw or "").upper().strip()).rstrip(".")


# Transaction type: BSE uses Acquisition/Disposal, NSE uses Buy/Sell; pledges
# come in several spellings. Canonical set: BUY, SELL, PLEDGE, REVOKE, INVOKE.
_TXN_TYPE = {
    "ACQUISITION": "BUY",
    "BUY": "BUY",
    "DISPOSAL": "SELL",
    "DISPOSED": "SELL",
    "SALE": "SELL",
    "SELL": "SELL",
    "PLEDGE": "PLEDGE",
    "CREATION OF PLEDGE": "PLEDGE",
    "PLEDGE CREATION": "PLEDGE",
    "REVOKE": "REVOKE",
    "PLEDGE REVOKE": "REVOKE",
    "REVOCATION OF PLEDGE": "REVOKE",
    "REVOKATION OF PLEDGE": "REVOKE",
    "INVOKE": "INVOKE",
    "PLEDGE INVOKE": "INVOKE",
    "INVOCATION OF PLEDGE": "INVOKE",
    "INVOCATION OF PLEDGED": "INVOKE",
}

# Category of person. Folds the BSE/NSE spelling variants into one set.
_CATEGORY = {
    "PROMOTER": "PROMOTER",
    "PROMOTERS": "PROMOTER",
    "PROMOTER GROUP": "PROMOTER_GROUP",
    "PROMOTER & DIRECTOR": "PROMOTER_DIRECTOR",
    "PROMOTER AND DIRECTOR": "PROMOTER_DIRECTOR",
    "PROMOTER & DESIGNATED PERSON": "PROMOTER_DESIGNATED",
    "PROMOTER AND DESIGNATED PERSON": "PROMOTER_DESIGNATED",
    "DIRECTOR": "DIRECTOR",
    "DIRECTORS": "DIRECTOR",
    "KMP": "KMP",
    "KEY MANAGERIAL PERSONNEL": "KMP",
    "DESIGNATED PERSON": "DESIGNATED_EMPLOYEE",
    "DESIGNATED EMPLOYEE": "DESIGNATED_EMPLOYEE",
    "DESIGNATED EMPLOYEES": "DESIGNATED_EMPLOYEE",
    "EMPLOYEE": "DESIGNATED_EMPLOYEE",
    "EMPLOYEES": "DESIGNATED_EMPLOYEE",
    "EMPLOYEES/DESIGNATED EMPLOYEES": "DESIGNATED_EMPLOYEE",
    "EMPLOYEES / DESIGNATED EMPLOYEES": "DESIGNATED_EMPLOYEE",
    "IMMEDIATE RELATIVE": "IMMEDIATE_RELATIVE",
    "DIRECTORS IMMEDIATE RELATIVE": "IMMEDIATE_RELATIVE",
    "PROMOTERS IMMEDIATE RELATIVE": "IMMEDIATE_RELATIVE",
    "PROMOTER IMMEDIATE RELATIVE": "IMMEDIATE_RELATIVE",
    "MEMBER OF PROMOTER GROUP": "PROMOTER_GROUP",
    "EMPLOYEES IMMEDIATE RELATIVE": "IMMEDIATE_RELATIVE",
    "TRUST": "TRUST",
    "CONNECTED PERSON": "CONNECTED_PERSON",
    "OTHER": "OTHER",
    "OTHERS": "OTHER",
}

# Categories treated as "promoter activity" for the promoter-only signal filter.
PROMOTER_CATEGORIES = {"PROMOTER", "PROMOTER_GROUP", "PROMOTER_DIRECTOR",
                       "PROMOTER_DESIGNATED"}

# Mode of acquisition.
_MODE = {
    "MARKET PURCHASE": "MARKET_PURCHASE",
    "MARKET SALE": "MARKET_SALE",
    "ESOP": "ESOP",
    "ESOP / ESOS": "ESOP",
    "ESOS": "ESOP",
    "OFF MARKET": "OFF_MARKET",
    "OFF-MARKET": "OFF_MARKET",
    "CREATION OF PLEDGE": "PLEDGE_CREATION",
    "PLEDGE CREATION": "PLEDGE_CREATION",
    "INVOCATION OF PLEDGED": "PLEDGE_INVOCATION",
    "INVOCATION OF PLEDGE": "PLEDGE_INVOCATION",
    "REVOKATION OF PLEDGE": "PLEDGE_REVOCATION",
    "REVOCATION OF PLEDGE": "PLEDGE_REVOCATION",
    "GIFT": "GIFT",
    "INTER-SE TRANSFER": "INTER_SE",
    "INTER-SE-TRANSFER": "INTER_SE",
    "INTER SE TRANSFER": "INTER_SE",
    "ALLOTMENT": "ALLOTMENT",
    "PREFERENTIAL OFFER": "PREFERENTIAL",
    "PREFERENTIAL ALLOTMENT": "PREFERENTIAL",
    "CONVERSION OF SECURITY": "CONVERSION",
    "CONVERSION OF SECURITIES": "CONVERSION",
    "RIGHTS ISSUE": "RIGHTS",
    "RIGHT ISSUE": "RIGHTS",
    "PUBLIC RIGHT": "RIGHTS",
    "BUY BACK": "BUYBACK",
    "BUYBACK": "BUYBACK",
    "BLOCK DEAL": "BLOCK_DEAL",
    "INHERITANCE": "INHERITANCE",
    "PLEDGE RELEASED": "PLEDGE_REVOCATION",
    "BENEFICIARY FROM TRUSTS": "TRUST_TRANSFER",
    "SCHEME OF AMALGAMATION/MERGER/DEMERGER/ARRANGEMENT": "SCHEME",
    "OTHERS": "OTHERS",
    "OTHER": "OTHERS",
    # --- long-tail values from BSE's full-history exports (back to 2001) ---
    "MARKET": "MARKET",  # market trade; buy/sell disambiguated by txn_type
    "SHARES PURCHASED": "MARKET_PURCHASE",
    "PUBLIC OFFER": "OPEN_OFFER",
    "OPEN OFFER": "OPEN_OFFER",
    "OFFER FOR SALE": "OPEN_OFFER",
    "DELISTING OFFER": "OPEN_OFFER",
    "DELISTING OF EQUITY SHARES": "OPEN_OFFER",
    "BUY-BACK OFFER": "BUYBACK",
    "BONUS": "BONUS",
    "BONUS ISSUE": "BONUS",
    "RIGHTS": "RIGHTS",
    "PREFERENTIAL ISSUE": "PREFERENTIAL",
    "PREF. ALLOTMENT": "PREFERENTIAL",
    "PREFERENTIAL ALLOTMENT OF CONVERTIBLE WARRANTS": "PREFERENTIAL",
    "PRIVATE PLACEMENT": "PREFERENTIAL",
    "PRIVATE PLACEMENT OF FCCBS": "PREFERENTIAL",
    "CONVERSION FITL INTO EQUITY": "CONVERSION",
    "CONV. OF WARRANTS": "CONVERSION",
    "CONVERSION OF CCCPS": "CONVERSION",
    "CONVERSION OF ESOP SHARES": "ESOP",
    "INTER-SE TRANSFER / GIFT": "INTER_SE",
    "INTER SE (TRANSMISSION)": "INTER_SE",
    "OFF MARKET / INTER SE TRANSFER": "INTER_SE",
    "OFF MARKET TRANSFER": "OFF_MARKET",
    "OFF MARKET & SHARE PURCHASE AGREEMENT": "OFF_MARKET",
    "OFF MARKET GIFT": "GIFT",
    "SHR.PURCH.AGREEMENT": "OFF_MARKET",
    "SHARE PURCHASE AGREEMENT OFF MARKET PURSUANT TO OPEN OFFER": "OFF_MARKET",
    "TRANSFER": "OFF_MARKET",
    "TRANSMISSION": "INHERITANCE",
    "PLEDGED INVOCATION": "PLEDGE_INVOCATION",
    "PLEDGE": "PLEDGE_CREATION",
    "ENCUMBRANCE CREATED": "PLEDGE_CREATION",
    "NON DISPOSAL UNDERTAKING": "PLEDGE_CREATION",
    "REVOCATION": "PLEDGE_REVOCATION",
    "RELEASE OF PLEDGE": "PLEDGE_REVOCATION",
    "RELEASE OF SHARES": "PLEDGE_REVOCATION",
    "RELEASE OF PLEDGE/ENCUMBRANCE ON SHARES HELD UNDER BORROWINGS": "PLEDGE_REVOCATION",
    "RELEASE OF PLEDGE & NON-DISPOSAL UNDERTAKING": "PLEDGE_REVOCATION",
    "SCHEME OF AMALGAMATION": "SCHEME",
    "SCHEME OF AMALGAMATION & ARRANGEMENT": "SCHEME",
    "SCH.OF ARRANGEMENT": "SCHEME",
    "MERGER": "SCHEME",
    # Genuinely mixed/unclassifiable filings:
    "MARKET & OFF MARKET": "OTHERS",
    "MARKET / INTER-SE TRANSFER": "OTHERS",
    "INVOCATION OF PLEDGE & MARKET": "OTHERS",
    "PLEDGE / REVOKE": "OTHERS",
    "CHANGE IN PERCENTAGE": "OTHERS",
}

# Modes that represent genuine open-market on-exchange trades (the real signal).
MARKET_MODES = {"MARKET_PURCHASE", "MARKET_SALE", "MARKET"}


def canon_txn_type(raw: str) -> str:
    k = _key(raw)
    if not k or k == "-":
        return "OTHER"
    v = _TXN_TYPE.get(k)
    if v is None:
        _unmapped["txn_type"].add(raw.strip())
        return "OTHER"
    return v


def canon_category(raw: str) -> str:
    k = _key(raw)
    if not k or k == "-":
        return "OTHER"
    v = _CATEGORY.get(k)
    if v is None:
        _unmapped["category"].add(raw.strip())
        return "OTHER"
    return v


def canon_mode(raw: str) -> str:
    k = _key(raw)
    if not k or k == "-":
        return "OTHERS"
    v = _MODE.get(k)
    if v is None:
        _unmapped["mode"].add(raw.strip())
        return "OTHERS"
    return v


def is_market_mode(canonical_mode: str) -> bool:
    return canonical_mode in MARKET_MODES


def is_promoter_category(canonical_category: str) -> bool:
    return canonical_category in PROMOTER_CATEGORIES


# --------------------------------------------------------------------------- #
# Corporate-actions purpose bucketing (free-text -> category)
# --------------------------------------------------------------------------- #

def corp_action_bucket(purpose: str) -> str:
    """Bucket a BSE corporate-action 'Purpose' free-text string into a category."""
    p = (purpose or "").lower()
    if not p:
        return "OTHER"
    # REIT/InvIT unit distributions before the dividend check: NSE phrases them
    # "Distribution - Rs X Per Unit ..." with dividend/interest as components.
    if "income distribution" in p or ("distribution" in p and "unit" in p):
        return "REIT_INVIT"
    if "dividend" in p:
        return "DIVIDEND"
    if "bonus" in p:
        return "BONUS"
    if "split" in p or "sub-division" in p or "sub division" in p or "face value" in p:
        return "SPLIT"
    if "buy back" in p or "buyback" in p or "buy-back" in p:
        return "BUYBACK"
    if "right" in p:
        return "RIGHTS"
    if any(w in p for w in ("amalgamation", "merger", "demerger", "arrangement",
                            "scheme", "spin off", "spin-off")):
        return "MERGER_DEMERGER"
    if "preferential" in p or "warrant" in p:
        return "PREFERENTIAL"
    if "open offer" in p or "delisting" in p:
        return "OPEN_OFFER"
    if "invit" in p or "reit" in p:
        return "REIT_INVIT"
    if any(w in p for w in ("resolution plan", "suspension", "insolvency",
                            "liquidation", "reduction of capital", "consolidation")):
        return "CAPITAL_RESTRUCTURE"
    if any(w in p for w in ("redemption", "interest", "debenture", "bond")):
        return "DEBT"
    if any(w in p for w in ("agm", "egm", "general meeting", "meeting")):
        return "MEETING"
    return "OTHER"
