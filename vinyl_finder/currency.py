"""
Currency conversion using Frankfurter (https://api.frankfurter.dev) -
free, open-source, no API key required. Rates are European Central Bank
daily reference rates (updated once per day on weekdays).

We fetch the full NZD-based rate table ONCE per script run and cache it,
rather than hitting the API per-item.
"""

import requests

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"


class CurrencyConverter:
    def __init__(self, base="NZD"):
        self.base = base
        self._rates = None  # dict like {"USD": 0.58, "EUR": 0.54, ...}

    def _load_rates(self):
        if self._rates is not None:
            return
        resp = requests.get(FRANKFURTER_URL, params={"base": self.base}, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        # data["rates"] is {currency_code: how much 1 NZD buys}
        self._rates = data.get("rates", {})
        self._rates[self.base] = 1.0

    def to_nzd(self, amount, from_currency):
        """Convert `amount` in `from_currency` into NZD."""
        if amount is None:
            return None
        from_currency = from_currency.upper()
        if from_currency == self.base:
            return round(amount, 2)
        self._load_rates()
        rate = self._rates.get(from_currency)
        if rate is None or rate == 0:
            # Frankfurter doesn't cover every currency (it's ECB-based,
            # ~30 currencies). If we can't convert, return None rather
            # than silently lying with a 1:1 rate.
            return None
        # rate = how much 1 NZD buys in `from_currency`
        # so 1 unit of from_currency = 1/rate NZD
        return round(amount / rate, 2)
