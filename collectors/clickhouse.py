import os
from datetime import date, datetime, timedelta

import requests

from .base import CostCollector, CostRecord
from .currency import convert_to_eur


# API limits to 30-day windows. Pick something safely below so a calendar
# month always fits in a single request and we only chunk for backfills.
MAX_WINDOW_DAYS = 30


# Fallback when bu-mapping.yaml has no rates table and no env var override.
# Latest known SCALE-tier rate, validated against the Mar 18 – Apr 18 invoice.
DEFAULT_CHC_USD_RATE = 0.9689


# Substring rules over entityName for BU inference. Keys must be unique enough
# not to clash with each other for the BUs we care about.
_NAME_BU_RULES = [
    ("rentacar", "rentacar"),
    ("hotels", "hotels"),
    ("puig", "puig"),
    ("retail", "retail"),
    ("tickets", "tickets"),
    ("ferries", "ferries"),
    ("flights", "flights"),
    ("turobserver", "turobserver"),
    ("paraty", "platform"),  # legacy company-wide warehouse
]


def _category_for_metric(metric_name: str) -> str:
    """Map a CHC metric name (e.g. computeCHC, publicDataTransferCHC) to one
    of the normalized categories used across providers."""
    n = metric_name.lower()
    if "compute" in n:
        return "compute"
    if "storage" in n or "backup" in n:
        return "storage"
    if "datatransfer" in n:
        return "network"
    return "other"


class ClickHouseCollector(CostCollector):
    provider = "clickhouse"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.key_id = os.environ["CLICKHOUSE_CLOUD_API_KEY_ID"]
        self.key_secret = os.environ["CLICKHOUSE_CLOUD_API_KEY_SECRET"]
        self.org_id = os.environ["CLICKHOUSE_CLOUD_ORG_ID"]
        self.base_url = "https://api.clickhouse.cloud/v1"

        # Env var override is a single rate applied to every record — useful
        # for testing or one-off backfills. Otherwise the per-cycle table in
        # bu-mapping.yaml is consulted; final fallback is DEFAULT_CHC_USD_RATE.
        env_override = os.environ.get("CLICKHOUSE_CLOUD_CHC_USD_RATE")
        self._rate_override = float(env_override) if env_override else None
        self._rate_table = self._load_rate_table()

    def _load_rate_table(self) -> list[tuple[date | None, date | None, float]]:
        raw = (self._bu_mapping.get(self.provider) or {}).get("chc_usd_rates") or []
        table: list[tuple[date | None, date | None, float]] = []
        for entry in raw:
            from_d = (
                date.fromisoformat(entry["from"]) if entry.get("from") else None
            )
            to_d = date.fromisoformat(entry["to"]) if entry.get("to") else None
            table.append((from_d, to_d, float(entry["rate"])))
        return table

    def _rate_for(self, day: date) -> float:
        if self._rate_override is not None:
            return self._rate_override
        for from_d, to_d, rate in self._rate_table:
            if (from_d is None or day >= from_d) and (to_d is None or day <= to_d):
                return rate
        return DEFAULT_CHC_USD_RATE

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
        cursor = start_date
        while cursor < end_date:
            window_end = min(cursor + timedelta(days=MAX_WINDOW_DAYS), end_date)
            records.extend(self._collect_window(cursor, window_end, now))
            cursor = window_end
        return records

    def _collect_window(
        self, start: date, end: date, collected_at: datetime
    ) -> list[CostRecord]:
        # API uses inclusive to_date; subtract 1 day from our half-open range
        # and skip degenerate windows.
        to_date = end - timedelta(days=1)
        if to_date < start:
            return []

        payload = self._request(
            f"/organizations/{self.org_id}/usageCost",
            params={"from_date": start.isoformat(), "to_date": to_date.isoformat()},
        )

        rows = (payload.get("result") or {}).get("costs") or []
        records: list[CostRecord] = []

        for row in rows:
            entity_id = row.get("entityId") or "unknown"
            entity_name = row.get("entityName") or entity_id
            try:
                usage_date = date.fromisoformat(row["date"])
            except (KeyError, ValueError):
                continue

            bu = self._resolve_bu(entity_id, entity_name)
            metrics = row.get("metrics") or {}

            for metric_name, chc_amount in metrics.items():
                if not chc_amount or chc_amount <= 0:
                    continue

                usd_amount = float(chc_amount) * self._rate_for(usage_date)
                eur_amount, rate = convert_to_eur(usd_amount, "USD", usage_date)

                records.append(
                    CostRecord(
                        date=usage_date,
                        provider=self.provider,
                        business_unit=bu,
                        category=_category_for_metric(metric_name),
                        description=f"{metric_name}: {entity_name}",
                        amount=eur_amount,
                        original_currency="USD",
                        original_amount=usd_amount,
                        exchange_rate=rate,
                        source="api",
                        collected_at=collected_at,
                    )
                )

        return records

    def _resolve_bu(self, entity_id: str, entity_name: str) -> str:
        # 1) Explicit override in bu-mapping.yaml (services:)
        explicit = self.get_bu(entity_id)
        if explicit != self._default_bu():
            return explicit

        # 2) Infer from entityName substring
        lowered = (entity_name or "").lower()
        for keyword, mapped in _NAME_BU_RULES:
            if keyword in lowered:
                return mapped

        # 3) Fallback
        return self._default_bu()

    def _default_bu(self) -> str:
        mapping = self._bu_mapping.get(self.provider, {})
        if isinstance(mapping, str):
            return mapping
        return mapping.get("default", "platform")
