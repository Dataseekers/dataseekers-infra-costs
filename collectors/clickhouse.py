import os
from datetime import date, datetime, timedelta

import requests

from .base import CostCollector, CostRecord
from .currency import convert_to_eur


# API limits to 30-day windows. Pick something safely below so a calendar
# month always fits in a single request and we only chunk for backfills.
MAX_WINDOW_DAYS = 30


class ClickHouseCollector(CostCollector):
    provider = "clickhouse"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.key_id = os.environ["CLICKHOUSE_CLOUD_API_KEY_ID"]
        self.key_secret = os.environ["CLICKHOUSE_CLOUD_API_KEY_SECRET"]
        self.org_id = os.environ["CLICKHOUSE_CLOUD_ORG_ID"]
        self.base_url = "https://api.clickhouse.cloud/v1"

    def _request(self, path: str, params: dict | None = None) -> dict:
        resp = requests.get(
            f"{self.base_url}{path}",
            params=params,
            auth=(self.key_id, self.key_secret),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def collect(self, start_date: date, end_date: date) -> list[CostRecord]:
        now = datetime.utcnow()
        records: list[CostRecord] = []

        # The API accepts up to 30-day windows. Chunk if caller requested more
        # (e.g. a multi-month backfill).
        cursor = start_date
        while cursor < end_date:
            window_end = min(cursor + timedelta(days=MAX_WINDOW_DAYS), end_date)
            records.extend(self._collect_window(cursor, window_end, now))
            cursor = window_end

        return records

    def _collect_window(
        self, start: date, end: date, collected_at: datetime
    ) -> list[CostRecord]:
        # API uses inclusive to_date, so subtract 1 day from our half-open
        # range. Avoid sending a to_date before from_date.
        to_date = end - timedelta(days=1)
        if to_date < start:
            return []

        payload = self._request(
            f"/organizations/{self.org_id}/usageCost",
            params={"from_date": start.isoformat(), "to_date": to_date.isoformat()},
        )

        # Defensive parsing: the response is documented as "grand total + list
        # of daily per-entity records" but the exact schema is not in the
        # public swagger. Probe for common shapes.
        result = payload.get("result", payload)
        currency = (result.get("currency") or "USD").upper()
        rows = (
            result.get("costs")
            or result.get("dailyCosts")
            or result.get("records")
            or []
        )
        if not rows:
            return []

        records: list[CostRecord] = []
        for row in rows:
            entity_id = (
                row.get("entityId")
                or row.get("serviceId")
                or row.get("entity")
                or "unknown"
            )
            entity_name = (
                row.get("entityName")
                or row.get("serviceName")
                or row.get("name")
                or entity_id
            )
            amount_native = float(
                row.get("amount")
                or row.get("cost")
                or row.get("total")
                or 0
            )
            if amount_native <= 0:
                continue

            row_date = row.get("date") or row.get("usageDate") or row.get("period")
            usage_date = (
                date.fromisoformat(row_date) if isinstance(row_date, str) else start
            )

            cost_type = (
                row.get("costType")
                or row.get("metric")
                or row.get("category")
                or "compute"
            )

            bu = self.get_bu(entity_id)
            if bu == self._default_bu():
                # Fallback to entity name in case mapping is keyed by name not id
                bu_by_name = self.get_bu(entity_name)
                if bu_by_name != self._default_bu():
                    bu = bu_by_name

            eur_amount, rate = convert_to_eur(amount_native, currency, usage_date)

            records.append(
                CostRecord(
                    date=usage_date,
                    provider=self.provider,
                    business_unit=bu,
                    category="database",
                    description=f"{cost_type}: {entity_name}",
                    amount=eur_amount,
                    original_currency=currency,
                    original_amount=amount_native,
                    exchange_rate=rate,
                    source="api",
                    collected_at=collected_at,
                )
            )

        return records

    def _default_bu(self) -> str:
        provider_mapping = self._bu_mapping.get(self.provider, {})
        if isinstance(provider_mapping, str):
            return provider_mapping
        return provider_mapping.get("default", "platform")
