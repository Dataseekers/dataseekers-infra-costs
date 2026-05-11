#!/usr/bin/env python3
"""Cost dashboard — Streamlit app for dataseekers infrastructure costs."""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import date
from collectors.base import get_bq_client

st.set_page_config(
    page_title="Dataseekers Costs",
    page_icon="💰",
    layout="wide",
)

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


# ── Sidebar ──
with st.sidebar:
    if st.button("Clear cache", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ── Header ──
st.title("Dataseekers Infrastructure Costs")

months = get_available_months()
if not months:
    st.warning("No data available yet.")
    st.stop()

selected_month = st.selectbox("Month", months, index=0)
data = get_month_data(selected_month)

# ── KPI cards ──
col0, col1, col2, col3, col4 = st.columns(5)

total = data["total"]
prev = data["prev_total"]
change = ((total - prev) / prev * 100) if prev > 0 else 0

daily_df = data["daily"]
days = len(daily_df) if len(daily_df) > 0 else 1
cost_per_day = total / days

col0.metric("Cost / Day", f"€{cost_per_day:,.0f}", help=f"Average over {days} days with data")
col1.metric("Total", f"€{total:,.0f}", f"{change:+.1f}%" if prev > 0 else "—")
col2.metric("Providers", f"{len(data['by_provider'])}")
col3.metric("Business Units", f"{len(data['by_bu'])}")
col4.metric("Previous Month", f"€{prev:,.0f}" if prev > 0 else "—")

st.divider()

# ── Row 1: By BU + By Provider ──
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Cost by Business Unit")
    if len(data["by_bu"]) > 0:
        fig = px.pie(
            data["by_bu"],
            values="total",
            names="business_unit",
            hole=0.4,
        )
        fig.update_traces(textinfo="label+percent", textposition="outside")
        fig.update_layout(showlegend=False, margin=dict(t=20, b=20, l=20, r=20))
        st.plotly_chart(fig, use_container_width=True)

with col_right:
    st.subheader("Cost by Provider")
    if len(data["by_provider"]) > 0:
        fig = px.bar(
            data["by_provider"],
            x="total",
            y="provider",
            orientation="h",
            text=data["by_provider"]["total"].apply(lambda x: f"€{x:,.0f}"),
        )
        fig.update_layout(
            yaxis=dict(categoryorder="total ascending"),
            xaxis_title="",
            yaxis_title="",
            margin=dict(t=20, b=20),
        )
        fig.update_traces(textposition="outside")
        st.plotly_chart(fig, use_container_width=True)

# ── Row 2: Daily trend + Monthly evolution ──
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Daily Cost (current month)")
    if len(data["daily"]) > 0:
        fig = px.bar(data["daily"], x="date", y="total")
        fig.update_layout(
            xaxis_title="",
            yaxis_title="€",
            margin=dict(t=20, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)

with col_right:
    st.subheader("Monthly Trend")
    trend = get_monthly_trend()
    if len(trend) > 0:
        fig = px.bar(
            trend,
            x="month",
            y="total",
            text=trend["total"].apply(lambda x: f"€{x:,.0f}"),
        )
        fig.update_layout(
            xaxis_title="",
            yaxis_title="€",
            xaxis_type="category",
            margin=dict(t=20, b=20),
        )
        fig.update_traces(textposition="outside")
        st.plotly_chart(fig, use_container_width=True)

# ── Row 3: BU x Provider heatmap ──
st.subheader("Business Unit × Provider")
if len(data["by_bu_provider"]) > 0:
    pivot = data["by_bu_provider"].pivot_table(
        index="business_unit",
        columns="provider",
        values="total",
        fill_value=0,
    )
    fig = px.imshow(
        pivot,
        text_auto=".0f",
        aspect="auto",
        color_continuous_scale="Blues",
    )
    fig.update_layout(margin=dict(t=20, b=20))
    st.plotly_chart(fig, use_container_width=True)

# ── Row 4: Trend by BU ──
st.subheader("Monthly Trend by Business Unit")
trend_bu = get_trend_by_bu()
if len(trend_bu) > 0:
    fig = px.line(trend_bu, x="month", y="total", color="business_unit", markers=True)
    fig.update_layout(
        xaxis_title="",
        yaxis_title="€",
        legend_title="",
        margin=dict(t=20, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)

# ── Row 5: Top cost lines ──
st.subheader("Top 15 Cost Lines")
if len(data["top_lines"]) > 0:
    display = data["top_lines"].copy()
    display["total"] = display["total"].apply(lambda x: f"€{x:,.2f}")
    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "business_unit": "Business Unit",
            "provider": "Provider",
            "category": "Category",
            "description": "Description",
            "total": "Amount",
        },
    )
