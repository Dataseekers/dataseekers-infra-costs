#!/usr/bin/env python3
"""Business Unit drill-down: KPIs, monthly trend, provider/category breakdowns, top services."""

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard_components import format_eur, period_selector_ui
from dashboard_navigation import PROVIDER_DETAIL
from dashboard_queries import (
    get_available_business_units,
    get_available_months,
    query_bu_monthly_trend,
    query_by_dim,
    query_daily,
    query_daily_by_provider,
    query_top_lines_mom,
    query_total,
)

st.title("Business Unit detail")

months = get_available_months()
bus = get_available_business_units()
if not months or not bus:
    st.warning("No data available yet.")
    st.stop()

# ── Filters ──
c_left, c_right = st.columns([1, 3])
with c_left:
    selected_bu = st.selectbox("Business Unit", bus, key="selected_bu")
with c_right:
    period = period_selector_ui(months)

# ── Aggregations ──
total = query_total(None, selected_bu, period.start, period.end)
prev_total = query_total(None, selected_bu, period.prev_start, period.prev_end)
org_total = query_total(None, None, period.start, period.end)

mom_pct = ((total - prev_total) / prev_total * 100) if prev_total > 0 else None
share_pct = (total / org_total * 100) if org_total > 0 else 0
delta_eur = total - prev_total

by_provider = query_by_dim(None, selected_bu, "provider", period.start, period.end)
by_provider_prev = query_by_dim(None, selected_bu, "provider", period.prev_start, period.prev_end)
by_category = query_by_dim(None, selected_bu, "category", period.start, period.end)
top_lines = query_top_lines_mom(
    None, selected_bu,
    period.start, period.end, period.prev_start, period.prev_end,
    limit=20,
)

top_provider = by_provider["provider"].iloc[0] if len(by_provider) > 0 else "—"
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
k4.metric("Top provider", top_provider)
k5.metric("Top service", top_service)

st.divider()

# ── Chart 1: Monthly trend (last 18 months) ──
st.subheader(f"Monthly trend — {selected_bu}")
trend = query_bu_monthly_trend(selected_bu).tail(18)
if len(trend) >= 3:
    fig = px.line(trend, x="month", y="total", markers=True)
    fig.update_layout(
        xaxis_title="", yaxis_title="€",
        xaxis_type="category", margin=dict(t=20, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    # Fallback for new BUs without enough monthly history
    daily = query_daily(None, selected_bu, period.start, period.end)
    if len(daily) > 0:
        st.caption("Not enough monthly history — showing daily view for the selected period.")
        fig = px.bar(daily, x="date", y="total")
        fig.update_layout(xaxis_title="", yaxis_title="€", margin=dict(t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data.")

# ── Chart 2 + 3: Provider breakdown (with MoM Δ inline) + Category breakdown ──
col_left, col_right = st.columns(2)
with col_left:
    st.subheader(f"By Provider — {selected_bu}")
    if len(by_provider) > 0:
        merged = by_provider.merge(
            by_provider_prev, on="provider", how="left", suffixes=("", "_prev"),
        )
        merged["total_prev"] = merged["total_prev"].fillna(0)
        merged["delta"] = merged["total"] - merged["total_prev"]
        merged["bar_text"] = merged.apply(
            lambda r: f"{format_eur(r['total'])}  ({'+' if r['delta'] >= 0 else ''}{format_eur(r['delta'])})",
            axis=1,
        )
        fig = px.bar(
            merged, x="total", y="provider", orientation="h", text="bar_text",
        )
        fig.update_layout(
            yaxis=dict(categoryorder="total ascending"),
            xaxis_title="", yaxis_title="", margin=dict(t=20, b=20),
        )
        fig.update_traces(textposition="outside")
        st.plotly_chart(fig, use_container_width=True)

        provider_options = by_provider["provider"].tolist()
        if provider_options:
            gc1, gc2 = st.columns([3, 1])
            with gc1:
                st.selectbox("Drill into provider", provider_options, key="selected_provider")
            with gc2:
                st.write("")
                st.page_link(PROVIDER_DETAIL, label="View detail →")
    else:
        st.info("No data.")

with col_right:
    st.subheader(f"By Category — {selected_bu}")
    if len(by_category) > 0:
        fig = px.pie(by_category, values="total", names="category", hole=0.4)
        fig.update_traces(textinfo="label+percent")
        fig.update_layout(showlegend=False, margin=dict(t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data.")

# ── Chart 4: Top cost lines with MoM ──
st.subheader(f"Top 20 cost lines — {selected_bu}")
if len(top_lines) > 0:
    display = top_lines.copy().drop(columns=["business_unit"])
    display["current_amt"] = display["current_amt"].apply(lambda x: format_eur(x, decimals=2))
    display["prev_amt"] = display["prev_amt"].apply(lambda x: format_eur(x, decimals=2))
    display["delta_eur"] = display["delta_eur"].apply(lambda x: f"€{x:+,.2f}")
    display["delta_pct"] = display["delta_pct"].apply(
        lambda x: f"{x:+.1f}%" if pd.notna(x) else "—"
    )
    st.dataframe(
        display, use_container_width=True, hide_index=True,
        column_config={
            "description": "Description",
            "provider": "Provider",
            "category": "Category",
            "current_amt": "Current",
            "prev_amt": "Previous",
            "delta_eur": "Δ €",
            "delta_pct": "Δ %",
        },
    )
else:
    st.info("No top lines for this period.")

# ── Chart 5: Day × Provider heatmap (collapsed) ──
with st.expander("Day × Provider heatmap"):
    daily_xp = query_daily_by_provider(selected_bu, period.start, period.end)
    if len(daily_xp) > 0:
        pivot = daily_xp.pivot_table(
            index="provider", columns="date", values="total", fill_value=0,
        )
        fig = px.imshow(
            pivot, aspect="auto", color_continuous_scale="Blues", text_auto=".0f",
        )
        fig.update_layout(margin=dict(t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data.")
