import hashlib
import os
from datetime import date, datetime

import requests

from .base import CostCollector, CostRecord


# Mapping of known OVH order IDs to cloud project IDs.
# Each cloud project generates bills with the same orderId on renewal.
# Obtain these by checking /me/bill/{id} for recent bills of each project.
ORDER_TO_PROJECT = {
    # datasekeers (c-ovh shared cluster)
    245611311: "a1676b228191442aa3838b8e18e207c7",
    243683322: "a1676b228191442aa3838b8e18e207c7",
    # tickets_seeker
    245610356: "a1676b228191442aa3838b8e18e207c7",  # TODO: verify, may be tickets
    243684787: "e046bdd7877442a981ddd35a2d010c11",
    # development
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
