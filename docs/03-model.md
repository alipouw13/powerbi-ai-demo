# Phase 3. Build the semantic model

**Agent:** `semantic-model-author`
**Time:** 25 minutes
**AI on show:** GitHub Copilot for measures and descriptions, DAX query view with
Copilot, Power BI Modeling MCP server (public preview)

This is the phase that decides whether phases 5, 6 and 7 succeed. Copilot cannot be
better than the metadata you give it. Everything after this is downstream of the work
you do here.

---

## Create the model

From the `LH_ContosoCoffee` lakehouse ribbon, select `New semantic model`. Name it
`ContosoCoffee`. Select all four tables. This gives you a Direct Lake model.

Alternatively, connect Power BI Desktop to the lakehouse and build an Import model. The
demo works either way. Note that in phase 4, Power BI Desktop supports Prep data for AI
only on Import, DirectQuery, and Composite (local) models, while the Power BI service
supports all model types including Direct Lake.

---

## Relationships

| From | To | Cardinality | Direction |
| --- | --- | --- | --- |
| `fact_sales[date_key]` | `dim_date[date_key]` | many to one | single |
| `fact_sales[product_key]` | `dim_product[product_key]` | many to one | single |
| `fact_sales[store_key]` | `dim_store[store_key]` | many to one | single |

Then mark `dim_date` as the date table, on `dim_date[date_key]`.

Missing relationships are the single most common reason an AI answer comes back wrong.
Copilot cannot join what you did not join.

---

## Measures

There are 18, in [`semantic-model/measures.dax`](../semantic-model/measures.dax). Add
them all. Every one has a description in the file, and the description matters: **Copilot
reads measure descriptions, and uses only the first 200 characters.**

### The GitHub Copilot version

Open the repo in VS Code and ask:

```text
Read semantic-model/measures.dax. For each measure, write a one sentence description
under 200 characters that says what it measures and when someone should use it. Return
a markdown table of measure name and description so I can paste them into Power BI.
```

Power BI Desktop can also generate descriptions itself: Model view, select a measure,
`Create with Copilot` in the Description box.

### The DAX Copilot round trip

In Power BI Desktop, enable `DAX query view with Copilot` under
`File`, `Options and settings`, `Options`, `Preview features`. Then in DAX query view:

```text
Write a DAX query that returns net revenue and gross margin percent by region for 2025,
sorted by net revenue descending.
```

Run it. Then select the query and ask `Explain this query`. Generate, run, explain. That
loop is the demo, not the single generation.

DAX Copilot checks syntax and retries once automatically if the query fails.

---

## The twelve things that decide AI quality

Work through this list. It is short, it is boring, and it is the entire difference
between a demo that works and one that does not.

1. **Business friendly names.** Rename anything a person would not say out loud.
   `net_amount` is a column. `Net Revenue` is what someone asks for.
2. **All three relationships defined.**
3. **Correct data types.** Dates as dates, money as decimal, never text.
4. **Data categories.** `dim_store[city]` as City, `dim_store[state]` as State or
   Province. This is how Copilot decides to draw a map.
5. **Summarisation set to `Don't summarize`** on `year`, `month_number`,
   `day_of_week_number`, and every `*_key` column. Otherwise Copilot will sum years and
   report a total year of 4,050.
6. **Synonyms** for business vocabulary: revenue, sales, turnover, takings.
7. **Hide** the key columns and the raw amount columns from the report and from Q&A.
   Leave the measures visible. Fewer, better fields beat more fields.
8. **Descriptions on every measure**, short and literal.
9. **Keep the star schema.** Do not flatten it.
10. **Enable Q&A** on the semantic model. Copilot data questions run through it.
11. **Plan for AI instructions and the AI data schema.** That is phase 4, but design for
    it here.
12. **Mark the model Approved for Copilot** once phase 4 is done, not before.

Very large models degrade Copilot quality, because there is a limit on how much metadata
can be sent. One documented number worth knowing: only the **first 200 characters** of a
description are used, so put the important words first. This model is nowhere near any
limit, but someone will ask.

---

## Power BI Modeling MCP server, optional

Public preview: https://github.com/microsoft/powerbi-modeling-mcp

Install the `analysis-services.powerbi-modeling-mcp` VS Code extension, then connect
from Copilot Chat:

```text
Connect to "ContosoCoffee" in Power BI Desktop
```

It exposes `measure_operations`, `column_operations`, `relationship_operations`,
`dax_query_operations`, `table_operations` and more, against the live model. Microsoft
Learn recommends it specifically for generating business friendly names before you build
a data agent. It needs Write permission, and it has a `--readonly` flag if you want to
demo it safely.

---

## Verify before you leave this phase

```bash
python validation/ground_truth.py
```

Build a table visual and check at least these three:

| Measure | Expected |
| --- | --- |
| `Net Revenue` | $412,918.50 |
| `Gross Margin %` | 68.65% |
| `Units Sold` | 94,417 |

If a measure disagrees, fix the measure. Never adjust the test.

---

## Then run pass A

Before you do any AI preparation, open the Copilot pane and ask all 15 questions in
[`validation/question-bank.md`](../validation/question-bank.md). Record the score as
pass A in [`validation/scorecard.md`](../validation/scorecard.md).

Do not skip this. Pass A is the control. Without it, phase 4 is an assertion instead of
a result.

---

Docs:
- https://learn.microsoft.com/power-bi/create-reports/copilot-evaluate-data
- https://learn.microsoft.com/power-bi/natural-language/q-and-a-best-practices
- https://learn.microsoft.com/dax/dax-copilot
- https://learn.microsoft.com/power-bi/transform-model/desktop-measure-copilot-descriptions
- https://learn.microsoft.com/fabric/data-science/semantic-model-best-practices

Next: [phase 4, prep for AI](04-prep-for-ai.md)
