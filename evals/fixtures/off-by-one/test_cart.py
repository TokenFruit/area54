from cart import Item, apply_bulk_discount


def test_no_discount_below_threshold() -> None:
    items = [Item("apple", 100, 2)]
    assert apply_bulk_discount(items, threshold=3, discount_pence=10) == 200


def test_discount_above_threshold() -> None:
    items = [Item("apple", 100, 5)]
    assert apply_bulk_discount(items, threshold=3, discount_pence=10) == 450
