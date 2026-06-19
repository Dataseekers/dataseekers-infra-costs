import hashlib
import os
import time
from datetime import date, datetime

import requests

from .base import CostCollector, CostRecord


# Earliest OVH bill date to sweep on a full re-collect. The Jan-2026 bill covers
# Dec-2025 usage (OVH bills in arrears), which is the first usage month we keep —
# this bounds the sweep to the cost-tracking era instead of walking the account's
# entire bill history every run.
_BILL_FLOOR = date(2026, 1, 1)


class OVHCollector(CostCollector):
    provider = "ovh"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.app_key = os.environ["OVH_APPLICATION_KEY"]
        self.app_secret = os.environ["OVH_APPLICATION_SECRET"]
        self.consumer_key = os.environ["OVH_CONSUMER_KEY"]
        self.base_url = "https://eu.api.ovh.com/1.0"
        self._time_delta: int | None = None  # OVH server-time offset, fetched once

    def _ovh_timestamp(self) -> str:
        """OVH-synced timestamp. Fetch the server time once and reuse the local
        offset, so a full bill sweep doesn't hit /auth/time on every request
        (fewer calls → less transient-failure surface)."""
        if self._time_delta is None:
            server = requests.get(f"{self.base_url}/auth/time", timeout=30).json()
            self._time_delta = int(server) - int(time.time())
        return str(int(time.time()) + self._time_delta)

    def _request(self, method: str, path: str) -> dict | list:
        url = f"{self.base_url}{path}"
        body = ""
        last_err: Exception | None = None
        for attempt in range(5):
            try:
                timestamp = self._ovh_timestamp()
                pre_sig = f"{self.app_secret}+{self.consumer_key}+{method}+{url}+{body}+{timestamp}"
                sig = "$1$" + hashlib.sha1(pre_sig.encode()).hexdigest()
                resp = requests.request(
                    method,
                    url,
                    headers={
                        "X-Ovh-Application": self.app_key,
                        "X-Ovh-Timestamp": timestamp,
                        "X-Ovh-Signature": sig,
                        "X-Ovh-Consumer": self.consumer_key,
                    },
                    timeout=60,
                )
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.RequestException as e:
                last_err = e
                self._time_delta = None  # re-sync time on the next attempt
                if attempt < 4:
                    time.sleep(min(2 ** attempt, 10))
        raise last_err

    def _resolve_bu(self, domain: str, description: str) -> str:
        """BU for a bill line: from its `domain` (= Public Cloud project ID), then
        any description-based override for that domain. Overrides exist because
        some BUs share a project (e.g. rentacar's r3-* nodes and "discovery" MySQL
        DBs live in the c-ovh project a1676). Scoped by domain so the same flavor
        in another project (e.g. tickets' r3-64) is untouched."""
        bu = self.get_bu(domain)
        desc = description.lower()
        for ov in self._bu_mapping.get("ovh", {}).get("description_overrides", []):
            if ov.get("domain") == domain and ov.get("contains", "").lower() in desc:
                return ov["bu"]
        return bu

    @staticmethod
    def _usage_date(detail: dict, bill_date: date) -> date:
        """Usage month of a line = first day of its `periodStart`. OVH bills in
        arrears (the bill is dated ~1 month after the usage it covers), so dating
        by the period keeps OVH aligned with the usage-dated providers (gcp/etc.).
        Falls back to the bill month when periodStart is absent."""
        ps = detail.get("periodStart")
        if ps:
            try:
                return date.fromisoformat(ps[:10]).replace(day=1)
            except ValueError:
                pass
        return bill_date.replace(day=1)

    def collect(self, start_date: date, end_date: date) -> list[CostRecord]:
        # OVH is dated by USAGE month (each line's periodStart), not bill date, and
        # a usage month can draw lines from more than one bill (arrears consumption
        # + any advance-billed fixed fees). So we sweep every bill from `_BILL_FLOOR`
        # and let load() atomically replace the whole OVH series. start_date/end_date
        # are intentionally ignored — OVH is a full-replace provider.
        now = datetime.utcnow()
        records = []

        for bill_id in self._request("GET", "/me/bill"):
            bill = self._request("GET", f"/me/bill/{bill_id}")
            bill_date = datetime.fromisoformat(bill["date"]).date()
            if bill_date < _BILL_FLOOR:
                continue

            for detail_id in self._request("GET", f"/me/bill/{bill_id}/details"):
                detail = self._request("GET", f"/me/bill/{bill_id}/details/{detail_id}")
                amount = detail.get("totalPrice", {}).get("value", 0)
                if amount <= 0:
                    continue

                domain = detail.get("domain", "")
                description = detail.get("description", "")
                records.append(CostRecord(
                    date=self._usage_date(detail, bill_date),
                    provider=self.provider,
                    business_unit=self._resolve_bu(domain, description),
                    category=self._classify(description),
                    description=f"{description} (bill: {bill_id})",
                    amount=amount,
                    original_currency="EUR",
                    original_amount=amount,
                    exchange_rate=1.0,
                    source="api",
                    collected_at=now,
                ))

        return records

    def inspect(self, start_date: date, end_date: date, project_id: str | None = None) -> list[dict]:
        """Return raw bill line items (no BQ write) for ad-hoc analysis.

        Each item carries description, domain, periodStart/End, quantity,
        unitPrice, totalPrice and the resolved bill_id / project_id / bu.
        Pass project_id to filter to a single Public Cloud project.
        """
        rows: list[dict] = []
        bill_ids = self._request("GET", "/me/bill")

        for bill_id in bill_ids:
            bill = self._request("GET", f"/me/bill/{bill_id}")
            bill_date = datetime.fromisoformat(bill["date"]).date()
            if not (start_date <= bill_date < end_date):
                continue

            order_id = bill.get("orderId")

            for detail_id in self._request("GET", f"/me/bill/{bill_id}/details"):
                d = self._request("GET", f"/me/bill/{bill_id}/details/{detail_id}")
                domain = d.get("domain", "")
                if project_id and domain != project_id:
                    continue
                rows.append({
                    "bill_id": bill_id,
                    "bill_date": bill_date.isoformat(),
                    "order_id": order_id,
                    "project_id": domain,
                    "bu": self._resolve_bu(domain, d.get("description", "")),
                    "description": d.get("description", ""),
                    "domain": domain,
                    "period_start": d.get("periodStart"),
                    "period_end": d.get("periodEnd"),
                    "quantity": d.get("quantity"),
                    "unit_price": (d.get("unitPrice") or {}).get("value"),
                    "total_price": (d.get("totalPrice") or {}).get("value", 0),
                    "category": self._classify(d.get("description", "")),
                })
        return rows

    def _classify(self, description: str) -> str:
        desc_lower = description.lower()
        if any(w in desc_lower for w in ("instance", "savings plan", "hourly consumption")):
            return "compute"
        if "storage" in desc_lower or "bucket" in desc_lower:
            return "storage"
        if "loadbalancer" in desc_lower or "gateway" in desc_lower or "floating ip" in desc_lower:
            return "network"
        if "mysql" in desc_lower or "database" in desc_lower:
            return "database"
        if "registry" in desc_lower:
            return "ci_cd"
        if "disk" in desc_lower:
            return "storage"
        return "other"
