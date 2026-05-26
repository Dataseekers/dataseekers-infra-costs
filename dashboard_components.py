"""UI helpers shared across dashboard pages."""

from dataclasses import dataclass
from datetime import date, timedelta

import streamlit as st


@dataclass
class Period:
    kind: str          # "month" | "3m" | "custom"
    label: str         # human label for chart titles
    start: date        # inclusive
    end: date          # EXCLUSIVE (use `date < end` in SQL)
    prev_start: date   # inclusive
    prev_end: date     # EXCLUSIVE


def _add_months(d: date, n: int) -> date:
    """Return the first day of d.month + n months."""
    total = d.year * 12 + (d.month - 1) + n
    year, month = divmod(total, 12)
    return date(year, month + 1, 1)


def period_selector_ui(months: list[str], key_prefix: str = "") -> Period:
    """Render the period-selector widgets and return the resolved Period."""
    kind_label = st.radio(
        "Period",
        ["Month", "Last 3 months", "Custom"],
        horizontal=True,
        key=f"{key_prefix}period_kind",
    )

    if kind_label == "Custom":
        today = date.today()
        default_start = today.replace(day=1)
        range_val = st.date_input(
            "Range",
            value=(default_start, today),
            key=f"{key_prefix}period_custom",
        )
        if isinstance(range_val, tuple) and len(range_val) == 2:
            start_d, end_inclusive = range_val
        else:  # single-date selection mid-edit
            start_d = end_inclusive = range_val if not isinstance(range_val, tuple) else range_val[0]
        end_d = end_inclusive + timedelta(days=1)
        length = (end_d - start_d).days
        prev_end = start_d
        prev_start = start_d - timedelta(days=length)
        label = f"{start_d.isoformat()} → {end_inclusive.isoformat()}"
        return Period("custom", label, start_d, end_d, prev_start, prev_end)

    anchor = st.selectbox("Anchor month", months, key=f"{key_prefix}selected_month")
    year, mon = map(int, anchor.split("-"))
    anchor_start = date(year, mon, 1)

    if kind_label == "Month":
        return Period(
            "month",
            anchor,
            anchor_start,
            _add_months(anchor_start, 1),
            _add_months(anchor_start, -1),
            anchor_start,
        )

    # Last 3 months ending at the anchor month (inclusive)
    start_d = _add_months(anchor_start, -2)
    end_d = _add_months(anchor_start, 1)
    return Period(
        "3m",
        f"{start_d.strftime('%Y-%m')} → {anchor}",
        start_d,
        end_d,
        _add_months(start_d, -3),
        start_d,
    )


def format_eur(amount: float, decimals: int = 0) -> str:
    return f"€{amount:,.{decimals}f}"
