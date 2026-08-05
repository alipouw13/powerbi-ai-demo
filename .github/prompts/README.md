# Copy-paste prompts

One block per phase from phase 1 onward. Phase 0 is setup and needs no prompt. Paste them
into the tool named in the heading. Nothing here needs
editing except the workspace name.

Prompts to GitHub Copilot Chat run in VS Code with the Fabric MCP servers connected.
Prompts to Power BI Copilot run in the Copilot pane in Power BI Desktop or the service.

---

## Phase 1, provision (GitHub Copilot Chat, Fabric Core MCP)

```text
List all my Fabric workspaces.
```

```text
Create a Fabric workspace called "Contoso Coffee AI Demo" and assign it to a capacity
that supports Copilot. Then create a lakehouse called "LH_ContosoCoffee" inside it.
When you are done, list the items in the workspace so I can verify.
```

```text
Which of my capacities support Copilot in Power BI? Copilot needs a paid F2 or higher,
or P1 or higher. Trial capacities do not qualify.
```

---

## Phase 2, load (GitHub Copilot Chat)

```text
Write a PySpark notebook cell that reads these four CSVs from Files/raw in the attached
lakehouse and writes each one as a managed delta table with the same name:
dim_date.csv, dim_product.csv, dim_store.csv, fact_sales.csv.

Requirements:
- Infer the header, but set explicit types: date_key as date, all *_amount columns as
  decimal, all *_key columns as integer, quantity as integer.
- Overwrite if the table exists.
- After writing, print the row count for each table.
```

```text
The expected row counts are dim_date 731, dim_product 12, dim_store 8,
fact_sales 64335. Mine do not match. Help me find where rows were dropped.
```

---

## Phase 3, model (Power BI MCP server, local — preferred)

Connect first, with the model open in Power BI Desktop:

```text
Connect to "ContosoCoffee" in Power BI Desktop
```

```text
Create these relationships, all many-to-one and single direction:
fact_sales[date_key] to dim_date[date_key], fact_sales[product_key] to
dim_product[product_key], fact_sales[store_key] to dim_store[store_key].
Then mark dim_date as the date table on dim_date[date_key].
```

```text
Set summarisation to Don't summarize on year, month_number, day_of_week_number and every
column ending in _key. Set the data category of dim_store[city] to City and
dim_store[state] to State or Province. Hide every *_key column and the raw amount
columns from report view.
```

```text
Read semantic-model/measures.dax and add every measure to the model, including its
description. Then run each measure as a DAX query and show me the result so I can check
it against validation/ground_truth.py.
```

```text
Audit this model against semantic-model/ai-readiness-checklist.md and fix only the
Critical findings. List every change you made before you make it.
```

Guardrails: it writes to the live model. Point it at a demo model, use `--readonly` if
you only want to show the read side, and re-run `python validation/ground_truth.py`
afterwards.

---

## Phase 3, model (Copilot in Fabric)

DAX query view, Copilot prompt box — take the `Suggest measures` starter, or type it:

```text
Suggest measures
```

Model view, Copilot pane:

```text
Help me add or replace descriptions for each measure. Consider the following rules:

- insert or replace the description that should appear above the measure code and after ///
- use business friendly terms
- describe the DAX code in the description in business-friendly terms; do not copy the
  code into the description
- use the measure name and the other measures as context
- the description should not be longer than 500 characters
```

---

## Phase 3, model (GitHub Copilot Chat)

With the Power BI modeling MCP server connected to the model:

```text
review current measures and suggest additional measures. do not duplicate and do not add
useless measures. if all measures are there then tell me such.
```

```text
Review my semantic model for AI readiness. Check for: business friendly table and
column names, all relationships defined, correct data types, data categories on City
and State, summarisation set to Don't summarize on Year, Month Number,
Day of Week Number and every key column, descriptions on every measure, and key columns
hidden from Q&A. List what is missing as a checklist.
```

Power BI, DAX query view with Copilot:

```text
Write a DAX query that returns net revenue and gross margin percent by region for 2025,
sorted by net revenue descending.
```

```text
Explain this query.
```

---

## Phase 3b, readiness audit (GitHub Copilot Chat, agent `model-readiness-auditor`)

```text
Audit the ContosoCoffee semantic model against semantic-model/ai-readiness-checklist.md.
For every item I cannot tick, give me a row with severity (Critical, Important,
Recommended), the object, the question in validation/question-bank.md it will break, and
the fix. Rank by severity. Do not fix anything yet.
```

```text
Which of my measure descriptions put the business meaning after the first 200 characters?
Rewrite those so the meaning comes first and the caveats come last.
```

Optional automated run, community project rather than a Microsoft product:
[Semantic Model AI Readiness Analyzer](https://github.com/SoomroFarhanH/SemanticModelBPforAI/tree/main/SemanticModel-AI-Readiness-Analyzer).
Import it into a Fabric workspace notebook, with Build permission on the published
model.

---

## Phase 4, prep for AI (Power BI, Prep data for AI, preview)

Paste into the **AI instructions** box. Full text is in
[`semantic-model/ai-instructions.md`](../../semantic-model/ai-instructions.md).

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

---

## Phase 5, report (Power BI Copilot pane, author)

```text
Suggest content for this report.
```

```text
Create a page showing net revenue and gross margin percent by region and by month, with
a card for total net revenue and a bar chart of the top 5 products by net revenue.
```

```text
Create a page analysing channel mix over time.
```

```text
Add a narrative visual that summarises revenue performance for 2025 compared to 2024.
```

After the visuals exist, set verified answers, one per visual:

```text
Pin: Total Net Sales by Region (bar, store page)
Trigger questions: What is net sales by region? / Show me sales broken down by region /
How is revenue distributed across regions? / Which region sells the most? /
Net sales by region
```

```text
Pin: Total Net Sales by Year-Month (line, executive page)
Trigger questions: What is the monthly sales trend? / Show me revenue by month /
How have net sales changed over time? / Monthly revenue trend / Sales over time
```

---

## Phase 5, restyle from a screenshot (GitHub Copilot Chat, agent `report-builder`, skill `report-restyle-from-screenshot`)

Publish the report first, connect the Fabric MCP server, and attach the screenshot of the
layout you want to the chat turn.

```text
Here is the layout I want. Restyle my Contoso Coffee report to match it.

Read the screenshot into a design spec first and show me the spec before you change
anything. Then fetch the report definition from the workspace with the Fabric MCP
server, apply the layout, the palette, and the theme onto a new page called "Executive
overview", and leave the original Copilot page alone.

Do not change any field bindings or measures. Layout, visual types, and formatting only.
```

```text
The KPI cards are still too tall and the palette is warmer in my screenshot than in the
page you produced. Adjust those two things only, then show me the before and after side
by side.
```

```text
Confirm you did not change any queryState, then run python validation/ground_truth.py
and tell me whether any visible total moved.
```

---

## Phase 6, insights (Copilot pane and standalone Copilot, consumer)

Ask the 15 questions in [`validation/question-bank.md`](../../validation/question-bank.md)
exactly as written. Then these three, which are designed to fail interestingly:

```text
What will revenue be next quarter?
```

```text
Which store is most profitable?
```

```text
Show me sales for the Northwest region.
```

---

## Phase 7, data agent (Fabric portal)

The agent has **one** data source, the `ContosoCoffee` semantic model. The curated
measures are the authoritative definitions, so there is no reason to also expose the
lakehouse and every reason not to: a second source only gives the orchestrator a way to
answer the same question from ungoverned raw columns.

When the OneLake catalog opens, add the `ContosoCoffee` semantic model and stop. **Do not
add `LH_ContosoCoffee`.** Then tick `Date`, `Sales`, `Product` and `Store` in the Explorer
pane, matching the tables you selected in the phase 4 AI data schema.

> **The single most important thing on this page.** Data agent instructions are **not**
> passed to the DAX generation step. For a semantic model source, what actually shapes
> the query is the Prep data for AI configuration from phase 4. Anything you write here
> about which measure means what is ignored. Keep business definitions in Prep for AI and
> keep this box for what it really controls: scope, tone, formatting, and refusals.

Paste into **Data agent instructions**. The structure follows the recommended format in
[the configuration guidance](https://learn.microsoft.com/fabric/data-science/data-agent-configurations#data-agent-instructions).

```md
## Objective

Help business users understand Contoso Coffee retail sales performance: revenue, margin,
units, orders, and how those split by time, product, store, region and channel.

Answer only from the curated measures in the semantic model. Never estimate, extrapolate,
or forecast. If the data cannot answer the question, say so plainly and stop.

## Data sources

One source: the `ContosoCoffee` Power BI semantic model. It is authoritative for every
question in scope. There is no second source to fall back to, so do not invent one and do
not answer from general knowledge about coffee retail.

## Key terminology

Expand these abbreviations when a user types them:

- AOV is Average Order Value. ASP is Average Selling Price.
- GM is Gross Margin. GM% is Gross Margin %.
- YoY is year over year. MoM is month over month. YTD is year to date. QTD is quarter to
  date. PY is prior year. PM is prior month.
- Basket size means units per order.

## Response guidelines

- Lead with the direct answer in one sentence, then the supporting numbers.
- Always state the time period covered and any filter you applied. An unqualified number
  is worse than no number.
- Currency with a dollar sign and thousands separators. Percentages to one decimal place.
- Return at most 10 rows unless the user asks for more. Responses are capped at 25 rows
  and 25 columns regardless.
- Do not show the DAX unless the user asks to see it.
- If a query returns blank, say the query returned no rows. Do not report it as zero.
  Blank and zero mean different things here.

## Handling common topics

- Comparing regions or store types: use net sales per store, not total net sales, because
  those groups contain different numbers of stores. Say that you did this and why.
- Ranking, "best", "top", "biggest": rank by net sales unless the user names another
  measure.
- Profitability: use gross margin in dollars. Use the percentage only if the user says
  rate, percent, or margin rate.
- Growth, "year over year", "versus last year": always state which year you compared. If
  the user did not name one, use 2025 versus 2024 and say so. Never report a growth rate
  for an unfiltered whole-model total.
- Future periods or forecasts: the model holds history only, 1 January 2024 to
  31 December 2025. Say the data does not cover it. Never project a trend forward.
- A name that does not exist, for example a "Northwest" region: say it does not exist and
  list the valid values. Never substitute the nearest match.
- Customers: this model has no customer table. Units and orders are not customer counts,
  so do not present them as such.
```

**Example queries: skip this.** Example query pairs are not supported for Power BI
semantic model sources, and neither are data source instructions or data source
descriptions. Verified answers in Prep for AI are the equivalent, which is another reason
phase 4 comes before phase 7.

Then write a real **publish description**. It becomes the MCP tool description and the
Microsoft 365 Copilot description, so it is how other systems decide whether to call your
agent:

```text
Answers questions about Contoso Coffee retail sales performance from the governed
ContosoCoffee semantic model: net sales, gross margin, discounts, orders, units, and
average order value, sliced by date, product category, store, region and channel.
Covers 1 January 2024 to 31 December 2025 for 8 US stores. Historical reporting only,
no forecasting.
```

---

## Phase 8, validate (any agent, or GitHub Copilot Chat)

```text
Run python validation/ground_truth.py. Then compare it to the answers I recorded in
validation/scorecard.md. For every answer that is not correct, tell me the likely cause
in the semantic model or in Prep data for AI, and which agent owns the fix. Do not
suggest rewording the question.
```
