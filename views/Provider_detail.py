#!/usr/bin/env python3
"""Provider drill-down: KPIs, daily trend, BU/category breakdowns, top services with MoM."""

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard_components import format_eur, period_selector_ui
from dashboard_navigation import BU_DETAIL
from dashboard_queries import (
    get_available_months,
    get_available_providers,
    get_segregated_bus,
    query_by_dim,
    query_daily,
    query_top_lines_mom,
    query_total,
)

st.title("Costs by provider")

months = get_available_months()
providers = get_available_providers()
if not months or not providers:
    st.warning("No data available yet.")
    st.stop()

# ── Filters ──
c_left, c_right = st.columns([1, 3])
with c_left:
    selected_provider = st.selectbox("Provider", providers, key="selected_provider")
with c_right:
    period = period_selector_ui(months)

# ── Aggregations ──
# Provider detail is a global view: drop segregated BUs everywhere so its totals,
# share and breakdowns match the Overview (segregated BUs live in their own page).
segregated = get_segregated_bus()
total = query_total(selected_provider, None, period.start, period.end, exclude_bus=segregated)
prev_total = query_total(selected_provider, None, period.prev_start, period.prev_end, exclude_bus=segregated)
org_total = query_total(None, None, period.start, period.end, exclude_bus=segregated)

mom_pct = ((total - prev_total) / prev_total * 100) if prev_total > 0 else None
share_pct = (total / org_total * 100) if org_total > 0 else 0
delta_eur = total - prev_total

by_bu = query_by_dim(selected_provider, None, "business_unit", period.start, period.end, exclude_bus=segregated)
by_category = query_by_dim(selected_provider, None, "category", period.start, period.end, exclude_bus=segregated)
top_lines = query_top_lines_mom(
    selected_provider, None,
    period.start, period.end, period.prev_start, period.prev_end,
    limit=20, exclude_bus=segregated,
)

top_bu = by_bu["business_unit"].iloc[0] if len(by_bu) > 0 else "—"
top_service = top_lines["description"].iloc[0] if len(top_lines) > 0 else "—"
if isinstance(top_service, str) and len(top_service) > 35:
    top_service = top_service[:32] + "…"

# ── KPI cards ──
st.divider()
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric(
    "Total",
    format_eur(total),
    f"{mom_pct:+.1f}% MoM" if mom_pct is not None else "—",
)
k2.metric(
    "Δ vs previous",
    format_eur(delta_eur) if prev_total > 0 else "—",
    help=f"Previous period: {format_eur(prev_total)}",
)
k3.metric("Share of org total", f"{share_pct:.1f}%", help=format_eur(org_total))
k4.metric("Top BU", top_bu)
k5.metric("Top service", top_service)

st.divider()

# ── Chart 1: Daily cost ──
# Hide the chart when all records fall on day 1 of a month — signature of
# providers that are collected monthly (ovh, brightdata, bitbucket, claude_ai)
# and stored as a single row on the 1st. Detection is data-driven so a new
# monthly collector wouldn't need a code change here.
daily = query_daily(selected_provider, None, period.start, period.end, exclude_bus=segregated)
if len(daily) > 0:
    is_monthly_provider = pd.to_datetime(daily["date"]).dt.day.eq(1).all()
    if not is_monthly_provider:
        st.subheader(f"Daily cost — {period.label}")
        fig = px.bar(daily, x="date", y="total")
        fig.update_layout(xaxis_title="", yaxis_title="€", margin=dict(t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)
else:
    st.subheader(f"Daily cost — {period.label}")
    st.info("No data in this period.")

# ── Chart 2 + 3: Breakdowns ──
col_left, col_right = st.columns(2)
with col_left:
    st.subheader(f"By Business Unit — {selected_provider}")
    if len(by_bu) > 0:
        fig = px.bar(
            by_bu, x="total", y="business_unit", orientation="h",
            text=by_bu["total"].apply(lambda x: format_eur(x)),
        )
        fig.update_layout(
            yaxis=dict(categoryorder="total ascending"),
            xaxis_title="", yaxis_title="", margin=dict(t=20, b=20),
        )
        fig.update_traces(textposition="outside")
        st.plotly_chart(fig, use_container_width=True)

        bu_options = by_bu["business_unit"].tolist()
        if bu_options:
            gc1, gc2 = st.columns([3, 1])
            with gc1:
                st.selectbox("Drill into BU", bu_options, key="selected_bu")
            with gc2:
                st.write("")
                st.page_link(BU_DETAIL, label="View detail →")
    else:
        st.info("No data.")

with col_right:
    st.subheader(f"By Category — {selected_provider}")
    if len(by_category) > 0:
        fig = px.pie(by_category, values="total", names="category", hole=0.4)
        fig.update_traces(textinfo="label+percent", automargin=True)
        fig.update_layout(showlegend=False, margin=dict(t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data.")

# ── Chart 4: Top services with MoM ──
st.subheader(f"Top 20 cost lines — {selected_provider}")
if len(top_lines) > 0:
    # Numeric columns + column_config formatting → sort by value, not by string.
    display = top_lines.copy().drop(columns=["provider"])
    st.dataframe(
        display, use_container_width=True, hide_index=True,
        column_config={
            "description": "Description",
            "business_unit": "BU",
            "category": "Category",
            "current_amt": st.column_config.NumberColumn("Current", format="€%.2f"),
            "prev_amt": st.column_config.NumberColumn("Previous", format="€%.2f"),
            "delta_eur": st.column_config.NumberColumn("Δ €", format="€%+.2f"),
            "delta_pct": st.column_config.NumberColumn("Δ %", format="%+.1f%%"),
        },
    )
else:
    st.info("No top lines for this period.")
