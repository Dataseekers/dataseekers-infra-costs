import csv
import io
from datetime import date
from functools import lru_cache

import requests


@lru_cache(maxsize=32)
def get_ecb_rate(currency: str, ref_date: date) -> float:
    """Get EUR exchange rate from ECB for a given currency and date.

    Returns the rate to convert FROM the given currency TO EUR.
    E.g., if USD rate is 1.08, then $100 = €92.59 (100 / 1.08).
    """
    if currency == "EUR":
        return 1.0

    # Look back up to 10 days before start of month to handle weekends/holidays
    from datetime import timedelta
    lookback_start = ref_date.replace(day=1) - timedelta(days=10)
    url = (
        f"https://data-api.ecb.europa.eu/service/data/EXR/"
        f"D.{currency}.EUR.SP00.A"
        f"?startPeriod={lookback_start.isoformat()}"
        f"&endPeriod={ref_date.isoformat()}"
        f"&format=csvdata"
    )
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()

    reader = csv.DictReader(io.StringIO(resp.text))
    rows = list(reader)
    if not rows:
        raise ValueError(f"No ECB rate found for {currency} on {ref_date}")

    # Last row has the most recent rate
    rate = float(rows[-1]["OBS_VALUE"])
    return rate


def convert_to_eur(amount: float, currency: str, ref_date: date) -> tuple[float, float]:
    """Convert amount to EUR. Returns (eur_amount, exchange_rate)."""
    rate = get_ecb_rate(currency, ref_date)
    return amount / rate, rate
