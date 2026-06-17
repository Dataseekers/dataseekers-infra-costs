import hashlib
import os
from datetime import date, datetime

import requests

from .base import CostCollector, CostRecord


# Mapping of known OVH order IDs to cloud project IDs.
# WARNING: OVH mints a NEW orderId for every monthly bill, so this map needs a
# fresh entry per project each month. The tickets project (e046…) is the single
# ~€1.3k–2.5k Public Cloud bill each month; the larger ~€4.7k–6.4k bill is the
# shared c-ovh cluster (platform). Obtain new orderIds from the bill list in the
# OVH manager (or /me/bill). TODO: resolve the project from the bill detail's
# `domain`/`serviceName` to stop maintaining this map by hand.
ORDER_TO_PROJECT = {
    # ── tickets (project e046…) — one bill/month, orderId changes monthly ──
    241718298: "e046bdd7877442a981ddd35a2d010c11",  # Jan 2026  €1367.94
    243684787: "e046bdd7877442a981ddd35a2d010c11",  # Feb 2026  €1469.63
    245610356: "e046bdd7877442a981ddd35a2d010c11",  # Mar 2026  €1383.14
    247895564: "e046bdd7877442a981ddd35a2d010c11",  # Apr 2026  €1496.90
    249647283: "e046bdd7877442a981ddd35a2d010c11",  # May 2026  €1988.90
    251615387: "e046bdd7877442a981ddd35a2d010c11",  # Jun 2026  €2119.78
    # ── c-ovh shared cluster (project a1676…) = platform ──
    245611311: "a1676b228191442aa3838b8e18e207c7",
    243683322: "a1676b228191442aa3838b8e18e207c7",
    # ── development (project 7cd0c…) = platform ──
    245601669: "7cd0c51d3ecd46e0a2e9f0b862c45add",
    243700082: "7cd0c51d3ecd46e0a2e9f0b862c45add",
}


class OVHCollector(CostCollector):
    provider = "ovh"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.app_key = os.environ["OVH_APPLICATION_KEY"]
        self.app_secret = os.environ["OVH_APPLICATION_SECRET"]
        self.consumer_key = os.environ["OVH_CONSUMER_KEY"]
        self.base_url = "https://eu.api.ovh.com/1.0"

    def _request(self, method: str, path: str) -> dict | list:
        url = f"{self.base_url}{path}"
        body = ""
        timestamp = str(requests.get(f"{self.base_url}/auth/time").json())

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
        )
        resp.raise_for_status()
        return resp.json()

    def collect(self, start_date: date, end_date: date) -> list[CostRecord]:
        now = datetime.utcnow()
        records = []

        all_bill_ids = self._request("GET", "/me/bill")

        for bill_id in all_bill_ids:
            bill = self._request("GET", f"/me/bill/{bill_id}")
            bill_date = datetime.fromisoformat(bill["date"]).date()

            if not (start_date <= bill_date < end_date):
                continue

            # Map bill to project via orderId
            order_id = bill.get("orderId")
            project_id = ORDER_TO_PROJECT.get(order_id, "unknown")
            bu = self.get_bu(project_id)

            # Get bill line items
            detail_ids = self._request("GET", f"/me/bill/{bill_id}/details")

            for detail_id in detail_ids:
                detail = self._request("GET", f"/me/bill/{bill_id}/details/{detail_id}")
                amount = detail.get("totalPrice", {}).get("value", 0)

                if amount <= 0:
                    continue

                description = detail.get("description", "")
                category = self._classify(description)

                records.append(CostRecord(
                    date=bill_date,
                    provider=self.provider,
                    business_unit=bu,
                    category=category,
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
            mapped_project = ORDER_TO_PROJECT.get(order_id, "unknown")
            if project_id and mapped_project != project_id:
                continue

            bu = self.get_bu(mapped_project)

            for detail_id in self._request("GET", f"/me/bill/{bill_id}/details"):
                d = self._request("GET", f"/me/bill/{bill_id}/details/{detail_id}")
                rows.append({
                    "bill_id": bill_id,
                    "bill_date": bill_date.isoformat(),
                    "order_id": order_id,
                    "project_id": mapped_project,
                    "bu": bu,
                    "description": d.get("description", ""),
                    "domain": d.get("domain", ""),
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
