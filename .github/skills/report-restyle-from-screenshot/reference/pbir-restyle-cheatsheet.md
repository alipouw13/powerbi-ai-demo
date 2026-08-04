# PBIR restyle cheatsheet

Everything here is scoped to layout and formatting. Nothing here changes what a visual
queries. If an edit would change a number, it does not belong in this file.

## Canvas and grid

Pick the canvas first, then place everything on a grid derived from it.

| Canvas | width | height | Outer margin | Gutter | Usable width |
| --- | --- | --- | --- | --- | --- |
| 16:9 standard | 1280 | 720 | 16 | 16 | 1248 |
| 16:9 large | 1600 | 900 | 20 | 20 | 1560 |

Twelve column grid at 1280 x 720 with a 16 px margin and 16 px gutter:

```text
column width = (1280 - (2 * 16) - (11 * 16)) / 12 = 89.33
x of column n (1 based) = 16 + (n - 1) * (89.33 + 16)
```

Common spans at 1280 x 720:

| Tile | Columns | width | Typical height |
| --- | --- | --- | --- |
| KPI card, 4 across | 3 | 283 | 96 |
| Half width chart | 6 | 578 | 260 |
| Two thirds chart | 8 | 789 | 300 |
| Full width chart | 12 | 1248 | 260 |
| Left slicer rail | 2 | 179 | 640 |

Vertical bands that read well: header 0 to 72, KPI row 88 to 184, chart row one 200 to
460, chart row two 476 to 704.

## Scaling a screenshot to the canvas

Screenshots are rarely 1280 wide. Scale, do not copy pixels.

```text
scale        = target_canvas_width / screenshot_width
x_pbir       = round(x_screenshot * scale)
y_pbir       = round(y_screenshot * scale)
width_pbir   = round(width_screenshot * scale)
height_pbir  = round(height_screenshot * scale)
```

Then snap the results to the nearest grid column and check nothing exceeds the canvas:
`x + width <= canvas width` and `y + height <= canvas height`.

## The position block

Only these six fields move a visual.

```json
"position": {
  "x": 16,
  "y": 88,
  "z": 1000,
  "width": 283,
  "height": 96,
  "tabOrder": 1000
}
```

- `z` controls stacking. Background shapes and header bands need a lower `z` than the
  tiles that sit on them.
- `tabOrder` controls keyboard order. Set it to match reading order, top left to bottom
  right, or you have made the page less accessible than the one Copilot generated.

## Visual type names

Use these exact strings in `visual.visualType`.

| Screenshot shows | visualType |
| --- | --- |
| Single big number | `card` |
| Number with target or trend | `kpi` |
| New style KPI card | `cardVisual` |
| Horizontal bars | `barChart` |
| Vertical bars | `columnChart` |
| Grouped vertical bars | `clusteredColumnChart` |
| Stacked vertical bars | `stackedColumnChart` |
| 100 percent stacked bars | `hundredPercentStackedColumnChart` |
| Line over time | `lineChart` |
| Filled line | `areaChart` |
| Bars plus a line | `lineClusteredColumnComboChart` |
| Donut | `donutChart` |
| Pie | `pieChart` |
| Treemap | `treemap` |
| Scatter | `scatterChart` |
| Map with bubbles | `map` |
| Filled map | `filledMap` |
| Grid of values | `tableEx` |
| Grid with row groups | `pivotTable` |
| Dropdown or list filter | `slicer` |
| Text tile | `textbox` |
| Rectangle, line, or band | `shape` |
| Logo or picture | `image` |
| Written summary | `narrativeVisual` |

Swap a type only when the screenshot clearly shows a different chart. A swap between
chart families, for example `donutChart` to `lineChart`, usually needs different field
roles, which means it is a rebuild and not a restyle. Hand those back to
`report-builder`.

## Formatting on a single visual

Formatting lives under `visual.objects` in `visual.json`. Values are expressions, not
bare literals.

```json
"objects": {
  "title": [
    {
      "properties": {
        "text": { "expr": { "Literal": { "Value": "'Net revenue by region'" } } },
        "fontSize": { "expr": { "Literal": { "Value": "14D" } } },
        "fontColor": { "solid": { "color": { "expr": { "Literal": { "Value": "'#1B1B1B'" } } } } },
        "alignment": { "expr": { "Literal": { "Value": "'left'" } } }
      }
    }
  ],
  "labels": [
    {
      "properties": {
        "show": { "expr": { "Literal": { "Value": "true" } } }
      }
    }
  ]
}
```

Literal quoting catches people out. Strings are wrapped in single quotes inside the
value, numbers take a `D` suffix, booleans are bare.

Container level styling, the card behind the visual, sits under
`visualContainerObjects`:

```json
"visualContainerObjects": {
  "background": [
    { "properties": { "color": { "solid": { "color": { "expr": { "Literal": { "Value": "'#FFFFFF'" } } } } },
                      "transparency": { "expr": { "Literal": { "Value": "0D" } } } } }
  ],
  "border": [
    { "properties": { "show": { "expr": { "Literal": { "Value": "true" } } },
                      "radius": { "expr": { "Literal": { "Value": "8D" } } } } }
  ],
  "dropShadow": [
    { "properties": { "show": { "expr": { "Literal": { "Value": "true" } } } } }
  ]
}
```

Prefer the theme for anything that repeats. Per visual formatting is for the exceptions.

## Wiring a custom theme

Three edits, and missing any one of them means the colours silently do not apply.

1. Add the theme file as a part, for example
   `StaticResources/RegisteredResources/ContosoScreenshot.json`.
2. Register it in `report.json` under `resourcePackages`:

```json
{
  "name": "SharedResources",
  "type": "SharedResources",
  "items": [
    { "name": "ContosoScreenshot", "path": "ContosoScreenshot.json", "type": "CustomTheme" }
  ]
}
```

3. Select it in `report.json` under `themeCollection.customTheme`, keeping the
   `reportVersionAtImport` block exactly as it came back from `get_item_definition`:

```json
"themeCollection": {
  "customTheme": { "name": "ContosoScreenshot", "type": "SharedResources" }
}
```

Start from [`../templates/contoso-theme.json`](../templates/contoso-theme.json).

## Page level background

A page fill colour and a header band are the two changes that make the biggest visual
difference for the least risk.

Page fill, in `page.json`:

```json
"objects": {
  "background": [
    { "properties": { "color": { "solid": { "color": { "expr": { "Literal": { "Value": "'#F5F3F0'" } } } } },
                      "transparency": { "expr": { "Literal": { "Value": "0D" } } } } }
  ]
}
```

A header band is a `shape` visual at `x: 0, y: 0, width: canvas width, height: 72` with a
low `z`, plus a `textbox` on top of it for the title.

## Parts checklist before you write

Send all of these to `update_item_definition`, changed or not:

- [ ] `definition.pbir`
- [ ] `definition/report.json`
- [ ] `definition/version.tmdl`
- [ ] `definition/pages/pages.json`
- [ ] every `definition/pages/<pageId>/page.json`
- [ ] every `definition/pages/<pageId>/visuals/<visualId>/visual.json`
- [ ] every `mobile.json` that came back in the fetch
- [ ] `StaticResources/...` when the theme changed
- [ ] `definition/bookmarks/...` when the report has bookmarks
