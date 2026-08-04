# AI instructions and AI data schema for the Contoso Coffee model

This is the source text for **phase 4, Prep data for AI**. Prep data for AI is in
preview.

All three features here save to the **semantic model**, not to the report. Author them
from the `Prep data for AI` button on the Home ribbon in Power BI Desktop, or on the
semantic model ribbon in the Power BI service.

Docs: https://learn.microsoft.com/power-bi/create-reports/copilot-prepare-data-ai

---

## 1. AI instructions

Paste this into the AI instructions box. It is deliberately about **business rules that
are not visible in the schema**. Restating column names here adds nothing.

```text
Revenue means Net Revenue, which is after discounts. Only use Gross Revenue when the
user explicitly says gross or pre-discount.

"Best", "top" and "biggest" mean highest Net Revenue unless the user names another
measure. "Most profitable" means highest Gross Margin in dollars. If the user says
"most profitable by margin rate" use Gross Margin %.

A store is a physical Contoso Coffee location. A region groups stores and has exactly
three values: West, Central, East. If a user names a region that is not one of these,
say that it does not exist. Do not substitute the nearest match.

The fiscal year is the calendar year. Data covers 1 January 2024 to 31 December 2025.
If a user asks about a period outside that range, say the data does not cover it.

Channel has exactly three values: In Store, Mobile Order, Delivery. In Store means the
customer ordered at the counter.

Units Sold counts individual items, not orders. Order Lines counts sales lines. Neither
is a customer count, and this model has no customer table.

Never sum year, month_number, day_of_week_number, or any column ending in _key.

This model has no forecast. If a user asks about a future period, say the model contains
historical data only.
```

### Why each line is there

| Instruction | The failure it prevents |
| --- | --- |
| Revenue means Net Revenue | Copilot picking `Gross Revenue`, which is 3 to 4 percent higher, so every number is subtly wrong |
| Best and top definitions | Ties broken by the wrong measure, or by row count |
| Regions are exactly three | An invented "Northwest region" answer |
| Date range stated | A confident answer about 2026, which has no data |
| No customer table | Units being reported as customers |
| Never sum year or keys | The classic "total year: 4,050" answer |
| No forecast | A hallucinated projection presented as data |

---

## 2. AI data schema

The goal is fewer, better fields. Include what a business user would name out loud, and
exclude everything else.

**Include**

- All 18 measures from `measures.dax`
- `dim_date`: `date_key`, `year`, `quarter`, `month_name`, `year_month`, `day_of_week`,
  `is_weekend`
- `dim_product`: `product_name`, `category`, `subcategory`
- `dim_store`: `store_name`, `city`, `state`, `region`, `store_type`
- `fact_sales`: `channel`

**Exclude**

- Every `*_key` column on `fact_sales`, and `product_key` and `store_key` on the
  dimensions
- `fact_sales`: `gross_amount`, `discount_amount`, `net_amount`, `cost_amount`,
  `quantity`, `sales_order_id`. The measures cover these, and leaving the raw columns
  visible invites Copilot to sum a column when it should use a measure.
- `dim_date`: `month_number`, `day_of_week_number`. These exist for sorting only.
- `dim_product`: `unit_price`, `unit_cost`. These are list values, not transaction
  values, and averaging them is misleading.

---

## 3. Verified answers

A verified answer pins a specific visual to a set of trigger phrases. Set them from a
report visual: select the visual, `...`, `Set verified answer` in Desktop or
`Set up a verified answer` in the service.

Keep the list short. Every verified answer is a promise you have to maintain.

| Visual to pin | Trigger phrases |
| --- | --- |
| Net revenue by region, bar chart | `net revenue by region`, `revenue by region`, `sales by region` |
| Net revenue by month, line chart | `revenue trend`, `revenue by month`, `monthly revenue` |
| Top 5 products by net revenue | `top products`, `best selling products`, `best products` |

In the Power BI service you also need to be in a Copilot enabled workspace, have
authoring permission on the semantic model, be on a report page, and be in edit mode
with the visual selected.

---

## 4. Approved for Copilot

Once the three features above are configured and tested, mark the model approved.

Power BI service, semantic model, `Settings`, expand `Approved for Copilot`, tick the
box, `Apply`.

- Removes the friction treatment banner in the standalone Copilot experience.
- Reports built on the model inherit the approval. There is no way to approve a report,
  dashboard, or app directly.
- Usually reflected within an hour, up to 24 hours on a model with many reports.

Do this last. The badge is a claim about the work, so do the work first.

---

## Testing checklist

- Q&A is enabled on the semantic model.
- Close and reopen the Copilot pane after every save, or changes will not appear.
- Use the skill picker in the Desktop Copilot pane to simulate each surface.
- Expand `How Copilot arrived at this` on every answer to see which fields were used.
- Re-run the full question bank in `validation/question-bank.md` and record the score.
