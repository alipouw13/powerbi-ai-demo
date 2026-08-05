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

This text is also the reason the phase 7 data agent instruction box stays short. The DAX
generation tool reads this and ignores the agent box, so this is the only place a
definition actually changes a query.

```text
Revenue, sales and turnover all mean Total Net Sales, which is after discounts. Only use
Gross Sales when the user explicitly says gross, list price, or pre-discount.

"Best", "top" and "biggest" mean highest Total Net Sales unless the user names another
measure. "Most profitable" means highest Gross Margin in dollars. If the user says
"most profitable by margin rate", use Gross Margin %.

When comparing regions or store types, use Net Sales per Store rather than Total Net
Sales, because those groups contain different numbers of stores.

A store is a physical Contoso Coffee location. Region groups stores and has exactly
three values: West, Central, East. Store Type has exactly three values: Flagship,
Standard, Kiosk. If a user names a value that is not in these lists, say it does not
exist. Do not substitute the nearest match.

The fiscal year is the calendar year. Data covers 1 January 2024 to 31 December 2025.
If a user asks about a period outside that range, say the data does not cover it.

Channel has exactly three values: In Store, Mobile Order, Delivery. In Store means the
customer ordered at the counter.

Total Quantity counts individual items. Order Count counts orders. Neither is a customer
count, and this model has no customer table.

List Price and Cost per Unit on Product are list values, not transaction values. Never
average them to answer a question about actual selling price. Use Average Selling Price.

Year-over-year measures only mean something when a single year is in context. Net Sales
YoY %, Net Sales PY, Net Sales MoM % and Net Sales PM compare against a shifted period,
so if the question covers the whole 2024 to 2025 range they compare two years of sales
against one and return a nonsense number. When a user asks about growth without naming a
year, filter to 2025 and say that is what you did. 2024 has no prior year in this data,
so year-over-year growth for 2024 is not available.

This model has no forecast. If a user asks about a future period, say the model contains
historical data only.
```

### Why each line is there

| Instruction | The failure it prevents |
| --- | --- |
| Revenue means Total Net Sales | Copilot picking `Gross Sales`, which is higher, so every number is subtly wrong |
| Best and top definitions | Ties broken by the wrong measure, or by row count |
| Per store when comparing groups | West looking best purely because it has three stores and Central has two |
| Regions and store types are closed lists | An invented "Northwest region" answer |
| Date range stated | A confident answer about 2026, which has no data |
| No customer table | Units being reported as customers |
| List Price is not a selling price | Averaging a list value and calling it realised price |
| YoY needs a single year in context | `Net Sales YoY %` returning 104.9% instead of 4.9%, because two years of sales get compared against one. This one actually happened on the phase 5 report card. |
| No forecast | A hallucinated projection presented as data |

---

## 2. AI data schema

The goal is fewer, better fields. Include what a business user would name out loud, and
exclude everything else. Select the **same tables** here and in the data agent, or the
two surfaces will disagree.

**Include**

- All 21 measures from `measures.dax`
- `Date`: `Date`, `Year`, `Quarter`, `Month Name`, `Year-Month`, `Day of Week`,
  `Is Weekend`
- `Product`: `Product Name`, `Category`, `Subcategory`
- `Store`: `Store Name`, `City`, `State`, `Region`, `Store Type`, `Opened Date`
- `Sales`: `Channel`

**Exclude**

- Every key column: `Date Key`, `Store Key`, `Product Key` on `Sales`, plus `Product Key`
  on `Product` and `Store Key` on `Store`. All are hidden in the model already.
- `Sales`: `Gross Amount`, `Discount Amount`, `Net Amount`, `Cost Amount`, `Quantity`,
  `Sales Order ID`. The measures cover these, and leaving the raw columns visible invites
  Copilot to sum a column when it should use a measure.
- `Date`: `Month Number`, `Day of Week Number`. These exist for sorting only and are
  hidden.
- `Product`: `List Price`, `Cost per Unit`. These are list values, not transaction
  values, and averaging them is misleading.

Note the model tables are `Date`, `Sales`, `Product` and `Store`. The lakehouse tables
underneath are still `dim_date`, `fact_sales`, `dim_product` and `dim_store`. That is
deliberate: rename in the model where users and AI see it, leave the source alone.

---

## 3. Verified answers

A verified answer pins a specific visual to a set of trigger phrases. Set them from a
report visual: select the visual, `...`, `Set verified answer` in Desktop or
`Set up a verified answer` in the service.

Keep the list short. Every verified answer is a promise you have to maintain.

Pin visuals that already exist in the report, so the pinned visual and the report stay in
step. These three are on the executive and store pages:

| Visual to pin | Trigger questions |
| --- | --- |
| `Total Net Sales by Region`, bar chart, store page | `What is net sales by region?`, `Show me sales broken down by region`, `How is revenue distributed across regions?`, `Which region sells the most?`, `Net sales by region` |
| `Total Net Sales by Year-Month`, line chart, executive page | `What is the monthly sales trend?`, `Show me revenue by month`, `How have net sales changed over time?`, `Monthly revenue trend`, `Sales over time` |
| `Net Sales by Category`, bar chart, executive page | `What is net sales by category?`, `Which product category sells the most?`, `Show me revenue split by category`, `Sales by product category`, `Category breakdown of sales` |

Configuration tips, from the
[best practice guidance](https://learn.microsoft.com/fabric/data-science/semantic-model-best-practices):

- Use five to seven trigger questions per verified answer, covering formal and
  conversational phrasings. Use complete questions, not partial phrases, because matching
  is semantic.
- Up to three filters per verified answer gives you flexible slicing without needing
  several near-duplicate answers.
- **A verified answer cannot reference a hidden column.** Key columns and the raw amount
  columns are hidden in this model, so pin visuals built on measures.
- **If you rename a table, column or measure, reopen every verified answer that touches
  it and save it again**, or it silently stops matching. This bit us during the column
  rename pass.

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
