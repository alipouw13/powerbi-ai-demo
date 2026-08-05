# Phase 5. Build the report with Copilot

**Agent:** `report-builder`
**Time:** 15 minutes
**AI on show:** Copilot in Power BI, report authoring, generally available

Copilot writes the first draft. You are the editor.

---

## What Copilot can do for an author

Generally available, in Power BI Desktop and the Power BI service:

- Create a report page from a prompt
- Suggest content, which returns a proposed report outline you accept page by page
- Create a narrative or smart summary visual
- Summarise the semantic model, useful when you did not build it
- Write and explain DAX in DAX query view
- Generate measure descriptions in Model view

Prompts are capped at 10,000 characters.

If there is no Copilot button, go back to [phase 0](00-setup.md). It is almost always
capacity: trial capacities do not qualify.

---

## Three prompts, in this order

The value is in the contrast between them.

**1. Let it read the model.**

```text
Suggest content for this report.
```

Copilot proposes an outline based on your model. Accept one page. This shows it reading
your measures and dimensions, not guessing from the table names.

**2. The specific one.**

```text
Create a page showing total net sales and gross margin percent by region and by month,
with a card for total net sales and a bar chart of the top 5 products by net sales.
```

This should work well, because phase 3 gave every measure a description and phase 4 told
Copilot that sales and revenue both mean `Total Net Sales`.

**3. The vague one.**

```text
Create a page analysing channel mix over time.
```

Deliberately underspecified. Watch what it chooses. This is the prompt that justifies the
AI instructions from phase 4, and it is the one to run twice: once before phase 4 if you
can, once after.

**4. A narrative.**

```text
Add a narrative visual that summarises net sales performance for 2025 compared to 2024.
```

Read the output aloud. If it says something untrue, that is a phase 3 or 4 problem
surfacing, not a phase 5 problem.

---

## What it looks like when it is finished

This is the `Executive Sales & Margin Overview` page after the review pass below. Copilot
drafted the visuals, then the layout, theme and titles were tightened by hand.

![Executive Sales & Margin Overview: a Power BI report page with a blue header band containing Region and Year slicers, a row of five KPI cards reading $412.92K total net sales, $283.48K gross margin, 68.7% gross margin percent, 64K orders and 4.9% net sales year over year, two line charts by year-month, and two bar charts by category and channel](images/executive-sales-margin-overview.png)

Worth pointing at during a demo:

| On the page | Why it is there |
| --- | --- |
| Cards read `Total Net Sales`, `Gross Margin`, `Gross Margin %`, `Order Count`, `Net Sales YoY %` | Measure names, straight from the model. Nothing is renamed in the report, so what the audience reads is what Copilot and the data agent read. |
| `$412.92K` and `68.7%` | The same numbers `python validation/ground_truth.py` returns. Check them live if you want the room to trust the rest. |
| The YoY card is titled `NET SALES YOY % (2025 VS 2024)`, not just `NET SALES YOY %` | The title names the comparison because the card is filtered to one year. It has to be. See below. |
| Gross Margin % is its own chart, not a second series on the sales chart | A rate and an amount on one axis is the most common way a generated page misleads. |
| Category and Channel as separate bar charts | These are the two splits the audience always asks for next, so answering them before the question is asked keeps the demo moving. |
| Region and Year slicers in the header band | Every number on the page is qualified by a visible filter state. |

Two of the visuals on this page, `Total Net Sales by Year-Month` and `Net Sales by
Category`, are pinned as verified answers in [phase 4](04-prep-for-ai.md), along with
`Total Net Sales by Region` on the store page. That is why they are worth building
properly: a verified answer returns the visual itself rather than a freshly generated
query, so whatever you pin is what the audience sees.

### The bug this page used to have, and why it is worth demoing

That last card is the most useful thing on the page, because it was wrong.

When Copilot first generated it, it read **104.9%**. Net sales did not grow 105 percent.

`Net Sales YoY %` is `DIVIDE([Total Net Sales] - [Net Sales PY], [Net Sales PY])`, and the
DAX is correct. The card was wrong because it had no year filter. With the whole model in
context, `Total Net Sales` covers 2024 and 2025 while `SAMEPERIODLASTYEAR` can only reach
back to 2024, so the card compared two years of sales against one. Filtered to 2025 the
same measure returns **4.9%**, which is what it shows above.

The fix was a visual-level filter pinning the card to 2025, plus the retitle so the
comparison is stated rather than assumed.

Two things worth saying out loud when you show this:

1. Copilot generated a card that was **plausible, well formatted, and wrong**. Nothing in
   the visual flagged it. Only checking the number against the data caught it.
2. Time intelligence at a grand total is the most common version of this failure. Any
   measure built on `SAMEPERIODLASTYEAR`, `DATEADD` or `TOTALYTD` needs a single period in
   context to mean anything, and a card with no filter does not have one.

If you want to reproduce it live, drop `Net Sales YoY %` on a blank card with no filter and
watch it read 104.9%.

This is also why phase 4 matters. The AI instructions tell Copilot and the data agent that
`Net Sales YoY %` needs a single year in context, so the same trap does not get reproduced
in a chat answer where there is no visual to inspect.

---

## What you do next, every time

Copilot produced a draft. Before anyone sees it:

1. **Check every number** against `python validation/ground_truth.py`. A page that looks
   right and totals wrong is worse than no page at all.
2. **Fix the titles.** Copilot's titles are literal and usually too long.
3. **Check aggregations** on any numeric field that should not be summed.
4. **Set verified answers** on the best two or three visuals, then go back to
   [phase 4](04-prep-for-ai.md). Those visuals are now curated answers.
5. **Publish** to the workspace.

---

## The honest framing

Copilot is very good at the first 70 percent of a report and it does not know which 30
percent it got wrong. That is not a criticism, it is how to use it. It removes the blank
page and the fiddly layout work, and it hands you back something to review.

The demo lands better if you say that than if you pretend the output is finished.

---

Docs:
- https://learn.microsoft.com/power-bi/create-reports/copilot-introduction
- https://learn.microsoft.com/power-bi/create-reports/copilot-reports-overview
- https://learn.microsoft.com/power-bi/create-reports/copilot-enable-power-bi

Next: [phase 6, insights](06-insights.md)
