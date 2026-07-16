"""Parse the NSE corporate-actions calendar export into canonical records.

Same calendar shape as the BSE feed, but keyed by trading symbol (NSE exports
carry no BSE security code) and without the no-delivery/payment-date columns.
Most events appear on both exchanges; match.merge_corp_actions collapses the
twins, so this feed's real contribution is NSE-only listings.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .. import normalize as nz
from ..util import col, read_csv_dicts


def parse(path: str | Path) -> Iterator[dict]:
    for i, r in enumerate(read_csv_dicts(path)):
        purpose = col(r, "PURPOSE")
        company = col(r, "COMPANY NAME") or col(r, "SYMBOL")
        yield {
            "source": "NSE",
            "security_code": "",
            "symbol": col(r, "SYMBOL"),
            "company": company,
            "company_norm": nz.normco(company),
            "purpose": purpose,
            "category": nz.corp_action_bucket(purpose),
            "ex_date": nz.iso(nz.parse_date(col(r, "EX-DATE"))),
            "record_date": nz.iso(nz.parse_date(col(r, "RECORD DATE"))),
            "bc_start": nz.iso(nz.parse_date(col(r, "BOOK CLOSURE START"))),
            "bc_end": nz.iso(nz.parse_date(col(r, "BOOK CLOSURE END"))),
            "nd_start": None,
            "nd_end": None,
            "payment_date": None,
            "raw_index": i,
        }
