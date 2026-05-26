"""Cached BigQuery queries shared across dashboard pages."""

from datetime import date

import pandas as pd
import streamlit as st

from collectors.base import get_bq_client


@st.cache_data(ttl=3600)
def query_bq(sql: str) -> pd.DataFrame:
    client = get_bq_client()
    return client.query(sql).to_dataframe()


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

    by_bu = query_bq(f"""
        SELECT business_unit, SUM(amount) as total
        FROM `dataseekers-core.costs.raw_costs`
        WHERE date >= '{start}' AND date < '{end}'
        GROUP BY 1 ORDER BY total DESC
    """)

    by_provider = query_bq(f"""
        SELECT provider, SUM(amount) as total
        FROM `dataseekers-core.costs.raw_costs`
        WHERE date >= '{start}' AND date < '{end}'
        GROUP BY 1 ORDER BY total DESC
    """)

    by_bu_provider = query_bq(f"""
        SELECT business_unit, provider, SUM(amount) as total
        FROM `dataseekers-core.costs.raw_costs`
        WHERE date >= '{start}' AND date < '{end}'
        GROUP BY 1, 2 ORDER BY total DESC
    """)

    daily = query_bq(f"""
        SELECT date, SUM(total) as total
        FROM `dataseekers-core.costs.daily_prorated`
        WHERE date >= '{start}' AND date < '{end}'
        GROUP BY 1 ORDER BY 1
    """)

    top_lines = query_bq(f"""
        SELECT business_unit, provider, category, description, SUM(amount) as total
        FROM `dataseekers-core.costs.raw_costs`
        WHERE date >= '{start}' AND date < '{end}'
        GROUP BY 1, 2, 3, 4 ORDER BY total DESC
        LIMIT 15
    """)

    prev_total = query_bq(f"""
        SELECT SUM(amount) as total
        FROM `dataseekers-core.costs.raw_costs`
        WHERE date >= '{prev_start}' AND date < '{prev_end}'
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
    df = query_bq("""
        SELECT
            FORMAT_DATE('%Y-%m', date) as month,
            SUM(amount) as total
        FROM `dataseekers-core.costs.raw_costs`
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
    return query_bq("""
        SELECT
            FORMAT_DATE('%Y-%m', date) as month,
            business_unit,
            SUM(amount) as total
        FROM `dataseekers-core.costs.raw_costs`
        GROUP BY 1, 2 ORDER BY 1
    """)
