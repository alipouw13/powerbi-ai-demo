"""Compute ground truth answers for the accuracy loop.

Reads the CSVs in data/ and prints the correct answer for every question in
validation/question-bank.md. Use this to score what Copilot, the data agent, or
the ontology agent tells you. Standard library only.

Usage:
    python validation/ground_truth.py
    python validation/ground_truth.py --json
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load(name: str) -> list[dict[str, str]]:
    with (DATA_DIR / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def money(value: float) -> str:
    return f"${value:,.2f}"


def compute_raw() -> dict[str, object]:
    """Return the ground truth as raw numbers, not display strings.

    Machine consumers should use this. Percentages are fractions, so a gross
    margin of 68.65 percent is returned as 0.6865...
    """
    facts = load("fact_sales.csv")
    products = {r["product_key"]: r for r in load("dim_product.csv")}
    stores = {r["store_key"]: r for r in load("dim_store.csv")}
    dates = {r["date_key"]: r for r in load("dim_date.csv")}

    total_net = 0.0
    total_cost = 0.0
    total_qty = 0
    by_year: dict[str, float] = defaultdict(float)
    by_region: dict[str, float] = defaultdict(float)
    by_store: dict[str, float] = defaultdict(float)
    by_category: dict[str, float] = defaultdict(float)
    by_product: dict[str, float] = defaultdict(float)
    by_channel: dict[str, float] = defaultdict(float)
    by_month_2025: dict[str, float] = defaultdict(float)
    weekend_net = 0.0
    weekday_net = 0.0

    for row in facts:
        net = float(row["net_amount"])
        cost = float(row["cost_amount"])
        qty = int(row["quantity"])
        date_row = dates[row["date_key"]]
        product = products[row["product_key"]]
        store = stores[row["store_key"]]

        total_net += net
        total_cost += cost
        total_qty += qty
        by_year[date_row["year"]] += net
        by_region[str(store["region"])] += net
        by_store[str(store["store_name"])] += net
        by_category[str(product["category"])] += net
        by_product[str(product["product_name"])] += net
        by_channel[row["channel"]] += net
        if date_row["year"] == "2025":
            by_month_2025[date_row["year_month"]] += net
        if date_row["is_weekend"] == "TRUE":
            weekend_net += net
        else:
            weekday_net += net

    margin = total_net - total_cost

    def ranked(mapping: dict[str, float]) -> dict[str, float]:
        return {k: v for k, v in sorted(mapping.items(), key=lambda kv: -kv[1])}

    return {
        "total_net": total_net,
        "total_margin": margin,
        "margin_pct": margin / total_net,
        "total_units": total_qty,
        "net_2024": by_year["2024"],
        "net_2025": by_year["2025"],
        "yoy_pct": (by_year["2025"] - by_year["2024"]) / by_year["2024"],
        "top_store": max(by_store.items(), key=lambda kv: kv[1]),
        "top_product": max(by_product.items(), key=lambda kv: kv[1]),
        "by_region": ranked(by_region),
        "by_category": ranked(by_category),
        "by_channel": ranked(by_channel),
        "best_month_2025": max(by_month_2025.items(), key=lambda kv: kv[1]),
        "weekend_net": weekend_net,
        "weekday_net": weekday_net,
        "avg_order_line": total_net / len(facts),
    }


def compute() -> dict[str, object]:
    raw = compute_raw()
    top_store = raw["top_store"]
    top_product = raw["top_product"]
    best_month = raw["best_month_2025"]

    return {
        "Q01 total net revenue (all time)": money(raw["total_net"]),
        "Q02 total gross margin amount": money(raw["total_margin"]),
        "Q03 gross margin percent": f"{raw['margin_pct']:.2%}",
        "Q04 total units sold": f"{raw['total_units']:,}",
        "Q05 net revenue 2024": money(raw["net_2024"]),
        "Q06 net revenue 2025": money(raw["net_2025"]),
        "Q07 year over year growth percent 2025 vs 2024": f"{raw['yoy_pct']:.2%}",
        "Q08 top store by net revenue": f"{top_store[0]} ({money(top_store[1])})",
        "Q09 top product by net revenue": f"{top_product[0]} ({money(top_product[1])})",
        "Q10 net revenue by region": {k: money(v) for k, v in raw["by_region"].items()},
        "Q11 net revenue by category": {k: money(v) for k, v in raw["by_category"].items()},
        "Q12 net revenue by channel": {k: money(v) for k, v in raw["by_channel"].items()},
        "Q13 best month in 2025 by net revenue": f"{best_month[0]} ({money(best_month[1])})",
        "Q14 weekend vs weekday net revenue": {
            "Weekend": money(raw["weekend_net"]),
            "Weekday": money(raw["weekday_net"]),
        },
        "Q15 average order line value": money(raw["avg_order_line"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args()

    answers = compute()
    if args.json:
        print(json.dumps(answers, indent=2))
        return

    print("Ground truth for the Contoso Coffee demo dataset")
    print("=" * 60)
    for question, answer in answers.items():
        if isinstance(answer, dict):
            print(f"{question}:")
            for key, value in answer.items():
                print(f"    {key:<14} {value}")
        else:
            print(f"{question}: {answer}")


if __name__ == "__main__":
    main()
