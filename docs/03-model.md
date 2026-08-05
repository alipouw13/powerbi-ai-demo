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

The tables arrive from the lakehouse named `fact_sales`, `dim_date`, `dim_product` and
`dim_store` with snake_case columns. Rename them in the model first (step 1 below), then
build the relationships. The names in this guide are the post-rename model names.

| From | To | Cardinality | Direction |
| --- | --- | --- | --- |
| `Sales[Date Key]` | `Date[Date]` | many to one | single |
| `Sales[Product Key]` | `Product[Product Key]` | many to one | single |
| `Sales[Store Key]` | `Store[Store Key]` | many to one | single |

Then mark `Date` as the date table, on `Date[Date]`.

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

It is the condensed version of Microsoft's own guidance in
[Optimize your semantic model for Copilot in Power BI](https://learn.microsoft.com/power-bi/create-reports/copilot-evaluate-data).
The full checklist, with everything that page covers, is
[`semantic-model/ai-readiness-checklist.md`](../semantic-model/ai-readiness-checklist.md),
and you run it as the gate in [phase 3b](03b-readiness-audit.md).

1. **Business friendly names.** Rename anything a person would not say out loud.
   `net_amount` is the lakehouse column. `Net Amount` is the model column, and
   `Total Net Sales` is what someone asks for. Rename in the model, leave the lakehouse
   alone.
2. **All three relationships defined.**
3. **Correct data types.** Dates as dates, money as decimal, never text.
4. **Data categories.** `Store[City]` as City, `Store[State]` as State or
   Province. This is how Copilot decides to draw a map.
5. **Summarisation set to `Don't summarize`** on `Year`, `Month Number`,
   `Day of Week Number`, and every key column. Otherwise Copilot will sum years and
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

### Three more that the Learn optimization page calls out

Not in the list above because this model does not need all of them, but real models do.

1. **Hierarchies.** Learn lists them explicitly as a model structure requirement. Build
   `Year > Quarter > Month > Day` on `Date`. It gives Copilot a drill path instead
   of a pile of date columns.
2. **Calculation group descriptions.** Model metadata does not include calculation items
   at all. If you have a calculation group with `YTD`, `MTD` and `PY`, the only way
   Copilot learns those exist is the calculation group column's description. And that is
   also cut at 200 characters, so list the items first, explain second.
3. **No duplicate visible column names across tables.** If two tables both expose
   `Date`, the query the AI generates can pick the wrong one and return a confidently
   wrong number with no error.

---

## Gate: audit before you score

Do not go straight from here to phase 4. Run [phase 3b](03b-readiness-audit.md) first.
It is fifteen minutes, it produces a written list of predicted failures, and pass A then
tells you which predictions were right. That is a far better demo moment than a failure
nobody saw coming.

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
| `Total Net Sales` | $412,918.50 |
| `Gross Margin %` | 68.7% |
| `Total Quantity` | 94,417 |
| `Order Count` | 64,335 |

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

Next: [phase 3b, audit the model](03b-readiness-audit.md), then
[phase 4, prep for AI](04-prep-for-ai.md)
