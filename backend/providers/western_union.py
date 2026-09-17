"""
WesternUnionProvider — Western Union's PRICECATALOG endpoint.

Endpoint: POST https://www.westernunion.com/wuconnect/prices/catalog

The catalog returns a matrix: every funding method crossed with every payout
method, each with its own rate, fee and speed.

What changed and why
--------------------
* WU charges its fee ON TOP of the principal, like Remitly. Declaring
  `FeeModel.ADDED` lets the engine re-base it instead of comparing a
  1000+fee spend against Wise's 1000.

* The old selection rule was "whichever row yields the highest receive
  amount", applied silently. WU's best rates sit on cash pickup and card
  funding, so the engine could compare a rival's bank-to-bank transfer
  against a WU row where the recipient has to walk into an agent location —
  unlabelled, and with the fee model un-rebased on top.

  Every row is now returned as an option carrying its own rail, fee and
  speed. Bank funding to bank deposit is this provider's own default order,
  but the ENGINE makes the final choice from the user's sort mode and
  filters. Cash pickup can still win on `cheapest`, which is a fair answer
  now that the rail is labelled and `pay_out_method` can filter it out.

* `speed_indicator` becomes real minutes, so "2-3" no longer sorts as a
  string and "0" (minutes) is properly distinguished from "0 days".

* Numbers are decoded as Decimal at the JSON boundary.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import List

import httpx

import delivery
from money import D, ZERO, floor_money
from providers.base import BaseProvider, decode_json_exact
from providers.quote import FeeModel, RawQuote

logger = logging.getLogger(__name__)


class WesternUnionProvider(BaseProvider):
    name = "Western Union"

    CATALOG_URL = "https://www.westernunion.com/wuconnect/prices/catalog"

    #: WU's fee schedule is banded by amount, so the fee at a 1000 principal
    #: may differ from the fee at 996. One correction pass gets the real fee
    #: for the principal we actually intend to send.
    MAX_FEE_REFINEMENTS = 1

    #: Status codes WU returns on a successful catalog lookup.
    OK_CODES = frozenset({"P0000", "P0039", "0"})

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/136.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://www.westernunion.com",
        "Referer": "https://www.westernunion.com/",
    }

    CURRENCY_TO_COUNTRY_ISO2 = {
        "USD": "US", "GBP": "GB", "EUR": "DE", "CAD": "CA", "AUD": "AU",
        "NZD": "NZ", "SGD": "SG", "NOK": "NO", "SEK": "SE", "DKK": "DK",
        "CHF": "CH", "HKD": "HK", "JPY": "JP", "INR": "IN", "PHP": "PH",
        "MXN": "MX", "NGN": "NG", "KES": "KE", "PKR": "PK", "BDT": "BD",
        "LKR": "LK", "NPR": "NP", "VND": "VN", "BRL": "BR", "COP": "CO",
        "PEN": "PE", "GHS": "GH", "ZAR": "ZA", "THB": "TH", "IDR": "ID",
        "MYR": "MY", "CNY": "CN", "KRW": "KR", "EGP": "EG", "MAD": "MA",
        "TZS": "TZ", "UGX": "UG", "RWF": "RW", "ETB": "ET", "PLN": "PL",
        "RON": "RO", "UAH": "UA", "GEL": "GE", "TRY": "TR",
    }

    #: Funding methods in like-for-like order — bank debit first, card last.
    FUND_IN_PREFERENCE = ["BANK", "ACH", "DEBIT", "CREDIT", "CARD"]

    async def fetch_raw_quote(
        self, amount: Decimal, currency_from: str, currency_to: str
    ) -> RawQuote:
        src = self.CURRENCY_TO_COUNTRY_ISO2.get(currency_from.upper())
        dst = self.CURRENCY_TO_COUNTRY_ISO2.get(currency_to.upper())

        if not src or not dst:
            missing = []
            if not src:
                missing.append(f"source={currency_from}")
            if not dst:
                missing.append(f"destination={currency_to}")
            return self._error(
                currency_from, currency_to,
                f"Unsupported corridor: no country mapping for {', '.join(missing)}",
            )

        try:
            return await self._quote_fee_inclusive(
                src, dst, amount, currency_from, currency_to
            )
        except Exception as e:
            return self._error(currency_from, currency_to, f"Western Union API error: {e}")

    # ------------------------------------------------------------------ #
    #  Fee-inclusive quoting
    # ------------------------------------------------------------------ #

    async def _quote_fee_inclusive(
        self,
        src_country: str,
        dst_country: str,
        budget: Decimal,
        currency_from: str,
        currency_to: str,
    ) -> RawQuote:
        """
        Find the principal whose principal + fee equals the user's budget.

        Same solve as Remitly: WU anchors on the principal, the user's real
        limit is total outlay, and WU's fee bands mean the correction has to
        be confirmed rather than assumed.
        """
        principal = budget
        last_data = None
        last_fee = None

        for attempt in range(self.MAX_FEE_REFINEMENTS + 1):
            data = await self._post_catalog(
                src_country, dst_country, principal, currency_from, currency_to
            )
            last_data = data

            rows = self._collect_rows(data)
            if not rows:
                raise ValueError("No processing services available for this corridor")

            fee = min(rows, key=self._row_sort_key)["gross_fee"]

            if last_fee is not None and fee == last_fee:
                break

            target = floor_money(budget - fee, currency_from)
            if target <= ZERO:
                raise ValueError(
                    f"Western Union fee of {fee} {currency_from} exceeds the "
                    f"{budget} being sent"
                )

            last_fee = fee
            if target == principal or attempt == self.MAX_FEE_REFINEMENTS:
                break
            principal = target

        return self._build_quote(last_data, principal, currency_from, currency_to)

    async def _post_catalog(
        self,
        src_country: str,
        dst_country: str,
        principal: Decimal,
        currency_from: str,
        currency_to: str,
    ) -> dict:
        corr_id = str(uuid.uuid4())
        payload = {
            "header_request": {
                "version": "0.5",
                "request_type": "PRICECATALOG",
                "correlation_id": corr_id,
                "transaction_id": corr_id,
            },
            "sender": {
                "client": "WUCOM",
                "channel": "WWEB",
                "cty_iso2_ext": src_country,
                "curr_iso3": currency_from.upper(),
                # str(), not float() — WU echoes this back into its own maths.
                "send_amount": str(principal),
                "funds_in": "*",
            },
            "receiver": {
                "cty_iso2_ext": dst_country,
                "curr_iso3": currency_to.upper(),
                "cty_iso2": dst_country,
            },
        }

        async with httpx.AsyncClient(timeout=15, headers=self.HEADERS) as client:
            resp = await client.post(self.CATALOG_URL, json=payload)
            resp.raise_for_status()
            data = decode_json_exact(resp)

        status = data.get("response_status") or {}
        code = status.get("code")
        if code and str(code) not in self.OK_CODES:
            raise ValueError(
                f"Western Union error [{code}]: {status.get('message', 'unknown')}"
            )
        return data

    # ------------------------------------------------------------------ #
    #  Parsing
    # ------------------------------------------------------------------ #

    def _collect_rows(self, data: dict) -> List[dict]:
        """Flatten the service-group matrix into a list of comparable rows."""
        rows: List[dict] = []

        for sg in data.get("services_groups") or []:
            service = sg.get("service_name") or "Transfer"
            for pg in sg.get("pay_groups") or []:
                rate = D(pg.get("fx_rate"), default=None)
                if not rate or rate <= ZERO:
                    continue

                eta_min, eta_max, business = delivery.parse_speed_indicator(
                    pg.get("speed_indicator")
                )

                rows.append({
                    "service": service,
                    "fund_in": str(pg.get("fund_in") or "").upper() or None,
                    "pay_out": str(pg.get("pay_out") or pg.get("delivery_method") or "").upper() or None,
                    "fx_rate": rate,
                    "gross_fee": D(pg.get("gross_fee")),
                    "receive_amount": D(pg.get("receive_amount"), default=None),
                    "eta_min": eta_min,
                    "eta_max": eta_max,
                    "business": business,
                })

        return rows

    def _row_sort_key(self, row: dict):
        """Bank funding first, then cheapest fee, then best rate."""
        fund_in = row.get("fund_in") or ""
        try:
            rank = self.FUND_IN_PREFERENCE.index(fund_in)
        except ValueError:
            rank = len(self.FUND_IN_PREFERENCE)
        return (rank, row["gross_fee"], -row["fx_rate"])

    def _build_quote(
        self,
        data: dict,
        principal: Decimal,
        currency_from: str,
        currency_to: str,
    ) -> RawQuote:
        rows = self._collect_rows(data)
        if not rows:
            return self._error(
                currency_from, currency_to,
                "No pay options found in Western Union catalog",
            )

        rows.sort(key=self._row_sort_key)

        options = [
            RawQuote(
                provider=self.name,
                currency_from=currency_from.upper(),
                currency_to=currency_to.upper(),
                principal=principal,
                fee=row["gross_fee"],
                fee_model=FeeModel.ADDED,
                exchange_rate=row["fx_rate"],
                receive_amount=row["receive_amount"],
                eta_min_minutes=row["eta_min"],
                eta_max_minutes=row["eta_max"],
                eta_is_business_days=row["business"],
                pay_in_method=row["fund_in"],
                pay_out_method=row["pay_out"],
                service_name=row["service"],
                rate_type="base",
            )
            for row in rows
        ]

        primary = options[0]
        primary.options = options

        logger.info(
            "[WesternUnion] %d options; default=%s/%s rate=%s fee=%s",
            len(options), primary.service_name, primary.pay_in_method,
            primary.exchange_rate, primary.fee,
        )
        return primary
