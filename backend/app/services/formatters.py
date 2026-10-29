"""
Single, consistent formatting module for DataPilot (charts, KPIs, tables, tooltips).

Implements:
- Indian lakh/crore formatting (12.5L, 3.2Cr) for rupee data and Indian numbering.
- Compact Western formatting (K, M, B) for standard numbering.
- Custom tickvals and ticktext generation for Plotly axes (since d3 has no Indian lakh/crore format).
- Date grain formatting (Jan 2025, 12 Jan, Q1 2025).
- Label truncation (24 characters) with '...' and text sanitization.
"""
from __future__ import annotations

import math
from datetime import datetime, date
from typing import Any, Sequence
import numpy as np
import pandas as pd


def is_indian_currency(currency_or_unit: str | None) -> bool:
    """Check if the metric or currency indicates Indian Rupees (INR, ₹, Rs)."""
    if not currency_or_unit:
        return False
    s = str(currency_or_unit).lower()
    return any(k in s for k in ("inr", "₹", "rupee", "rs", "lakh", "crore"))


def format_compact_number(
    val: Any,
    currency: str | None = None,
    decimals: int = 1,
    force_indian: bool | None = None,
) -> str:
    """
    Format a numeric value into a compact string:
    - If Indian context (or force_indian=True): Cr (Crore, 10^7), L (Lakh, 10^5), K (Thousand, 10^3).
    - Otherwise: B (Billion, 10^9), M (Million, 10^6), K (Thousand, 10^3).
    """
    if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
        return "—"
    try:
        num = float(val)
    except (ValueError, TypeError):
        return str(val)

    prefix = ""
    if currency:
        curr_lower = currency.lower()
        if "usd" in curr_lower or "$" in curr_lower:
            prefix = "$"
        elif "eur" in curr_lower or "€" in curr_lower:
            prefix = "€"
        elif "gbp" in curr_lower or "£" in curr_lower:
            prefix = "£"
        elif is_indian_currency(currency):
            prefix = "₹"

    use_indian = force_indian if force_indian is not None else (is_indian_currency(currency) or prefix == "₹")
    sign = "-" if num < 0 else ""
    abs_num = abs(num)

    if use_indian:
        if abs_num >= 1e7:
            val_scaled = abs_num / 1e7
            formatted = f"{val_scaled:.{decimals}f}" if decimals > 0 else f"{int(round(val_scaled))}"
            return f"{sign}{prefix}{formatted}Cr"
        elif abs_num >= 1e5:
            val_scaled = abs_num / 1e5
            formatted = f"{val_scaled:.{decimals}f}" if decimals > 0 else f"{int(round(val_scaled))}"
            return f"{sign}{prefix}{formatted}L"
        elif abs_num >= 1e3:
            val_scaled = abs_num / 1e3
            formatted = f"{val_scaled:.{decimals}f}" if decimals > 0 else f"{int(round(val_scaled))}"
            return f"{sign}{prefix}{formatted}K"
    else:
        if abs_num >= 1e9:
            val_scaled = abs_num / 1e9
            formatted = f"{val_scaled:.{decimals}f}" if decimals > 0 else f"{int(round(val_scaled))}"
            return f"{sign}{prefix}{formatted}B"
        elif abs_num >= 1e6:
            val_scaled = abs_num / 1e6
            formatted = f"{val_scaled:.{decimals}f}" if decimals > 0 else f"{int(round(val_scaled))}"
            return f"{sign}{prefix}{formatted}M"
        elif abs_num >= 1e3:
            val_scaled = abs_num / 1e3
            formatted = f"{val_scaled:.{decimals}f}" if decimals > 0 else f"{int(round(val_scaled))}"
            return f"{sign}{prefix}{formatted}K"

    # Regular integer or float under 1,000
    if abs_num == int(abs_num):
        return f"{sign}{prefix}{int(abs_num):,}"
    else:
        return f"{sign}{prefix}{abs_num:,.{min(decimals, 2)}f}".rstrip("0").rstrip(".")


def format_percent(val: Any, decimals: int = 1, is_fraction: bool = False) -> str:
    """Format a percentage with exactly the requested decimal places."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "—"
    try:
        num = float(val)
        if is_fraction:
            num *= 100.0
        return f"{num:.{decimals}f}%"
    except (ValueError, TypeError):
        return str(val)


def generate_axis_ticks(
    min_val: Any,
    max_val: float | None = None,
    max_ticks: int = 6,
    currency: str | None = None,
    is_percent: bool = False,
    force_zero: bool = True,
) -> tuple[list[float], list[str]]:
    """
    Generate clean, human-readable tick values and formatted tick text.
    Handles Indian lakh/crore formatting through explicit tickvals and ticktext.
    Ensures 5 to 8 ticks per axis without awkward fractions or scientific notation.
    Supports either (min_val, max_val) or a sequence/list of numbers as first argument.
    """
    if isinstance(min_val, (list, tuple, np.ndarray, pd.Series)):
        vals = [
            float(v) for v in min_val
            if v is not None and not (isinstance(v, float) and (np.isnan(v) or np.isinf(v)))
        ]
        if vals:
            cur_min = min(vals)
            cur_max = max(vals)
        else:
            cur_min = 0.0
            cur_max = 1.0
    else:
        cur_min = float(min_val) if min_val is not None else 0.0
        cur_max = float(max_val) if max_val is not None else (cur_min + 1.0)

    if force_zero and cur_min > 0:
        cur_min = 0.0

    if cur_min >= cur_max:
        cur_max = cur_min + 1.0

    span = cur_max - cur_min
    if span <= 0 or math.isinf(span) or math.isnan(span):
        return [cur_min], [format_compact_number(cur_min, currency=currency)]

    # Compute nice interval step
    target_ticks = max(4, min(max_ticks, 8))
    raw_step = span / max(target_ticks - 1, 1)
    mag = 10 ** math.floor(math.log10(raw_step))
    rel_step = raw_step / mag

    if rel_step < 1.5:
        step = 1.0 * mag
    elif rel_step < 3.0:
        step = 2.0 * mag
    elif rel_step < 7.0:
        step = 5.0 * mag
    else:
        step = 10.0 * mag

    first_tick = math.floor(cur_min / step) * step
    last_tick = math.ceil(cur_max / step) * step

    ticks: list[float] = []
    curr = first_tick
    while curr <= last_tick + (step * 0.01):
        if curr >= cur_min - (step * 0.01) and curr <= cur_max + (step * 0.01):
            ticks.append(round(curr, 8))
        curr += step

    if len(ticks) > 8:
        # Step down if too dense
        ticks = ticks[::2]

    # Format each tick
    tick_texts: list[str] = []
    for t in ticks:
        if is_percent:
            tick_texts.append(f"{t:.0f}%" if t == int(t) else f"{t:.1f}%")
        else:
            # Axis ticks: if 0, return "0"
            if t == 0:
                tick_texts.append("0")
            else:
                tick_texts.append(format_compact_number(t, currency=currency, decimals=1))

    return ticks, tick_texts


def format_date_by_grain(val: Any, grain: str | None = None) -> str:
    """Format timestamps and dates cleanly according to aggregation grain."""
    if val is None or pd.isna(val):
        return ""
    if isinstance(val, (int, float)):
        return str(val)

    try:
        dt = pd.to_datetime(val)
    except Exception:
        return str(val)

    if pd.isna(dt):
        return str(val)

    grain = (grain or "").lower()
    if grain == "year":
        return dt.strftime("%Y")
    elif grain == "quarter":
        q = (dt.month - 1) // 3 + 1
        return f"Q{q} {dt.year}"
    elif grain == "month":
        return dt.strftime("%b %Y")
    elif grain == "week":
        return f"Wk {dt.isocalendar()[1]} {dt.year}"
    elif grain == "day":
        return dt.strftime("%d %b %Y")
    else:
        # Default intelligent format
        if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
            return dt.strftime("%d %b %Y")
        return dt.strftime("%d %b %Y, %H:%M")


def truncate_label(label: Any, max_len: int = 24) -> str:
    """Truncate label to max_len characters with '...' if needed."""
    if label is None:
        return ""
    s = str(label).strip()
    if len(s) > max_len:
        return s[: max_len - 3].rstrip() + "..."
    return s
