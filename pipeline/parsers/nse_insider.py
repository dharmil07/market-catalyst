"""Parse NSE insider-trading exports into canonical records.

NSE exports add three fields BSE lacks and which we surface in the UI:
Regulation (the SEBI clause), a precise broadcast datetime, and the XBRL link to
the original filing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .. import normalize as nz
from ..util import col, read_csv_dicts


def _reject_annual_format(rec: dict, path: Path) -> None:
    """Fail loudly on NSE's "Annual PIT" export, which looks similar but is a
    coarser, incompatible dataset: no XBRL links, no acquisition mode, and it
    merges sales with pledge invocations (and pledge creations with releases),
    so parsing it here would silently corrupt the dashboard's signals."""
    if any("ACQUIRED / DISPOSED - BUY" in k.upper() for k in rec):
        raise ValueError(
            f"{path.name} is NSE's 'Annual PIT' export, which this pipeline does "
            "not support. Download the regular Insider Trading export instead "
            "(https://www.nseindia.com/companies-listing/corporate-filings-insider-trading, "
            "'Insider Trading' search -> Download CSV; several date-range files "
            "can sit side by side in data/raw/insider/nse/), and remove this file."
        )


def parse(path: str | Path) -> Iterator[dict]:
    path = Path(path)
    for i, r in enumerate(read_csv_dicts(path)):
        if i == 0:
            _reject_annual_format(r, path)
        sec_type_acq = col(r, "TYPE OF SECURITY (ACQUIRED")
        deriv_type = col(r, "DERIVATIVE TYPE")
        contract_spec = col(r, "DERIVATIVE CONTRACT SPECIFICATION")
        shares = nz.parse_num(col(r, "NO. OF SECURITIES (ACQUIRED"))
        is_derivative = (
            "derivative" in sec_type_acq.lower()
            or (deriv_type not in ("", "-") and shares is None)
            or (shares is None and contract_spec not in ("", "-"))
        )

        category = nz.canon_category(col(r, "CATEGORY OF PERSON"))
        mode = nz.canon_mode(col(r, "MODE OF ACQUISITION"))
        xbrl = col(r, "XBRL")
        regulation = col(r, "REGULATION")
        broadcast = col(r, "BROADCAST")

        yield {
            "source": "NSE",
            "security_code": "",
            "symbol": col(r, "SYMBOL"),
            "company": col(r, "COMPANY"),
            "company_norm": nz.normco(col(r, "COMPANY")),
            "person": col(r, "NAME OF THE ACQUIRER"),
            "person_norm": nz.normp(col(r, "NAME OF THE ACQUIRER")),
            "category_raw": col(r, "CATEGORY OF PERSON"),
            "category": category,
            "txn_type_raw": col(r, "TRANSACTION TYPE"),
            "txn_type": nz.canon_txn_type(col(r, "TRANSACTION TYPE")),
            "mode_raw": col(r, "MODE OF ACQUISITION"),
            "mode": mode,
            "is_market": nz.is_market_mode(mode),
            "is_promoter": nz.is_promoter_category(category),
            "shares": shares,
            "value_raw": nz.parse_num(col(r, "VALUE OF SECURITY (ACQUIRED")),
            "prior_shares": nz.parse_num(col(r, "NO. OF SECURITY (PRIOR)")),
            "prior_pct": nz.parse_num(col(r, "% SHAREHOLDING (PRIOR)")),
            "post_shares": nz.parse_num(col(r, "NO. OF SECURITY (POST)")),
            "post_pct": nz.parse_num(col(r, "% POST")),
            "date_from": nz.iso(nz.parse_date(col(r, "ACQUISITION FROM"))),
            "date_to": nz.iso(nz.parse_date(col(r, "ACQUISITION TO"))),
            # Portal downloads say "INTIMATION"; the API's CSV says "INITMATION".
            "date_intimation": nz.iso(nz.parse_date(
                col(r, "TIMATION") or col(r, "INITMATION"))),
            "is_derivative": is_derivative,
            "exchange_traded": col(r, "EXCHANGE"),
            "regulation": regulation if regulation not in ("", "-") else None,
            "xbrl": xbrl if xbrl.startswith("http") else None,
            "broadcast": broadcast if broadcast not in ("", "-") else None,
            "raw_index": i,
        }
