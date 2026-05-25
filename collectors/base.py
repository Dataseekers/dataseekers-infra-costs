import json
import os
import tempfile
from dataclasses import dataclass, asdict
from datetime import date, datetime
from abc import ABC, abstractmethod

import yaml
from google.cloud import bigquery


@dataclass
class CostRecord:
    date: date
    provider: str
    business_unit: str
    category: str
    description: str
    amount: float
    original_currency: str
    original_amount: float
    exchange_rate: float
    source: str
    collected_at: datetime

    def to_dict(self):
        d = asdict(self)
        d["date"] = self.date.isoformat()
        d["collected_at"] = self.collected_at.isoformat()
        return d


def get_bq_client() -> bigquery.Client:
    """Create BigQuery client.

    Supports 3 auth methods (in priority order):
    1. Streamlit secrets (gcp_service_account in .streamlit/secrets.toml)
    2. GOOGLE_CREDENTIALS_JSON env var (for CI pipelines)
    3. Application Default Credentials (local dev with gcloud auth)
    """
    # 1. Streamlit secrets
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets:
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"])
            )
            return bigquery.Client(project="dataseekers-core", credentials=creds)
    except Exception:
        pass

    # 2. CI env var
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        tmpfile = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmpfile.write(creds_json)
        tmpfile.close()
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = tmpfile.name

    # 3. ADC fallback
    return bigquery.Client(project="dataseekers-core")


class CostCollector(ABC):
    provider: str
    table_id: str = "dataseekers-core.costs.raw_costs"

    def __init__(self, bu_mapping_path: str = "config/bu-mapping.yaml"):
        with open(bu_mapping_path) as f:
            self._bu_mapping = yaml.safe_load(f)

    @abstractmethod
    def collect(self, start_date: date, end_date: date) -> list[CostRecord]:
        raise NotImplementedError

    def get_bu(self, key: str, record_date: date | None = None) -> str:
        provider_mapping = self._bu_mapping.get(self.provider, {})
        if isinstance(provider_mapping, str):
            return provider_mapping

        # Check in sub-mappings (projects, compartments, zones, services, etc.)
        for section in ("projects", "compartments", "zones", "services"):
            mapping = provider_mapping.get(section, {})
            if key in mapping:
                value = mapping[key]
                if isinstance(value, list):
                    return self._resolve_dated_bu(key, value, record_date)
                return value

        return provider_mapping.get("default", "platform")

    @staticmethod
    def _resolve_dated_bu(key: str, ranges: list, record_date: date | None) -> str:
        # When the record has no date (e.g. fixed-cost collectors), fall back
        # to the currently-open range (the one with `to: null`).
        if record_date is None:
            for entry in ranges:
                if entry.get("to") is None:
                    return entry["bu"]
            return ranges[-1]["bu"]
        for entry in ranges:
            frm = entry.get("from")
            to = entry.get("to")
            frm_d = date.fromisoformat(frm) if frm else None
            to_d = date.fromisoformat(to) if to else None
            if frm_d and record_date < frm_d:
                continue
            if to_d and record_date > to_d:
                continue
            return entry["bu"]
        raise ValueError(
            f"No date range matches {record_date} for key {key!r} in bu-mapping"
        )

    def load(self, records: list[CostRecord], bq_client: bigquery.Client | None = None):
        if not records:
            return

        client = bq_client or get_bq_client()
        start = min(r.date for r in records)
        end = max(r.date for r in records)

        # Delete existing records for this provider + date range (idempotent)
        client.query(
            f"""
            DELETE FROM `{self.table_id}`
            WHERE date BETWEEN @start AND @end AND provider = @provider
            """,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("start", "DATE", start),
                    bigquery.ScalarQueryParameter("end", "DATE", end),
                    bigquery.ScalarQueryParameter("provider", "STRING", self.provider),
                ]
            ),
        ).result()

        # Insert new records using load API (not streaming) to avoid buffer conflicts
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        )
        job = client.load_table_from_json(
            [r.to_dict() for r in records], self.table_id, job_config=job_config
        )
        job.result()
        if job.errors:
            raise RuntimeError(f"BigQuery load errors: {job.errors}")

    def validate(self, records: list[CostRecord]) -> list[str]:
        warnings = []
        for r in records:
            if r.amount < 0:
                warnings.append(f"Negative cost: {r.description} = {r.amount}")
        if not records:
            warnings.append(f"No records collected for {self.provider}")
        return warnings
