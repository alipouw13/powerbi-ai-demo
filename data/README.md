# Data

Synthetic sales data for a fictional coffee retailer. No real customer data, ever.

## Files

| File | Grain | Rows |
| --- | --- | --- |
| `dim_date.csv` | one calendar day, 2024-01-01 to 2025-12-31 | 731 |
| `dim_product.csv` | one product | 12 |
| `dim_store.csv` | one store | 8 |
| `fact_sales.csv` | one sales order line | 64,335 |

Star schema. `fact_sales` joins to each dimension on its `*_key` column.

## Regenerating

```bash
python data/generate_data.py
```

Standard library only, no pip installs. The generator is seeded (`SEED = 20260101`), so
it produces byte-identical CSVs every time, on every machine.

**Do not change the seed.** Every number in `validation/`, `docs/`, and `README.md` is
derived from this exact dataset by `validation/ground_truth.py`. Changing the seed
invalidates all of them.

## Why it is deterministic

The demo scores AI answers against known-correct values. That only works if the correct
values are the same for everyone. A seeded generator means the ground truth in
`validation/scorecard.md` is valid for any person who clones this repo, without them
having to recompute anything.

## Shape of the data

- 8 stores across 3 US regions: West, Central, East
- 3 product categories: Beverage, Food, Retail
- 3 channels: In Store, Mobile Order, Delivery
- Weekday-weighted, with a modest year-over-year growth trend and seasonality

Deliberate quirks are built in so the demo has something to teach:

- Both `gross_amount` and `net_amount` exist, so "revenue" is ambiguous until an AI
  instruction defines it
- Key columns are numeric, so a model with default summarisation will happily sum them
- `unit_price` and `unit_cost` are list values on the product dimension, so averaging
  them across sales lines gives a misleading answer
