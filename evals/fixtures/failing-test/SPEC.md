# TF-901: Percentage discount

## Acceptance criteria

1. **Given** a price and a percentage **when** the discount is applied **then**
   the price is reduced by that percentage, rounded to the nearest penny.
2. **Given** a percentage above 100 **when** the discount is applied **then**
   the result is zero, never negative.
3. **Given** a percentage of zero **when** the discount is applied **then** the
   price is unchanged.
