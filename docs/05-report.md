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

## Start the report: auto-create or blank

In the Power BI service, select the `ContosoCoffee` semantic model, then use the arrow
beside `Auto-create report`. You have two starting points:

- **Auto-create report** generates an initial report immediately. Use it when speed
  matters more than seeing or shaping the outline first.
- **Create a blank report** opens an empty canvas. This is the better demo path because
  you can ask Copilot to inspect the model, propose several pages, and choose which ones
  it should build.

![The Power BI report creation dialog with the Auto-create report and Create a blank report options](images/05-create-report-options.png)

Choose `Create a blank report`, open the Copilot pane, and select
`Suggest content for a new report page` or use the first prompt below. Copilot evaluates
the semantic model and returns an outline. Expand each proposed page to review its
purpose, then select `Create` to generate it or `Edit` to refine the page prompt first.

![A blank Power BI report with Copilot suggesting four report pages and offering Create and Edit actions](images/05-copilot-suggest-report-pages.png)

Build the pages you want from the outline. Copilot creates the visuals and adds each page
as a report tab; the result is still a first draft that you must validate and edit.

![A Copilot-created Power BI report with four report tabs and a completed channel performance page](images/05-copilot-created-report-pages.png)

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
4. **Set verified answers** on the best two or three visuals using the procedure at the
   end of this phase. Those visuals are now curated answers.
5. **Publish** to the workspace.
6. **Restyle it**, once the numbers are right, using the screenshot workflow below.

---

## Make it look like something, from a screenshot

Copilot in Power BI gave you a correct page that looks generic. Default visuals, stacked
in a column, stock theme. The Copilot pane cannot help you here, because it cannot read
an image.

GitHub Copilot Chat can read an image, and the Fabric MCP server can rewrite the report
definition. Together they can take a screenshot of the design someone actually wants and
apply it to the report you just built.

The repository skill
[`.github/skills/report-restyle-from-screenshot`](../.github/skills/report-restyle-from-screenshot/SKILL.md)
carries the procedure. The `report-builder` agent uses it automatically, or invoke it
with `/report-restyle-from-screenshot`.

**What you need first**

- The report published to the workspace. If it only exists in Desktop there is no item
  definition to fetch.
- A Fabric MCP server connected in VS Code, from [phase 1](01-provision.md).
- The numbers on the page already checked. Restyling first only makes a wrong page
  attractive.

**How it goes**

In GitHub Copilot Chat, with the `report-builder` agent selected, attach the screenshot
and say:

```text
Here is the layout I want. Restyle my Contoso Coffee report to match it.

Read the screenshot into a design spec first and show me the spec before you change
anything. Then fetch the report definition from the workspace with the Fabric MCP
server, apply the layout, the palette, and the theme onto a new page called "Executive
overview", and leave the original Copilot page alone.

Do not change any field bindings or measures. Layout, visual types, and formatting only.
```

What happens under the hood:

1. Copilot reads the image and writes a design spec: canvas size, palette hex values,
   the KPI card row, chart positions, gutters. It shows you that spec first, because
   this is the step that goes wrong silently.
2. It calls `get_item_definition` and gets the report back as PBIR JSON: `page.json` per
   page, a `visual.json` per visual, `report.json` for the theme.
3. It rewrites the position blocks, the visual types where the screenshot clearly shows
   a different chart, the formatting, and it registers a custom theme built from your
   palette.
4. It calls `update_item_definition` with every required part, not only the changed
   ones, because that call replaces the definition rather than patching it.
5. It fetches the definition again, screenshots the result, and puts it next to your
   image so you can see what still does not match.

**The line that must not be crossed**

Layout, visual type, formatting, theme: fair game. Field bindings, measures, and the
semantic model binding: never. So re-run `python validation/ground_truth.py` afterwards.
A restyle that moves a number is a bug, not a design choice.

**Why demo it this way**

Keep the generic Copilot page and the restyled page side by side in the same report.
That contrast is the point: Copilot removes the blank page, and a screenshot plus MCP
turns the draft into something you would put in front of an executive, without anybody
dragging visuals around a canvas for an hour.

---

## The honest framing

Copilot is very good at the first 70 percent of a report and it does not know which 30
percent it got wrong. That is not a criticism, it is how to use it. It removes the blank
page and the fiddly layout work, and it hands you back something to review.

The demo lands better if you say that than if you pretend the output is finished.

---

## Set verified answers

Now that the report and its visuals exist, select a visual, `...`, then
`Set verified answer` in Desktop or `Set up a verified answer` in the service. Add
trigger phrases.

In the service you also need to be in a Copilot enabled workspace, have authoring
permission on the semantic model, be on a report page, and be in edit mode.

Set three:

| Visual | Trigger phrases |
| --- | --- |
| Net revenue by region, bar chart | net revenue by region, revenue by region, sales by region |
| Net revenue by month, line chart | revenue trend, revenue by month, monthly revenue |
| Top 5 products by net revenue | top products, best selling products, best products |

Keep the list short. Every verified answer is a promise you have to maintain when the
model changes.

---

Docs:
- https://learn.microsoft.com/power-bi/create-reports/copilot-introduction
- https://learn.microsoft.com/power-bi/create-reports/copilot-reports-overview
- https://learn.microsoft.com/power-bi/create-reports/copilot-enable-power-bi
- https://learn.microsoft.com/rest/api/fabric/articles/item-management/definitions/report-definition
- https://learn.microsoft.com/power-bi/developer/projects/projects-report

Next: [phase 6, insights](06-insights.md)
