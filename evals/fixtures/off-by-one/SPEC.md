# TF-900: Bulk discount

## Acceptance criteria

1. **Given** a cart line **when** its quantity is **at or above** the bulk
   threshold **then** each unit of that line is discounted by the bulk amount.
2. **Given** a cart line **when** its quantity is below the threshold **then**
   no discount applies to that line.
3. **Given** an empty cart **when** the total is computed **then** it is zero.
