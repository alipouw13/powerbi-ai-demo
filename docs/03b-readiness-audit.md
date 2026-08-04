# Phase 3b. Audit the model before you score it

**Agent:** `model-readiness-auditor`
**Time:** 15 minutes
**AI on show:** none for the audit itself, deliberately; Copilot in Desktop only to draft the fixes

This is a gate, not a phase. It sits between [phase 3](03-model.md) and
[phase 4](04-prep-for-ai.md), and it takes fifteen minutes.

The demo's argument is that AI quality is decided by model quality. That argument is
worth more if you can *measure* model quality before you measure AI quality. Otherwise
you are asserting the thing you claim to be proving.

So: score the model, then score the AI.

---

## Why bother

Microsoft publishes a specific list of what a semantic model needs in order for Copilot
to work well:
[Optimize your semantic model for Copilot in Power BI](https://learn.microsoft.com/power-bi/create-reports/copilot-evaluate-data).

It is organised into five areas:

| Area | What it covers |
| --- | --- |
| Model structure | Relationships, cardinality, fact and dimension separation, hierarchies |
| Measures and KPIs | Standardised logic, purposeful names, predefined measures and KPIs |
| Columns and data quality | Unambiguous names, correct data types, standardised values |
| Refresh, security, metadata | Refresh transparency, security roles, documented structure |
| DAX query considerations | Descriptions everywhere, the 200 character window, calculation groups |

None of that is new advice. It is the modelling work a good BI developer already does.
That is the point the demo keeps making: **there is no separate AI project.**

---

## Run the checklist

The full list, with the Contoso Coffee specifics filled in, is
[`semantic-model/ai-readiness-checklist.md`](../semantic-model/ai-readiness-checklist.md).

Work down it and tick boxes. Anything you cannot tick, write down as a **prediction**:

> `year` is still set to Sum, so Q05 and Q06 will come back wrong or refused.

Keep that list. Pass A will tell you which predictions were right, and a correct
prediction is a much stronger demo moment than a failure you did not see coming.

---

## Three items nearly everyone misses

Out of the whole checklist, these three are the ones that reliably surprise people.

**1. The 200 character window is real and it is short.**
Copilot uses only the first 200 characters of a description. Not the first 200 words.
Put the business meaning first and the caveats last, because the caveats will be cut.

**2. Calculation items are not in the model metadata at all.**
If your model has a calculation group with `YTD`, `MTD` and `PY` items, Copilot has no
way of knowing those items exist. The only place it can learn them is the calculation
group column's **description**, so that description has to list them and explain them.
And it is also cut at 200 characters, so list first, explain second. Contoso Coffee has
no calculation group. Almost every real model does, which is why this is here.

**3. A measure defined in a report is invisible to anything reading the model.**
Report-level measures live in the report. A data agent, or a standalone Copilot session
pointed at the semantic model, reads the model. If a number only exists as a report
measure, the agent cannot use it, and nobody gets an error explaining why.

---

## Automate it, optional

There is a community Fabric notebook that runs most of this list for you and returns a
severity-weighted score:

```text
https://github.com/SoomroFarhanH/SemanticModelBPforAI/tree/main/SemanticModel-AI-Readiness-Analyzer
```

> **Community project, not a Microsoft product.** It is not supported by Microsoft and
> it is not covered by any Microsoft SLA. Read it before you run it against anything you
> care about. It is included here because it is the only automated version of the Learn
> checklist that we are aware of, and because a score is more useful than an opinion.

How to run it, from that project's README:

1. Publish the `ContosoCoffee` semantic model to a Fabric workspace. Phases 1 to 3
   already did this.
2. Make sure you have **Build** permission or higher on the model.
3. Create a notebook in the same Fabric workspace and import
   `SemanticModelAIReadinessAnalyzer.ipynb`.
4. Run it. It installs `semantic-link-labs` itself and then prompts for the workspace
   and model names.

It groups findings as **Critical**, **Important** and **Recommended**. Fix every Critical
one before pass A. A Critical finding is not an AI problem, it is a modelling problem
that AI is about to make visible.

Underneath, it uses
[Semantic Link](https://learn.microsoft.com/fabric/data-science/semantic-link-overview)
and [Semantic Link Labs](https://github.com/microsoft/semantic-link-labs), the Microsoft
open source library that gives Python access to model metadata, the Best Practice
Analyzer, and the Memory Analyzer. Those are worth knowing about on their own, whether or
not you use this particular notebook.

Two checks it cannot automate, and you should still do by hand:

- **Memory Analyzer**, to find the columns that cost the most and buy the least.
- **Performance Analyzer**, against only the measures you are about to put in the AI
  data schema. A measure that takes several seconds in a visual will time out inside a
  Copilot answer.

---

## Fix it with Copilot in Power BI Desktop

The audit tells you what is wrong. Copilot in Power BI Desktop is a fast way to draft the
fix. Treat everything it returns as a **draft you review**, not an edit you accept
blindly — you are the one who knows what the business calls these things.

Enable Copilot in Desktop, then use these prompts against the `ContosoCoffee` model.

**Rename things so a human, and an LLM, can tell them apart.**

```text
Recommend better names for tables, columns, and DAX measures.
```

This is the single highest-value prompt in the phase. Ambiguous names — `date2`, `amt`,
`Sales 2` — are the most common reason Copilot picks the wrong column, and no amount of
instruction text later on rescues a model whose names do not mean anything.

Rename before you build anything on top of the model. A rename applied after phase 5
means revisiting report visuals, verified answers, and any DAX that referenced the old
name, so do this here rather than later.

**Get a first draft of the AI instructions you will paste in phase 4.**

```text
Review my model and generate a text for Prep data for AI instruction. Use business
friendly terms. Be explicit and specific and use analogies and descriptive language,
avoid ambiguity.
```

Take the output into [phase 4](04-prep-for-ai.md) rather than pasting it straight in.
Copilot describes what the model *is*; the AI instructions need to say what the business
*means*, including the things that are nowhere in the metadata.

**Ask for a general critique.**

```text
Suggest improvements to this semantic model.
```

Deliberately open-ended. Use it as a second opinion on the checklist, then keep only the
findings you can map back to a Learn area in the table above.

**Fill in the descriptions — already done, in phase 3.**

Measure descriptions are the thinnest part of most models, and they are the thing Copilot
actually reads at query time.
[Phase 3 covers this](03-model.md#descriptions-ask-copilot-in-the-fabric-model-view) with
the Copilot pane in Fabric model view, because it belongs with the measures rather than
with the audit. If you skipped it, go back and do it now — an audit of a model with no
measure descriptions has one finding, and it is that one.

---

## Where the fix belongs

The audit tends to produce a pile of small fixes. Put them in the right layer, because
the layers have very different lifecycles.

| Fix | Belongs in | Version controlled |
| --- | --- | --- |
| Names, data types, relationships, hierarchies | Semantic model | Yes, via PBIP and TMDL |
| Descriptions, synonyms, row labels | Semantic model | Yes, via PBIP and TMDL |
| AI instructions, AI data schema, verified answers | Semantic model | Yes, via PBIP and TMDL |
| Data agent instructions and example queries | The data agent item in the service | No |

That last row is the one to think about. Anything you can express in the **semantic
model** gets source control, pull requests, and a diff. Anything you express only in the
**data agent** is a service-level setting with no Git story, which means two people can
change it and neither can see what the other did.

Practical rule: put business meaning in the model, and keep data agent instructions to
the things only the agent knows, mainly which source to route a question to when it has
several. Phase 7 uses exactly that split.

---

## Then run pass A

Now go and run pass A as [phase 3](03-model.md) describes: the same 15 questions from
[`validation/question-bank.md`](../validation/question-bank.md), scored into
[`validation/scorecard.md`](../validation/scorecard.md).

You now have two numbers to compare instead of one: what the audit said would break, and
what actually broke.

---

Docs:
- https://learn.microsoft.com/power-bi/create-reports/copilot-evaluate-data
- https://learn.microsoft.com/power-bi/create-reports/copilot-prepare-data-ai
- https://learn.microsoft.com/power-bi/create-reports/copilot-introduction
- https://learn.microsoft.com/fabric/data-science/semantic-link-overview
- https://learn.microsoft.com/power-bi/developer/projects/projects-overview
- https://github.com/microsoft/semantic-link-labs
- Semantic Model AI Readiness Analyzer, community project, not a Microsoft product:
  https://github.com/SoomroFarhanH/SemanticModelBPforAI/tree/main/SemanticModel-AI-Readiness-Analyzer

Next: [phase 4, prep for AI](04-prep-for-ai.md)
