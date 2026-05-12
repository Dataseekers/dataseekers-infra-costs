# dataseekers-infra-costs

## Tech Stack

- Python 3.12+
- Google Cloud BigQuery (storage + views)
- APIs: OVH, OCI, Bright Data, Bitbucket, GCP billing export

## Commands

```bash
# Collect costs (all providers)
python main.py collect --month 2026-02

# Collect specific providers
python main.py collect --month 2026-02 --providers gcp,ovh

# Dry run (no BigQuery write)
python main.py collect --month 2026-02 --dry-run --verbose

# Report
python main.py report --month 2026-02

# Validate (month-over-month sanity checks)
python main.py validate --month 2026-02

# Month shortcuts
python main.py collect --month previous
python main.py collect --month current
```

## Install

```bash
pip install -r requirements.txt
```

## Architecture

```
collectors/
  base.py          # CostCollector ABC + CostRecord dataclass + BQ load
  currency.py      # EUR conversion via ECB API
  gcp.py           # BigQuery billing export query
  ovh.py           # OVH billing API (signed requests)
  oci.py           # Oracle Cloud Usage API
  brightdata.py    # Zone cost API
  bitbucket.py     # Fixed subscription cost
config/
  bu-mapping.yaml  # Provider resource → business unit mapping
bigquery/
  schema.sql       # Table + views DDL
main.py            # CLI entrypoint: collect, report, validate
```

## BigQuery

- **Dataset:** `dataseekers-core.costs` (us-central1)
- **Table:** `raw_costs` — partitioned by date, clustered by provider + business_unit
- **Views:** `by_bu_month`, `by_provider_month`, `by_bu_provider`, `monthly_summary`, `daily_detail`

## Environment Variables

### Required per provider

| Provider | Variables |
|----------|-----------|
| GCP | `GCP_BILLING_TABLE` (optional, has default) + gcloud ADC |
| OVH | `OVH_APPLICATION_KEY`, `OVH_APPLICATION_SECRET`, `OVH_CONSUMER_KEY` |
| OCI | `OCI_TENANCY`, `OCI_USER`, `OCI_FINGERPRINT`, `OCI_KEY_FILE` (or `OCI_KEY_CONTENT`), `OCI_REGION` |
| Bright Data | `BRIGHTDATA_API_TOKEN` |
| Bitbucket | `BITBUCKET_USERNAME`, `BITBUCKET_API_TOKEN`, `BITBUCKET_WORKSPACE`, `BITBUCKET_SUBSCRIPTION_USD` |
| ClickHouse Cloud | `CLICKHOUSE_CLOUD_API_KEY_ID`, `CLICKHOUSE_CLOUD_API_KEY_SECRET`, `CLICKHOUSE_CLOUD_ORG_ID` |

## Related docs (`dataseekers-infra-docs`)

- [Monthly cost report runbook](https://github.com/Dataseekers/dataseekers-infra-docs/blob/main/runbooks/cost-report-monthly.md) — how to prepare the monthly email to management.
- [GCP billing export late records](https://github.com/Dataseekers/dataseekers-infra-docs/blob/main/reference/gcp-billing-export-late-records.md) — why the daily workflow re-collects `--month previous`.

## Testing

Skip tests — no test suite yet.

## Type Checking

Skip type checking — no mypy/pyright configured.

## Versioning

Skip versioning — no version tracking yet.

## Skip Skills

- frontend-patterns
- flask-patterns
- fastapi-patterns
- node-patterns
- project-structure
