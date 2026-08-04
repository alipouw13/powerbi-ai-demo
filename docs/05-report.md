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
Create a page showing net revenue and gross margin percent by region and by month, with
a card for total net revenue and a bar chart of the top 5 products by net revenue.
```

This should work well, because phase 3 gave every measure a description and phase 4 told
Copilot what revenue means.

**3. The vague one.**

```text
Create a page analysing channel mix over time.
```

Deliberately underspecified. Watch what it chooses. This is the prompt that justifies the
AI instructions from phase 4, and it is the one to run twice: once before phase 4 if you
can, once after.

**4. A narrative.**

```text
Add a narrative visual that summarises revenue performance for 2025 compared to 2024.
```

Read the output aloud. If it says something untrue, that is a phase 3 or 4 problem
surfacing, not a phase 5 problem.

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
