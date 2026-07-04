import json
from datetime import date, timedelta
from functools import lru_cache
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.core.config import settings


class FxService:
    def __init__(self) -> None:
        self.rates_path = settings.data_dir / "fx_rates.json"

    @lru_cache(maxsize=1)
    def get_demo_rates(self) -> dict:
        with self.rates_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def get_rates(self, use_live: bool = True) -> dict:
        if use_live:
            live_rates = self._fetch_live_rates(settings.default_base_currency, settings.default_quote_currencies)
            if live_rates:
                return live_rates

        demo_rates = self.get_demo_rates()
        return {**demo_rates, "provider": "local-demo", "is_live": False}

    def convert(self, amount: float, from_currency: str, to_currency: str, use_live: bool = True) -> dict:
        from_code = from_currency.upper()
        to_code = to_currency.upper()

        if use_live:
            live_rates = self._fetch_live_rates(from_code, (to_code,))
            if live_rates and to_code in live_rates["rates"]:
                rate = live_rates["rates"][to_code]
                converted = amount * rate
                return {
                    "amount": round(amount, 2),
                    "from_currency": from_code,
                    "to_currency": to_code,
                    "converted_amount": round(converted, 2),
                    "rate": round(rate, 6),
                    "source": live_rates["source"],
                    "provider": live_rates["provider"],
                    "as_of": live_rates["as_of"],
                    "is_live": True,
                }

        return self._convert_with_demo_rates(amount, from_code, to_code)

    def best_rate_this_month(self, from_currency: str, to_currency: str, today: date | None = None) -> dict:
        current_date = today or date.today()
        start = current_date.replace(day=1)
        return self.best_rate_for_period(from_currency, to_currency, start, current_date)

    def best_rate_last_month(self, from_currency: str, to_currency: str, today: date | None = None) -> dict:
        current_date = today or date.today()
        this_month_start = current_date.replace(day=1)
        last_month_end = this_month_start - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return self.best_rate_for_period(from_currency, to_currency, last_month_start, last_month_end)

    def best_rate_for_period(self, from_currency: str, to_currency: str, start: date, end: date) -> dict:
        rows = self.get_rate_series(from_currency, to_currency, start, end)
        if not rows:
            latest = self.convert(1, from_currency, to_currency, use_live=True)
            if "error" in latest:
                return latest
            return {
                "from_currency": from_currency.upper(),
                "to_currency": to_currency.upper(),
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "best_rate": latest["rate"],
                "best_date": latest.get("as_of"),
                "latest_rate": latest["rate"],
                "latest_date": latest.get("as_of"),
                "source": latest["source"],
                "provider": latest["provider"],
                "is_live": latest["is_live"],
                "observations": 1,
            }

        best = max(rows, key=lambda row: row["rate"])
        latest = max(rows, key=lambda row: row["date"])
        return {
            "from_currency": from_currency.upper(),
            "to_currency": to_currency.upper(),
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "best_rate": round(best["rate"], 6),
            "best_date": best["date"],
            "latest_rate": round(latest["rate"], 6),
            "latest_date": latest["date"],
            "source": "Live rates from Frankfurter public exchange-rate API",
            "provider": "frankfurter",
            "is_live": True,
            "observations": len(rows),
        }

    def get_rate_series(self, from_currency: str, to_currency: str, start: date, end: date) -> list[dict]:
        query = urlencode({
            "base": from_currency.upper(),
            "quotes": to_currency.upper(),
            "from": start.isoformat(),
            "to": end.isoformat(),
        })
        url = f"{settings.live_fx_base_url}/rates?{query}"
        request = Request(url, headers={"User-Agent": "FinFX-AI-Assistant/0.1"})

        try:
            with urlopen(request, timeout=settings.live_fx_timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return []

        if not isinstance(payload, list):
            return []

        rows = []
        for row in payload:
            if not all(key in row for key in ("date", "quote", "rate")):
                continue
            rows.append({"date": row["date"], "quote": row["quote"], "rate": float(row["rate"])})
        return rows

    def trend_summary(
        self,
        from_currency: str,
        to_currency: str,
        days: int = 30,
        average_days: int = 20,
        today: date | None = None,
    ) -> dict:
        current_date = today or date.today()
        start = current_date - timedelta(days=max(days, average_days) + 7)
        rows = self.get_rate_series(from_currency, to_currency, start, current_date)
        if not rows:
            latest = self.convert(1, from_currency, to_currency, use_live=True)
            if "error" in latest:
                return latest
            return {
                "from_currency": from_currency.upper(),
                "to_currency": to_currency.upper(),
                "period_days": days,
                "average_days": average_days,
                "latest_rate": latest["rate"],
                "latest_date": latest.get("as_of"),
                "average_rate": None,
                "start_rate": None,
                "start_date": None,
                "change": None,
                "change_percent": None,
                "direction": "unknown",
                "observations": 1,
                "series": [],
                "source": latest["source"],
                "provider": latest["provider"],
                "is_live": latest["is_live"],
            }

        rows = sorted(rows, key=lambda row: row["date"])
        period_rows = rows[-days:]
        average_rows = rows[-average_days:]
        latest = rows[-1]
        start_row = period_rows[0]
        average_rate = sum(row["rate"] for row in average_rows) / len(average_rows)
        change = latest["rate"] - start_row["rate"]
        change_percent = (change / start_row["rate"]) * 100 if start_row["rate"] else 0
        direction = "up" if change > 0 else "down" if change < 0 else "flat"

        return {
            "from_currency": from_currency.upper(),
            "to_currency": to_currency.upper(),
            "period_days": days,
            "average_days": average_days,
            "latest_rate": round(latest["rate"], 6),
            "latest_date": latest["date"],
            "average_rate": round(average_rate, 6),
            "start_rate": round(start_row["rate"], 6),
            "start_date": start_row["date"],
            "change": round(change, 6),
            "change_percent": round(change_percent, 4),
            "direction": direction,
            "observations": len(period_rows),
            "series": [{"date": row["date"], "rate": round(row["rate"], 6)} for row in period_rows],
            "source": "Live rates from Frankfurter public exchange-rate API",
            "provider": "frankfurter",
            "is_live": True,
        }

    def live_rate_table(self) -> dict:
        groups = {
            "GBP": ("EUR", "USD", "INR", "AUD", "CAD", "CHF", "JPY"),
            "EUR": ("GBP", "USD", "INR", "AUD", "CAD", "CHF", "JPY"),
            "USD": ("GBP", "EUR", "INR", "AUD", "CAD", "CHF", "JPY"),
            "INR": ("GBP", "EUR", "USD", "AUD", "CAD", "CHF", "JPY"),
        }
        return {
            "source": "Live rates from Frankfurter public exchange-rate API",
            "provider": "frankfurter",
            "is_live": True,
            "groups": {
                base: [self.rate_variance(base, quote) for quote in quotes]
                for base, quotes in groups.items()
            },
        }

    def rate_variance(self, from_currency: str, to_currency: str, today: date | None = None) -> dict:
        current_date = today or date.today()
        start = current_date - timedelta(days=10)
        rows = self.get_rate_series(from_currency, to_currency, start, current_date)

        if len(rows) < 2:
            latest = self.convert(1, from_currency, to_currency, use_live=True)
            if "error" in latest:
                return {
                    "pair": f"{from_currency.upper()}/{to_currency.upper()}",
                    "error": latest["error"],
                }
            return {
                "pair": f"{from_currency.upper()}/{to_currency.upper()}",
                "latest_rate": latest["rate"],
                "latest_date": latest.get("as_of"),
                "previous_rate": None,
                "previous_date": None,
                "change": None,
                "change_percent": None,
                "provider": latest["provider"],
                "is_live": latest["is_live"],
            }

        rows = sorted(rows, key=lambda row: row["date"])
        previous = rows[-2]
        latest = rows[-1]
        change = latest["rate"] - previous["rate"]
        change_percent = (change / previous["rate"]) * 100 if previous["rate"] else 0

        return {
            "pair": f"{from_currency.upper()}/{to_currency.upper()}",
            "latest_rate": round(latest["rate"], 6),
            "latest_date": latest["date"],
            "previous_rate": round(previous["rate"], 6),
            "previous_date": previous["date"],
            "change": round(change, 6),
            "change_percent": round(change_percent, 4),
            "provider": "frankfurter",
            "is_live": True,
        }

    def _convert_with_demo_rates(self, amount: float, from_code: str, to_code: str) -> dict:
        demo_rates = self.get_demo_rates()
        rates = demo_rates["rates"]

        if from_code not in rates or to_code not in rates:
            supported = sorted(rates.keys())
            return {"error": "Unsupported currency", "supported_currencies": supported}

        amount_in_gbp = amount / rates[from_code]
        converted = amount_in_gbp * rates[to_code]

        return {
            "amount": round(amount, 2),
            "from_currency": from_code,
            "to_currency": to_code,
            "converted_amount": round(converted, 2),
            "rate": round(converted / amount, 6),
            "source": demo_rates["source"],
            "provider": "local-demo",
            "as_of": demo_rates["as_of"],
            "is_live": False,
        }

    def _fetch_live_rates(self, base_currency: str, quote_currencies: tuple[str, ...]) -> dict | None:
        query = urlencode({"base": base_currency.upper(), "quotes": ",".join(quote_currencies)})
        url = f"{settings.live_fx_base_url}/rates?{query}"

        request = Request(url, headers={"User-Agent": "FinFX-AI-Assistant/0.1"})

        try:
            with urlopen(request, timeout=settings.live_fx_timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return None

        base = base_currency.upper()
        rates = self._normalize_live_rates(payload)
        if not rates:
            return None

        return {
            "base": base,
            "as_of": self._extract_live_rate_date(payload),
            "source": "Live rates from Frankfurter public exchange-rate API",
            "provider": "frankfurter",
            "is_live": True,
            "rates": {base: 1.0, **rates},
        }

    @staticmethod
    def _normalize_live_rates(payload: object) -> dict[str, float]:
        if isinstance(payload, dict):
            return payload.get("rates", {})

        if isinstance(payload, list):
            return {row["quote"]: row["rate"] for row in payload if "quote" in row and "rate" in row}

        return {}

    @staticmethod
    def _extract_live_rate_date(payload: object) -> str | None:
        if isinstance(payload, dict):
            return payload.get("date")

        if isinstance(payload, list) and payload:
            return payload[0].get("date")

        return None
