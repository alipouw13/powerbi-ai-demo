# AI readiness checklist

The audit you run **between phase 3 and phase 4**, before you score pass A.

Two sources feed this list:

1. [Optimize your semantic model for Copilot in Power BI](https://learn.microsoft.com/power-bi/create-reports/copilot-evaluate-data),
   the official Microsoft Learn guidance. Its five categories are the five sections
   below.
2. The community
   [Semantic Model AI Readiness Analyzer](https://github.com/SoomroFarhanH/SemanticModelBPforAI/tree/main/SemanticModel-AI-Readiness-Analyzer),
   a Fabric notebook that automates 21 or more of these checks and returns a
   severity-weighted score. Community project, not a Microsoft product.

Tick each box for the Contoso Coffee model. Anything you cannot tick is a predicted
failure in pass A, and you should be able to name which question it will break.

Sections 1 to 5 follow the Learn tables. Section 0 and section 6, and the items marked
*(analyzer)*, come from the community project and are that project's opinion rather than
Microsoft guidance. Both are useful. Only one is official.

---

## 0. Scope

Before anything technical. The analyzer opens with this and it is the right place to
start.

- [ ] The model answers **one** subject area, not six. Contoso Coffee is retail sales
      only. It has no inventory, no marketing, no support tickets.
- [ ] You can state in one sentence who asks it questions and what they ask about.
- [ ] Security requirements are known. If row-level security is needed, it exists before
      the AI does, not after.

A model that tries to answer everything answers nothing well. Narrow scope is the
cheapest accuracy improvement available.

---

## 1. Model structure

From the Learn **Model structure** table.

- [ ] **Relationships defined and logical.** All three exist, all three are active,
      all three are many to one. Copilot cannot join what you did not join.
- [ ] **Fact table clearly delineated.** `fact_sales` holds the measurable data and
      nothing else.
- [ ] **Dimension tables hold descriptive attributes.** `dim_product`, `dim_store`,
      `dim_date`.
- [ ] **Star schema kept.** No flattening, no second fact table.
- [ ] **Hierarchies established** on dimensions that people drill into. For this model:
      `dim_date` as Year, Quarter, Month, Day. Learn calls these out explicitly, and
      most demo models skip them.
- [ ] **Relationship types specified.** Cardinality and active or inactive set
      deliberately, not left at whatever the auto-detect produced.
- [ ] **No isolated visible tables.** *(analyzer)* A visible table with no relationship
      is a table Copilot will use wrongly. Connect it or hide it.
- [ ] **Bidirectional cross-filtering used sparingly.** *(analyzer)* None needed here.
- [ ] **No duplicate visible column names across tables.** *(analyzer)* If two tables
      both expose `Date`, the DAX generator can pick the wrong one and produce a wrong
      answer with no error message. This one is silent, which makes it the worst kind.

## 2. Measures and KPIs

From the Learn **Measures and KPIs** table.

- [ ] **Standardised calculation logic.** Every measure is explainable in one sentence.
- [ ] **Names reflect purpose.** `Average Customer Rating`, not `AvgRating`. In this
      model, `Net Revenue`, not `SumNetAmt`.
- [ ] **Predefined measures exist** for what users will actually ask. All 18 are in
      [`measures.dax`](measures.dax).
- [ ] **Explicit measures only.** Every numeric column has summarisation set to
      `Don't summarize`, so nobody gets an implicit aggregation they did not ask for.
      This is the check that stops a total year of 4,050.
- [ ] **No report-scoped measures.** *(analyzer)* A measure defined inside a report
      lives in the report, not in the semantic model, so anything reading the model
      cannot see it. Move it into the semantic model or it does not exist as far as the
      AI is concerned.
- [ ] **Helper and intermediate measures hidden.** *(analyzer)* If a measure only exists
      to feed another measure, it is noise in the schema. Hide it.

## 3. Columns and data quality

From the Learn **Columns and data quality** table.

- [ ] **Column names unambiguous and self-explanatory.** No `ProdID`, no `F_SLS_AMT`,
      no ALL_CAPS, no database prefixes. The AI reads names literally.
- [ ] **Data types correct and consistent.** Dates as dates, money as decimal, keys as
      whole numbers. A date stored as text breaks every time-based question.
- [ ] **Values standardised within a column.** `In Store`, not a mix of `In Store`,
      `in store` and `INSTORE`.
- [ ] **Data categories set.** `dim_store[city]` as City, `dim_store[state]` as State or
      Province. This is how Copilot decides it can draw a map.
- [ ] **Row labels set on dimensions.** Q&A tooling lets you name the column that best
      identifies a single row in a table, so "sales by store" charts store names instead
      of treating the table as a single thing.
- [ ] **Synonyms added** for real business vocabulary: revenue, sales, turnover,
      takings.
- [ ] **Date ambiguity resolved.** *(analyzer)* If a model has several date columns, the
      AI has to guess which one "last month" means. Hide the extras, or describe the
      primary one, or say it in an AI instruction.
- [ ] **Hidden objects still have descriptions.** *(analyzer)* Hiding a column does not
      remove it from a verified answer that already references it, so a later model
      change can break that answer without any error.

## 4. Refresh, security, and metadata

From the Learn **Refresh, security, and metadata** table.

- [ ] **Refresh schedule communicated**, so nobody argues with a number that is simply
      a day old.
- [ ] **Security roles defined** where sensitive data exists. Not needed for synthetic
      coffee sales, needed for anything real.
- [ ] **Model structure documented.** Descriptions on tables, columns, and measures are
      the documentation the AI actually reads.

## 5. DAX and description quality

From the Learn **DAX query considerations** table. These are the two most commonly
missed items in the entire list.

- [ ] **Descriptions on everything visible.** Tables, columns, and measures. Say what
      the thing is, and when someone should use it.
- [ ] **The important words are in the first 200 characters.** Copilot uses only the
      first 200 characters of a description. Anything after that is discarded. Front
      load the business meaning.
- [ ] **Calculation groups describe their items.** The model metadata does not include
      calculation items at all, so the only way Copilot learns that `YTD`, `MTD` and
      `PY` exist is if you list them in the calculation group column's description. And
      that description is also cut at 200 characters, so list the items first and
      explain second. Contoso Coffee has no calculation group, but every real model
      does, and this is the check that catches it.

---

## 6. Size and performance

Not in the Learn optimization tables. All three come from the analyzer, and they matter
at real scale rather than on a model this small.

- [ ] **Model is not bloated.** *(analyzer)* Every visible object is metadata competing
      for space in what gets sent to the model. The analyzer flags models with more than
      500 visible columns or more than 150 visible measures as candidates for a focused
      AI data schema.
- [ ] **Measures in the AI data schema run fast.** *(analyzer)* Run Performance Analyzer
      against the measures you selected in phase 4, not against the whole model. A
      measure that takes several seconds turns into a timeout inside a Copilot answer.
- [ ] **Measure dependencies are inside the schema.** *(analyzer)* If a measure in your
      AI data schema depends on a column you excluded, you have a gap between what the
      AI can see and what the measure needs.

---

## Running it automatically

The manual list above is the audit. The community analyzer notebook does most of it for
you and adds a severity-weighted score, which makes it repeatable rather than a matter
of who was looking.

```text
https://github.com/SoomroFarhanH/SemanticModelBPforAI/tree/main/SemanticModel-AI-Readiness-Analyzer
```

Requirements, from that project's README:

- Run it inside a **Microsoft Fabric workspace notebook**
- The semantic model must already be published to a Fabric workspace
- You need **Build** permission or higher on the model
- It installs `semantic-link-labs` itself
- It recommends running the Best Practice Analyzer and Memory Analyzer first

It wraps [Semantic Link](https://learn.microsoft.com/fabric/data-science/semantic-link-overview)
and [Semantic Link Labs](https://github.com/microsoft/semantic-link-labs), both of which
are worth knowing about independently. Semantic Link Labs is a Microsoft open source
project and gives you programmatic access to model metadata, the Best Practice Analyzer,
and the Memory Analyzer from Python.

Findings come back ranked Critical, Important, Recommended. Fix Critical before you
score pass A, because a Critical finding is not an AI problem, it is a modelling problem
that AI will expose.

---

## What this buys you

Every unticked box above is a prediction. `year` left summable predicts a wrong answer
to any question that groups by year. A missing description on `Gross Margin %` predicts
Q03 comes back as margin dollars. Two tables both exposing `Date` predicts an answer
that is confidently wrong and gives you nothing to point at.

That is the useful thing about running the audit before pass A rather than after: you
end up with a written list of predicted failures, and then pass A tells you which
predictions were right. That is a much better conversation than "the AI got it wrong".

---

Docs:

- https://learn.microsoft.com/power-bi/create-reports/copilot-evaluate-data
- https://learn.microsoft.com/power-bi/create-reports/copilot-prepare-data-ai
- https://learn.microsoft.com/power-bi/natural-language/q-and-a-tooling-intro
- https://learn.microsoft.com/fabric/data-science/semantic-link-overview
- https://github.com/microsoft/semantic-link-labs
- Semantic Model AI Readiness Analyzer, community project, not a Microsoft product:
  https://github.com/SoomroFarhanH/SemanticModelBPforAI/tree/main/SemanticModel-AI-Readiness-Analyzer
