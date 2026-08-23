"""Quantity-based discount tiers."""

from __future__ import annotations

#: ``(minimum quantity, percent)``, lowest tier first.
TIERS: tuple[tuple[int, int], ...] = (
    (10, 5),
    (50, 10),
    (100, 20),
)


def discount_percent(quantity: int) -> int:
    """Return the discount percent for *quantity*.

    The tier that applies is the highest one whose minimum quantity the order
    meets. Below the lowest tier there is no discount.
    """
    for minimum, percent in TIERS:
        if quantity >= minimum:
            return percent
    return 0
