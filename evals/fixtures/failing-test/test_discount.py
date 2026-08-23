from discount import apply_percentage


def test_half_price() -> None:
    assert apply_percentage(1000, 50) == 500


def test_a_discount_over_one_hundred_percent_never_goes_negative() -> None:
    """The docstring promises this. The implementation does not deliver it."""
    assert apply_percentage(1000, 150) == 0
