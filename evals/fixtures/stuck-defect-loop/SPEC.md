# TF-902: Quantity discount tiers

## Acceptance criteria

1. **Given** an order quantity and the tier table **when** the discount is
   chosen **then** it is the percent of the **highest** tier whose minimum
   quantity the order meets, and zero below the lowest tier.
