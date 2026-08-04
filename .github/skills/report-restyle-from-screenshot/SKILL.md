---
name: report-restyle-from-screenshot
description: Restyles an existing Power BI report page to match a design screenshot the user uploads, by reading the image in GitHub Copilot Chat and rewriting the report PBIR definition through the Fabric MCP server. Use when someone says "make this page look like this screenshot", "the Copilot page is ugly", "apply this design to my report", "match this dashboard mockup", or "restyle the report".
---

# Restyle a report page from an uploaded screenshot

Power BI Copilot writes a correct but generic page. It picks default visuals, stacks
them in a column, and keeps the stock theme. This skill takes a screenshot of the layout
someone actually wants, turns it into a design spec, and applies that spec to the real
report by editing the report definition through the Fabric MCP server.

Copilot in Power BI cannot read an uploaded image. GitHub Copilot Chat can. That is why
this half of the work happens in VS Code and not in the Copilot pane.

Repository sources of truth: [`docs/05-report.md`](../../../docs/05-report.md),
[`validation/ground_truth.py`](../../../validation/ground_truth.py),
[`semantic-model/measures.dax`](../../../semantic-model/measures.dax).

Resources in this skill:
- [`reference/pbir-restyle-cheatsheet.md`](reference/pbir-restyle-cheatsheet.md), the
  PBIR fields you are allowed to touch, the layout grid maths, and the visual type names.
- [`templates/contoso-theme.json`](templates/contoso-theme.json), a starting theme file
  to fill in with the palette you read off the screenshot.

## Preconditions

Stop and say which one is missing rather than improvising:

1. The report exists in a Fabric workspace. If it is only open in Power BI Desktop and
   was never published, there is no item definition to fetch.
2. A Fabric MCP server is connected in VS Code and signed in. You need
   `list_items`, `get_item`, `get_item_definition`, `update_item_definition` and
   `get_knowledge`.
3. The user has attached the screenshot to the chat turn. Never work from a description
   of an image you were not given.
4. The page being restyled already has correct numbers. Restyling a wrong page only
   makes the wrong number prettier. If it has not been checked, send the user back to
   `report-builder` step 1 first.

## Procedure

### 1. Read the screenshot into a design spec

Describe only what is visible. Write the spec back to the user as a short table before
you touch anything, because this is the step that goes wrong silently.

Capture:

| Item | What to record |
| --- | --- |
| Canvas | Aspect ratio, and the target size in pixels, usually 1280 x 720 or 1600 x 900 |
| Background | Page fill colour, and any header or sidebar band with its height or width |
| Palette | Every distinct colour as a hex value, ordered most used first |
| Typography | Title size, card value size, and whether labels are sentence case or upper case |
| KPI row | How many cards, where they sit, and what each one appears to show |
| Charts | Position, size, chart type, and orientation for each one |
| Spacing | Outer margin and the gutter between tiles, in pixels at the target canvas size |
| Chrome | Slicers, legends, gridlines, borders, shadows, rounded corners, logo |

Two rules for this step. Record what the screenshot shows, not what you would design.
And if the screenshot shows a field that does not exist in the Contoso Coffee model,
flag it as unmappable rather than inventing a measure for it.

### 2. Confirm the spec and the target

Ask the user to confirm the design spec, the workspace, the report, and which page or
pages to restyle. Get an explicit answer on whether you are replacing an existing page or
adding a new one. Default to adding a new page, so the original Copilot output survives
for the before and after comparison, which is the point of the demo.

### 3. Fetch the current definition

Call `get_knowledge` with topic `Report` first, so you are working from the current PBIR
schema and not from memory. Then `list_items` filtered to `Report`, then
`get_item_definition` on the report.

You get a PBIR folder. The parts that matter:

```text
definition/report.json                               theme collection, resource packages, settings
definition/pages/pages.json                          page order and active page
definition/pages/<pageId>/page.json                  display name, width, height, display option
definition/pages/<pageId>/visuals/<id>/visual.json   position block and visual definition
StaticResources/RegisteredResources/*.json           custom theme files
definition.pbir                                      semantic model binding, do not edit
```

Decode the base64 payloads and keep the originals. You need them for the parts you do
not change.

### 4. Map the spec onto PBIR

Change these:

- `page.json`: `width`, `height`, `displayName`, `displayOption`.
- `visual.json` `position`: `x`, `y`, `width`, `height`, `z`, `tabOrder`.
- `visual.json` `visual.visualType`, only where the screenshot clearly shows a different
  chart type, for example `clusteredColumnChart` instead of `barChart`.
- `visual.json` `visual.objects`: titles, data labels, background, border, shadow.
- A custom theme JSON in `StaticResources/RegisteredResources/`, wired into
  `report.json` through `themeCollection.customTheme` and `resourcePackages`.

Do not change these:

- `visual.query.queryState` projections. The field bindings came from a checked page, and
  a screenshot is not evidence about data.
- `definition.pbir`. Rebinding the semantic model is not restyling.
- Measure names, `Entity` references, or `Property` names.

Layout maths, gutters, and the visual type list are in
[`reference/pbir-restyle-cheatsheet.md`](reference/pbir-restyle-cheatsheet.md).

### 5. Write the definition back

`update_item_definition` replaces the definition, it does not patch it. Send every
required part, including the parts you did not change, or you will delete pages and
visuals. The required set is `definition.pbir`, `definition/report.json`,
`definition/version.tmdl`, `definition/pages/pages.json`, every `page.json`, and every
`visual.json`. Optional parts such as `StaticResources` may be omitted only when they
have no edits, and in this skill they usually do have edits because of the theme.

Payloads are base64 with `payloadType` set to `InlineBase64`.

### 6. Verify

An `update_item_definition` call that returns success is not evidence the page looks
right.

1. Call `get_item_definition` again and confirm the page count, the visual count per
   page, and that every `queryState` you did not intend to touch is byte identical.
2. Open the report in the service and take a screenshot of the restyled page.
3. Put that screenshot beside the uploaded one and list the differences that remain. Say
   which ones you chose not to fix, and why.
4. Run `python validation/ground_truth.py` and confirm the visible totals still match. A
   layout edit must not move a number. If a number moved, you edited a query, so revert
   and start again from the fetched definition.

Report back: parts changed, parts left alone, remaining visual differences, and the
ground truth result.

## Failure modes

| Symptom | Cause | Fix |
| --- | --- | --- |
| Pages disappeared after the update | Partial part list sent to `update_item_definition` | Re-send the full part list from the fetched definition |
| Update rejected on schema | `$schema` version edited or dropped | Keep the exact `$schema` values that came back from the fetch |
| Theme applied but colours unchanged | Theme file added to `StaticResources` but never registered | Add it to `resourcePackages` and `themeCollection.customTheme` in `report.json` |
| Visuals overlap or fall off the canvas | Positions copied at screenshot pixel size, not scaled to the canvas | Scale by target canvas width divided by screenshot width |
| A number changed after restyling | A `queryState` was rewritten | Revert to the fetched definition and redo positions only |
| Report is `PBIR-Legacy` | Older report stored as a single `report.json` | Do not hand edit. Ask the user to convert it to PBIR, or restyle in Desktop |

## Anti-patterns

- Restyling a page whose numbers were never checked.
- Inventing a measure because the screenshot has a tile you cannot map.
- Overwriting the original Copilot page, which destroys the before and after comparison.
- Claiming a match without putting the two screenshots side by side.
- Copying a customer's or a competitor's proprietary dashboard pixel for pixel. Take the
  layout pattern, not somebody else's branded artwork.

## Docs

- https://learn.microsoft.com/rest/api/fabric/articles/item-management/definitions/report-definition
- https://learn.microsoft.com/power-bi/developer/projects/projects-report
- https://learn.microsoft.com/power-bi/create-reports/desktop-report-themes
- https://learn.microsoft.com/rest/api/fabric/articles/mcp-servers/what-is-fabric-mcp-server
