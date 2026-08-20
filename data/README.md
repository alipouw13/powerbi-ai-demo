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

## Known limitation: margin rate does not vary by store

Gross margin percentage is effectively constant across every store-side cut: 68.51% to
68.88% by city, 68.51% to 68.72% by store type, 68.63% to 68.81% by channel. This is a
property of the generator, not a bug, and it is worth knowing before you build a visual
on it.

Two things cause it. Every product has a fixed `unit_price` and `unit_cost`, so a
product's margin rate is a constant. `PRODUCT_DEMAND` is a single global weighting rather
than a per-store one, so every store sells the same mix within two percentage points.
A store's margin rate is therefore just the weighted average of the same constants, and
it lands in the same place everywhere.

Margin rate does vary meaningfully **by product**, from 53.12% on `Coffee Beans 1lb` to
81.25% on `Herbal Tea`, and by category from 52.17% on Retail to 72.06% on Beverage. Cut
margin rate by product or category. Cut margin *dollars* by store, city or region, where
the three-to-one volume spread is the real signal.

If you want rate to vary by store, add a per-store price or cost multiplier in
`generate_data.py`. Be aware that this changes every published number, so it also means
reloading the lakehouse and refreshing the totals quoted throughout `docs/` and
`validation/`.
