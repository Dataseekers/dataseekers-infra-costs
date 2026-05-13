import csv
import io
import time
from datetime import date, timedelta

import requests


_PREFETCH_DAYS = 90
_TIMEOUT = 30
_RETRIES = 3
_BACKOFF_BASE = 2.0

_RATES: dict[str, dict[date, float]] = {}
_FETCHED_RANGES: dict[str, tuple[date, date]] = {}


def _fetch_range(currency: str, start: date, end: date) -> dict[date, float]:
    """Fetch ECB daily rates for `currency` between `start` and `end` (inclusive).

    Returns a dict of {date: rate}. Weekends/holidays are absent — callers must
    fall back to the most recent prior observation.
    """
    url = (
        f"https://data-api.ecb.europa.eu/service/data/EXR/"
        f"D.{currency}.EUR.SP00.A"
        f"?startPeriod={start.isoformat()}"
        f"&endPeriod={end.isoformat()}"
        f"&format=csvdata"
    )

    last_exc: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            resp = requests.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            break
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
            last_exc = exc
            if attempt == _RETRIES - 1:
                raise
            time.sleep(_BACKOFF_BASE ** attempt)
    else:
        raise last_exc  # pragma: no cover

    rates: dict[date, float] = {}
    for row in csv.DictReader(io.StringIO(resp.text)):
        try:
            rates[date.fromisoformat(row["TIME_PERIOD"])] = float(row["OBS_VALUE"])
        except (KeyError, ValueError):
            continue
    return rates


def _ensure_loaded(currency: str, ref_date: date) -> None:
    """Ensure the in-memory cache covers `ref_date` for `currency`."""
    fetched = _FETCHED_RANGES.get(currency)
    if fetched and fetched[0] <= ref_date <= fetched[1]:
        return

    end = ref_date
    start = ref_date - timedelta(days=_PREFETCH_DAYS)
    if fetched:
        start = min(start, fetched[0])
        end = max(end, fetched[1])

    new_rates = _fetch_range(currency, start, end)
    bucket = _RATES.setdefault(currency, {})
    bucket.update(new_rates)
    _FETCHED_RANGES[currency] = (start, end)


def get_ecb_rate(currency: str, ref_date: date) -> float:
    """Get EUR exchange rate from ECB for a given currency and date.

    Returns the rate to convert FROM the given currency TO EUR.
    E.g., if USD rate is 1.08, then $100 = €92.59 (100 / 1.08).
    """
    if currency == "EUR":
        return 1.0

    _ensure_loaded(currency, ref_date)
    bucket = _RATES.get(currency) or {}

    candidates = [d for d in bucket if d <= ref_date]
    if not candidates:
        raise ValueError(f"No ECB rate found for {currency} on or before {ref_date}")
    return bucket[max(candidates)]


def convert_to_eur(amount: float, currency: str, ref_date: date) -> tuple[float, float]:
    """Convert amount to EUR. Returns (eur_amount, exchange_rate)."""
    rate = get_ecb_rate(currency, ref_date)
    return amount / rate, rate
