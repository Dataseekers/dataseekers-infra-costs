"""Cached BigQuery queries shared across dashboard pages."""

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

from collectors.base import get_bq_client


_RAW = "`dataseekers-core.costs.raw_costs`"
_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "bu-mapping.yaml"


@st.cache_data(ttl=3600)
def query_bq(sql: str) -> pd.DataFrame:
    client = get_bq_client()
    return client.query(sql).to_dataframe()


def get_segregated_bus() -> tuple[str, ...]:
    """BUs excluded from the global aggregate views (Overview + By provider).

    They stay fully available in the "By business unit" drill-down — this just
    keeps their spend out of the org-wide rollups and the per-provider view.

    Driven by `dashboard.segregated_bus` in config/bu-mapping.yaml. Empty by
    default, so with no config the dashboard behaves exactly as before. Returns
    a tuple so the value stays hashable when passed as a @st.cache_data arg.
    """
    try:
        with open(_CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return ()
    bus = (cfg.get("dashboard") or {}).get("segregated_bus") or []
    return tuple(bus)


def _bu_in_list(bus: tuple[str, ...]) -> str:
    """Render a tuple of BU names as a SQL IN-list body: 'a', 'b'."""
    return ", ".join(f"'{b}'" for b in bus)


def _exclude_clause(exclude_bus: tuple[str, ...]) -> str:
    """`AND business_unit NOT IN (...)` snippet, or '' when nothing to exclude."""
    return f" AND business_unit NOT IN ({_bu_in_list(exclude_bus)})" if exclude_bus else ""


@st.cache_data(ttl=3600)
def get_available_months() -> list[str]:
    df = query_bq("""
        SELECT DISTINCT FORMAT_DATE('%Y-%m', date) as month
        FROM `dataseekers-core.costs.raw_costs`
        ORDER BY month DESC
    """)
    return df["month"].tolist()


def get_month_data(month: str) -> dict:
    start = f"{month}-01"
    parts = month.split("-")
    year, mon = int(parts[0]), int(parts[1])
    if mon == 12:
        end = f"{year + 1}-01-01"
    else:
        end = f"{year}-{mon + 1:02d}-01"

    # Previous month
    if mon == 1:
        prev_start = f"{year - 1}-12-01"
        prev_end = start
    else:
        prev_start = f"{year}-{mon - 1:02d}-01"
        prev_end = start

    # Overview is a global view: drop any segregated BU so its spend doesn't
    # count toward org-wide totals (it's shown only in the By business unit page).
    excl = _exclude_clause(get_segregated_bus())

    by_bu = query_bq(f"""
        SELECT business_unit, SUM(amount) as total
        FROM `dataseekers-core.costs.raw_costs`
        WHERE date >= '{start}' AND date < '{end}'{excl}
        GROUP BY 1 ORDER BY total DESC
    """)

    by_provider = query_bq(f"""
        SELECT provider, SUM(amount) as total
        FROM `dataseekers-core.costs.raw_costs`
        WHERE date >= '{start}' AND date < '{end}'{excl}
        GROUP BY 1 ORDER BY total DESC
    """)

    by_bu_provider = query_bq(f"""
        SELECT business_unit, provider, SUM(amount) as total
        FROM `dataseekers-core.costs.raw_costs`
        WHERE date >= '{start}' AND date < '{end}'{excl}
        GROUP BY 1, 2 ORDER BY total DESC
    """)

    daily = query_bq(f"""
        SELECT date, SUM(total) as total
        FROM `dataseekers-core.costs.daily_prorated`
        WHERE date >= '{start}' AND date < '{end}'{excl}
        GROUP BY 1 ORDER BY 1
    """)

    top_lines = query_bq(f"""
        SELECT business_unit, provider, category, description, SUM(amount) as total
        FROM `dataseekers-core.costs.raw_costs`
        WHERE date >= '{start}' AND date < '{end}'{excl}
        GROUP BY 1, 2, 3, 4 ORDER BY total DESC
        LIMIT 15
    """)

    prev_total = query_bq(f"""
        SELECT SUM(amount) as total
        FROM `dataseekers-core.costs.raw_costs`
        WHERE date >= '{prev_start}' AND date < '{prev_end}'{excl}
    """)

    return {
        "by_bu": by_bu,
        "by_provider": by_provider,
        "by_bu_provider": by_bu_provider,
        "daily": daily,
        "top_lines": top_lines,
        "total": by_bu["total"].sum() if len(by_bu) > 0 else 0,
        "prev_total": prev_total["total"].iloc[0] if len(prev_total) > 0 and prev_total["total"].iloc[0] else 0,
    }


def get_monthly_trend() -> pd.DataFrame:
    excl = _exclude_clause(get_segregated_bus())
    df = query_bq(f"""
        SELECT
            FORMAT_DATE('%Y-%m', date) as month,
            SUM(amount) as total
        FROM `dataseekers-core.costs.raw_costs`
        WHERE TRUE{excl}
        GROUP BY 1 ORDER BY 1
    """)
    # Mark current month as incomplete
    current_month = date.today().strftime("%Y-%m")
    if len(df) > 0:
        df["month"] = df["month"].apply(
            lambda m: f"{m} *" if m == current_month else m
        )
    return df


def get_trend_by_bu() -> pd.DataFrame:
    excl = _exclude_clause(get_segregated_bus())
    return query_bq(f"""
        SELECT
            FORMAT_DATE('%Y-%m', date) as month,
            business_unit,
            SUM(amount) as total
        FROM `dataseekers-core.costs.raw_costs`
        WHERE TRUE{excl}
        GROUP BY 1, 2 ORDER BY 1
    """)


# ─── Drill-down helpers (Phase 1+) ─────────────────────────────────────────


@st.cache_data(ttl=3600)
def get_available_providers() -> list[str]:
    df = query_bq(f"SELECT DISTINCT provider FROM {_RAW} ORDER BY provider")
    return df["provider"].tolist()


@st.cache_data(ttl=3600)
def get_available_business_units() -> list[str]:
    # No exclusion here: segregated BUs (e.g. tickets) ARE selectable in the
    # "By business unit" page — that's the one place their data should appear.
    df = query_bq(f"SELECT DISTINCT business_unit FROM {_RAW} ORDER BY business_unit")
    return df["business_unit"].tolist()


@st.cache_data(ttl=3600)
def query_bu_monthly_trend(business_unit: str) -> pd.DataFrame:
    return query_bq(f"""
        SELECT FORMAT_DATE('%Y-%m', DATE_TRUNC(date, MONTH)) AS month,
               SUM(amount) AS total
        FROM {_RAW}
        WHERE business_unit = '{business_unit}'
        GROUP BY 1 ORDER BY 1
    """)


@st.cache_data(ttl=3600)
def query_daily_by_provider(business_unit: str, start: date, end: date) -> pd.DataFrame:
    return query_bq(f"""
        SELECT date, provider, SUM(amount) AS total
        FROM {_RAW}
        WHERE business_unit = '{business_unit}'
          AND date >= '{start}' AND date < '{end}'
        GROUP BY 1, 2 ORDER BY 1
    """)


def _filter_clause(
    provider: str | None,
    business_unit: str | None,
    exclude_bus: tuple[str, ...] = (),
) -> str:
    parts = []
    if provider:
        parts.append(f"provider = '{provider}'")
    if business_unit:
        parts.append(f"business_unit = '{business_unit}'")
    if exclude_bus:
        parts.append(f"business_unit NOT IN ({_bu_in_list(exclude_bus)})")
    return (" AND " + " AND ".join(parts)) if parts else ""


@st.cache_data(ttl=3600)
def query_total(
    provider: str | None,
    business_unit: str | None,
    start: date,
    end: date,
    exclude_bus: tuple[str, ...] = (),
) -> float:
    where = f"WHERE date >= '{start}' AND date < '{end}'{_filter_clause(provider, business_unit, exclude_bus)}"
    df = query_bq(f"SELECT SUM(amount) AS total FROM {_RAW} {where}")
    if len(df) == 0:
        return 0.0
    val = df["total"].iloc[0]
    return 0.0 if val is None or pd.isna(val) else float(val)


@st.cache_data(ttl=3600)
def query_daily(
    provider: str | None,
    business_unit: str | None,
    start: date,
    end: date,
    exclude_bus: tuple[str, ...] = (),
) -> pd.DataFrame:
    where = f"WHERE date >= '{start}' AND date < '{end}'{_filter_clause(provider, business_unit, exclude_bus)}"
    return query_bq(f"""
        SELECT date, SUM(amount) AS total
        FROM {_RAW} {where}
        GROUP BY 1 ORDER BY 1
    """)


@st.cache_data(ttl=3600)
def query_by_dim(
    provider: str | None,
    business_unit: str | None,
    dim: str,
    start: date,
    end: date,
    exclude_bus: tuple[str, ...] = (),
) -> pd.DataFrame:
    if dim not in ("business_unit", "provider", "category"):
        raise ValueError(f"unsupported dim: {dim!r}")
    where = f"WHERE date >= '{start}' AND date < '{end}'{_filter_clause(provider, business_unit, exclude_bus)}"
    return query_bq(f"""
        SELECT {dim}, SUM(amount) AS total
        FROM {_RAW} {where}
        GROUP BY 1 ORDER BY total DESC
    """)


@st.cache_data(ttl=3600)
def query_top_lines_mom(
    provider: str | None,
    business_unit: str | None,
    start: date,
    end: date,
    prev_start: date,
    prev_end: date,
    limit: int = 20,
    exclude_bus: tuple[str, ...] = (),
) -> pd.DataFrame:
    extra = _filter_clause(provider, business_unit, exclude_bus)
    return query_bq(f"""
        WITH curr AS (
          SELECT description, business_unit, provider, category, SUM(amount) AS amt
          FROM {_RAW}
          WHERE date >= '{start}' AND date < '{end}'{extra}
          GROUP BY 1, 2, 3, 4
        ),
        prev AS (
          SELECT description, SUM(amount) AS amt
          FROM {_RAW}
          WHERE date >= '{prev_start}' AND date < '{prev_end}'{extra}
          GROUP BY 1
        )
        SELECT
          COALESCE(c.description, p.description) AS description,
          c.business_unit, c.provider, c.category,
          IFNULL(c.amt, 0) AS current_amt,
          IFNULL(p.amt, 0) AS prev_amt,
          IFNULL(c.amt, 0) - IFNULL(p.amt, 0) AS delta_eur,
          SAFE_DIVIDE(IFNULL(c.amt, 0) - IFNULL(p.amt, 0), p.amt) * 100 AS delta_pct
        FROM curr c FULL OUTER JOIN prev p USING (description)
        ORDER BY ABS(IFNULL(c.amt, 0) - IFNULL(p.amt, 0)) DESC
        LIMIT {limit}
    """)
