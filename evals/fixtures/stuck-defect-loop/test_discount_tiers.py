from discount_tiers import discount_percent


def test_below_the_lowest_tier_there_is_no_discount() -> None:
    assert discount_percent(9) == 0


def test_the_highest_tier_met_is_the_one_that_applies() -> None:
    """The spec says highest tier met. The implementation returns the lowest."""
    assert discount_percent(100) == 20
