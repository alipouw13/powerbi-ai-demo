"""Generate the synthetic Contoso Coffee dataset for the Power BI AI demo.

Standard library only. Deterministic (fixed seed) so every run of the demo,
and every accuracy check in validation/, sees exactly the same numbers.

Usage:
    python data/generate_data.py

Writes four CSV files next to this script:
    dim_date.csv, dim_product.csv, dim_store.csv, fact_sales.csv
"""

from __future__ import annotations

import csv
import datetime as dt
import random
from pathlib import Path

SEED = 20260101
START_DATE = dt.date(2024, 1, 1)
END_DATE = dt.date(2025, 12, 31)
OUT_DIR = Path(__file__).parent

PRODUCTS: list[dict[str, object]] = [
    # product_key, product_name, category, subcategory, unit_price, unit_cost
    {"product_key": 1, "product_name": "Espresso Single", "category": "Beverage", "subcategory": "Espresso", "unit_price": 2.75, "unit_cost": 0.70},
    {"product_key": 2, "product_name": "Espresso Double", "category": "Beverage", "subcategory": "Espresso", "unit_price": 3.50, "unit_cost": 0.95},
    {"product_key": 3, "product_name": "Latte Regular", "category": "Beverage", "subcategory": "Milk Coffee", "unit_price": 4.25, "unit_cost": 1.20},
    {"product_key": 4, "product_name": "Latte Large", "category": "Beverage", "subcategory": "Milk Coffee", "unit_price": 5.10, "unit_cost": 1.45},
    {"product_key": 5, "product_name": "Cappuccino", "category": "Beverage", "subcategory": "Milk Coffee", "unit_price": 4.10, "unit_cost": 1.15},
    {"product_key": 6, "product_name": "Cold Brew", "category": "Beverage", "subcategory": "Cold Coffee", "unit_price": 4.60, "unit_cost": 1.30},
    {"product_key": 7, "product_name": "Iced Latte", "category": "Beverage", "subcategory": "Cold Coffee", "unit_price": 4.75, "unit_cost": 1.35},
    {"product_key": 8, "product_name": "Herbal Tea", "category": "Beverage", "subcategory": "Tea", "unit_price": 3.20, "unit_cost": 0.60},
    {"product_key": 9, "product_name": "Blueberry Muffin", "category": "Food", "subcategory": "Bakery", "unit_price": 3.40, "unit_cost": 1.10},
    {"product_key": 10, "product_name": "Almond Croissant", "category": "Food", "subcategory": "Bakery", "unit_price": 3.95, "unit_cost": 1.40},
    {"product_key": 11, "product_name": "Breakfast Sandwich", "category": "Food", "subcategory": "Hot Food", "unit_price": 6.50, "unit_cost": 2.60},
    {"product_key": 12, "product_name": "Coffee Beans 1lb", "category": "Retail", "subcategory": "Packaged", "unit_price": 16.00, "unit_cost": 7.50},
]

STORES: list[dict[str, object]] = [
    # store_key, store_name, city, state, region, store_type, opened_date
    {"store_key": 1, "store_name": "Contoso Pike Place", "city": "Seattle", "state": "WA", "region": "West", "store_type": "Flagship", "opened_date": "2019-03-11"},
    {"store_key": 2, "store_name": "Contoso Bellevue Square", "city": "Bellevue", "state": "WA", "region": "West", "store_type": "Mall", "opened_date": "2020-08-24"},
    {"store_key": 3, "store_name": "Contoso Mission District", "city": "San Francisco", "state": "CA", "region": "West", "store_type": "Standard", "opened_date": "2021-01-18"},
    {"store_key": 4, "store_name": "Contoso River North", "city": "Chicago", "state": "IL", "region": "Central", "store_type": "Standard", "opened_date": "2020-05-04"},
    {"store_key": 5, "store_name": "Contoso Deep Ellum", "city": "Dallas", "state": "TX", "region": "Central", "store_type": "Standard", "opened_date": "2022-02-14"},
    {"store_key": 6, "store_name": "Contoso Midtown", "city": "New York", "state": "NY", "region": "East", "store_type": "Flagship", "opened_date": "2018-09-10"},
    {"store_key": 7, "store_name": "Contoso Back Bay", "city": "Boston", "state": "MA", "region": "East", "store_type": "Standard", "opened_date": "2021-06-21"},
    {"store_key": 8, "store_name": "Contoso Wynwood", "city": "Miami", "state": "FL", "region": "East", "store_type": "Kiosk", "opened_date": "2023-04-03"},
]

CHANNELS = ["In Store", "Mobile Order", "Delivery"]
CHANNEL_WEIGHTS = [0.62, 0.27, 0.11]

# Per-store demand multiplier. Flagship stores sell more, the kiosk sells less.
STORE_DEMAND = {1: 1.55, 2: 1.10, 3: 1.20, 4: 1.05, 5: 0.90, 6: 1.60, 7: 0.95, 8: 0.55}

# Relative popularity of each product.
PRODUCT_DEMAND = {1: 0.9, 2: 1.1, 3: 1.6, 4: 1.2, 5: 1.3, 6: 0.9, 7: 1.0, 8: 0.6, 9: 0.8, 10: 0.7, 11: 0.6, 12: 0.25}

# Month seasonality index, January through December. Cold months favour hot drinks.
MONTH_INDEX = [1.02, 0.96, 1.00, 0.98, 1.03, 1.08, 1.12, 1.10, 1.04, 1.06, 1.05, 1.14]

# Day of week index, Monday through Sunday.
WEEKDAY_INDEX = [1.05, 1.08, 1.10, 1.12, 1.20, 0.92, 0.78]


def daterange(start: dt.date, end: dt.date):
    day = start
    while day <= end:
        yield day
        day += dt.timedelta(days=1)


def write_csv(name: str, rows: list[dict], fieldnames: list[str]) -> Path:
    path = OUT_DIR / name
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def build_dim_date() -> list[dict]:
    rows = []
    for day in daterange(START_DATE, END_DATE):
        quarter = (day.month - 1) // 3 + 1
        rows.append(
            {
                "date_key": day.isoformat(),
                "year": day.year,
                "quarter": f"Q{quarter}",
                "month_number": day.month,
                "month_name": day.strftime("%B"),
                "year_month": day.strftime("%Y-%m"),
                "day_of_week": day.strftime("%A"),
                "day_of_week_number": day.isoweekday(),
                "is_weekend": "TRUE" if day.isoweekday() >= 6 else "FALSE",
            }
        )
    return rows


def build_fact_sales() -> list[dict]:
    rng = random.Random(SEED)
    rows: list[dict] = []
    order_id = 100000

    for day in daterange(START_DATE, END_DATE):
        # Gentle year over year growth so time intelligence measures have a trend.
        growth = 1.0 + (0.12 * ((day - START_DATE).days / 730.0))
        month_factor = MONTH_INDEX[day.month - 1]
        weekday_factor = WEEKDAY_INDEX[day.isoweekday() - 1]

        for store in STORES:
            store_key = int(store["store_key"])
            if dt.date.fromisoformat(str(store["opened_date"])) > day:
                continue
            base_lines = 9 * STORE_DEMAND[store_key] * growth * month_factor * weekday_factor
            line_count = max(1, int(rng.gauss(base_lines, base_lines * 0.18)))

            for _ in range(line_count):
                product = rng.choices(PRODUCTS, weights=[PRODUCT_DEMAND[int(p["product_key"])] for p in PRODUCTS], k=1)[0]
                quantity = rng.choices([1, 2, 3, 4], weights=[0.66, 0.24, 0.07, 0.03], k=1)[0]
                channel = rng.choices(CHANNELS, weights=CHANNEL_WEIGHTS, k=1)[0]

                unit_price = float(product["unit_price"])
                unit_cost = float(product["unit_cost"])
                # A small share of lines carry a promotional discount.
                discount_pct = rng.choices([0.0, 0.10, 0.20], weights=[0.86, 0.10, 0.04], k=1)[0]

                gross = unit_price * quantity
                discount = round(gross * discount_pct, 2)
                net = round(gross - discount, 2)
                cost = round(unit_cost * quantity, 2)

                order_id += 1
                rows.append(
                    {
                        "sales_order_id": order_id,
                        "date_key": day.isoformat(),
                        "store_key": store_key,
                        "product_key": int(product["product_key"]),
                        "channel": channel,
                        "quantity": quantity,
                        "gross_amount": round(gross, 2),
                        "discount_amount": discount,
                        "net_amount": net,
                        "cost_amount": cost,
                    }
                )
    return rows


def main() -> None:
    date_rows = build_dim_date()
    fact_rows = build_fact_sales()

    write_csv("dim_date.csv", date_rows, list(date_rows[0].keys()))
    write_csv(
        "dim_product.csv",
        [dict(p) for p in PRODUCTS],
        ["product_key", "product_name", "category", "subcategory", "unit_price", "unit_cost"],
    )
    write_csv(
        "dim_store.csv",
        [dict(s) for s in STORES],
        ["store_key", "store_name", "city", "state", "region", "store_type", "opened_date"],
    )
    write_csv("fact_sales.csv", fact_rows, list(fact_rows[0].keys()))

    total_net = sum(float(r["net_amount"]) for r in fact_rows)
    total_cost = sum(float(r["cost_amount"]) for r in fact_rows)
    print(f"dim_date.csv     rows={len(date_rows):>7}")
    print(f"dim_product.csv  rows={len(PRODUCTS):>7}")
    print(f"dim_store.csv    rows={len(STORES):>7}")
    print(f"fact_sales.csv   rows={len(fact_rows):>7}")
    print(f"total net revenue = {total_net:,.2f}")
    print(f"total gross margin = {total_net - total_cost:,.2f} ({(total_net - total_cost) / total_net:.2%})")


if __name__ == "__main__":
    main()
