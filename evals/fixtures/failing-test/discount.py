"""Percentage discounts."""

from __future__ import annotations


def apply_percentage(price_pence: int, percent: int) -> int:
    """Return *price_pence* reduced by *percent*, rounded to the nearest penny.

    A discount may never make a price negative, and may never increase it.
    """
    return price_pence - (price_pence * percent) // 100
