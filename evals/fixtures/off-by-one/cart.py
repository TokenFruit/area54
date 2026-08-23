"""Shopping cart totals."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    name: str
    price_pence: int
    quantity: int


def apply_bulk_discount(items: list[Item], threshold: int, discount_pence: int) -> int:
    """Total the cart, discounting each item that meets the bulk threshold.

    Args:
        items: the cart contents.
        threshold: the quantity at which the bulk discount applies.
        discount_pence: pence off each unit, once the threshold is met.
    """
    total = 0
    for item in items:
        unit = item.price_pence
        if item.quantity > threshold:
            unit -= discount_pence
        total += unit * item.quantity
    return total
