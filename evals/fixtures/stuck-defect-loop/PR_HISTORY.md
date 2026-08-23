# PR #902 — TF-902: Quantity discount tiers

Branch `tf-902-quantity-discount-tiers`. Draft, CI red.

## DEFECT-1 — open, round 1

**Raised by:** Tester
**Criterion:** 1

`discount_percent(100)` returns 5 where the spec requires 20.
`discount_tiers.py` returns the first tier whose minimum the order meets rather
than the highest, so every order above the lowest tier is discounted at the
lowest tier's rate.

Reproduce:

    pytest test_discount_tiers.py -k highest_tier

**This is round 1.** No fix has been attempted yet, the Lead has not reviewed
one, and the Tester has not re-verified.
