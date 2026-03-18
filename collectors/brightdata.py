import os
from datetime import date, datetime

import requests

from .base import CostCollector, CostRecord
from .currency import convert_to_eur


class BrightDataCollector(CostCollector):
    provider = "brightdata"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.token = os.environ["BRIGHTDATA_API_TOKEN"]
        self.base_url = "https://api.brightdata.com"

    def _request(self, path: str) -> dict | list:
        resp = requests.get(
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def collect(self, start_date: date, end_date: date) -> list[CostRecord]:
        now = datetime.utcnow()
        records = []

        zones = self._request("/zone/get_active_zones")

        for zone in zones:
            zone_name = zone["name"]
            cost_data = self._request(
                f"/zone/cost?zone={zone_name}"
                f"&from={start_date.isoformat()}"
                f"&to={end_date.isoformat()}"
            )

            for account, plans in cost_data.items():
                for plan, info in plans.items():
                    cost_usd = info.get("cost", 0)
                    if cost_usd <= 0:
                        continue

                    bu = self.get_bu(zone_name)
                    eur_amount, rate = convert_to_eur(cost_usd, "USD", start_date)

                    records.append(CostRecord(
                        date=start_date,
                        provider=self.provider,
                        business_unit=bu,
                        category="proxies",
                        description=f"zone: {zone_name} ({zone['type']})",
                        amount=eur_amount,
                        original_currency="USD",
                        original_amount=cost_usd,
                        exchange_rate=rate,
                        source="api",
                        collected_at=now,
                    ))

        return records
