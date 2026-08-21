# Phase 4. Prep data for AI (preview)

**Agent:** `copilot-readiness`
**Time:** 20 minutes
**AI on show:** Prep data for AI (preview), Approved for Copilot (preview)

This is the argument of the whole demo. Same questions, same data, better answers,
because a human told the model what things mean.

Run pass A first. If you have not scored the questions before doing this phase, stop and
go back to [phase 3](03-model.md). If you have not audited the model, go back to
[phase 3b](03b-readiness-audit.md). Preparing an unaudited model for AI just moves the
problem somewhere harder to find.

**Get a first draft of the AI instructions.**

```text
Review my model and generate text for Prep data for AI (preview) instructions. Use business
friendly terms. Be explicit and specific and use analogies and descriptive language,
avoid ambiguity.
```

Treat the output as a draft rather than pasting it straight in. Copilot describes what
the model *is*; the AI instructions need to say what the business *means*, including the
things that are nowhere in the metadata.

---

## Three features, in two stages

| Feature | What it does | Saved to |
| --- | --- | --- |
| **AI data schema** | Tells Copilot which tables and columns matter, hides the noise | The linguistic schema on the semantic model |
| **Verified answers** | Pins a specific visual to a trigger phrase | The semantic model |
| **AI instructions** | Plain language business rules and context | The linguistic schema on the semantic model |

All three save to the **semantic model**, not to the report. That is why they benefit
every report built on the model, and every agent that uses it.

Configure AI instructions and the AI data schema in this phase. Verified answers need
report visuals, so set those at the end of [phase 5](05-report.md#set-verified-answers).

It is also why they are governable. Anything stored on the semantic model comes with you
into [PBIP and TMDL](https://learn.microsoft.com/power-bi/developer/projects/projects-overview),
which means source control, pull requests, and a diff you can review. Compare that with
instructions typed into a data agent in the service, which have no version history at
all. Phase 7 leans on this: put the business meaning here, keep agent-level instructions
to routing.

**Where to author them**

- **Power BI Desktop:** `Prep data for AI` (preview) on the Home ribbon. Supports Import,
  DirectQuery, and Composite (local) models.
- **Power BI service:** select the semantic model, `Prep data for AI` (preview) on the ribbon,
  then `Apply`. Supports all model types, including Direct Lake.

Users consume these features everywhere Copilot in Power BI exists.

---

## 1. AI instructions

Paste the block from
[`semantic-model/ai-instructions.md`](../semantic-model/ai-instructions.md).

The rule for writing these: **write the business rules that are not visible in the
schema.** Restating column names adds nothing. The useful lines are the ones a new hire
would need told:

| Instruction | Failure it prevents |
| --- | --- |
| Revenue, sales and turnover mean `Total Net Sales`, not `Gross Sales` | Every number 3 to 4 percent too high, subtly |
| Top and best mean highest `Total Net Sales` | Ties broken by the wrong measure |
| Regions and store types are closed lists | An invented "Northwest region" or store type answer |
| Data covers 2024 to 2025 only | A confident answer about 2026 |
| Order Count counts sales order lines | Orders being confused with customers or items |
| Year-over-year needs a single year in context | `Net Sales YoY %` reporting 104.9% instead of 4.9%. This one really happened, see [phase 5](05-report.md). |
| Never sum year or any key column | A total year of 4,050 |
| The model has no forecast | A hallucinated projection presented as fact |

---

## 2. AI data schema

Fewer, better fields. Include what a business user would say out loud. Exclude the rest.

**Include:** all 21 measures, plus `Date` date and period columns, `Product` name,
category and subcategory, `Store` name, city, state, region, store type and opened date,
and `Sales[Channel]`.

**Exclude:** every key column, the raw `Gross Amount`, `Discount Amount`,
`Net Amount`, `Cost Amount` and `Quantity` columns on the fact table, `Month Number` and
`Day of Week Number` (they exist for sorting), and `List Price` and `Cost per Unit` on the
product dimension (they are list values, and averaging them misleads).

Full list in [`semantic-model/ai-instructions.md`](../semantic-model/ai-instructions.md).

Two things to check once you have made the selection, both from the
[readiness checklist](../semantic-model/ai-readiness-checklist.md):

- **Every measure you included can still resolve.** If a measure in the schema depends
  on a column you excluded, you have a gap between what the AI can see and what the
  measure needs.
- **Every measure you included is fast.** Run Performance Analyzer against just these
  measures, not the whole model. A measure that takes several seconds in a visual is a
  measure that times out inside a Copilot answer.

---

## 3. Test it

- Use the **skill picker** in the Desktop Copilot pane to simulate each surface.
  Standalone Copilot (preview) is `Answer questions about the data`. Read mode adds
  `Analyze report visuals`. Edit mode adds `Create new report pages`. Desktop enables
  all three by default.
- **Close and reopen the Copilot pane after every save.** Changes do not reach an open
  pane.
- Expand **How Copilot arrived at this** on every answer. It lists the fields, measures,
  and filters that were used. This is your debugging surface.
- If you need a support case, use `Download diagnostics` on the `...` menu of the Copilot
  pane.

Q&A must be enabled on the semantic model for any of this to work.

---

## 4. Approved for Copilot (preview)

Do this after you have tested the AI instructions and AI data schema.

Power BI service, find the semantic model, `Settings`, expand
`Approved for Copilot` (preview), tick the box, `Apply`.

- It removes the **friction treatment** in the standalone Copilot (preview) experience,
  which is the banner warning users that answer quality could be low.
- Reports built on the model are treated as approved. There is no way to mark a report,
  dashboard, or app approved directly. Only semantic models.
- Usually reflected within an hour, up to 24 hours on a model with many reports. To force
  it, save a small change to a report.
- An admin can additionally enable `Only show approved items in the standalone Copilot in
  Power BI experience` (preview) so unapproved content never appears.

The setting used to be called "prepped for AI".

---

## Then run pass B

Ask the same 15 questions, in the same words, and record pass B in
[`validation/scorecard.md`](../validation/scorecard.md).

**B minus A is the result of this demo.** Everything else is context.

Also re-run the three failure questions. F01, F02 and F03 should now behave, because the
AI instructions cover exactly those cases.

---

## If the AI instructions box looks empty

The pane is a **view over one property of the semantic model**. It is not a store of its
own, and there is no second copy anywhere:

```
ContosoCoffee > model > cultures['en-US']
  > linguisticMetadata > content > CustomInstructions
```

So an empty box has two very different causes, and they need telling apart before anyone
starts retyping a page of instructions:

1. **The text really is gone.** Something wrote the model and left it out.
2. **The pane did not load it.** The property is a single string inside a blob that also
   holds every Q&A synonym in the model — a quarter of a megabyte on this one — and the
   box renders empty while that is still in flight or if the fetch fails.

**Check the property, not the pane.** Either run `agent_remediate` with `DRY_RUN = True`,
which prints the path, the character count and the last three lines before it writes
anything, or read it straight out of the item definition:

```
POST /v1/workspaces/{workspace}/items/{semanticModel}/getDefinition
```

and look at `definition/cultures/en-US.tmdl`. If `CustomInstructions` is there with the
length you expect, the instructions are fine and the pane is the problem. Reload the model
and reopen `Prep data for AI`.

**If it really is gone,** every remediation writes the whole model to
`Files/model_backups/<model>_<stamp>.tmsl.json` immediately *before* it changes anything.
Restore the newest one. Do not approve anything first: a remediation applied to empty
instructions appends its sentence to nothing and gives you a one-line model.

### Why remediation cannot be the cause

Changing that one string means writing the whole model back with `createOrReplace`, and
TMSL is explicit that [omission of a read-write object is considered a
deletion](https://learn.microsoft.com/analysis-services/tmsl/createorreplace-command-tmsl).
That is a real hazard and it is guarded in three places, each of which stops the run:

| Guard | Refuses |
| --- | --- |
| Append-only check, during the diff | New text that does not contain the current text. A short read cannot replace a page of instructions with one approved sentence. |
| Payload census, before the write | A payload holding fewer tables, columns, measures, relationships, roles or Q&A terms than the model does. `createOrReplace` would delete the difference. |
| Result census, after the write | A model that came back smaller than it went in. |

The last one matters most and is the least obvious. In every case where objects are lost,
the instruction string still reads back exactly as sent, because it is the one thing that
was transmitted correctly. Reading it back is not evidence that the model survived, so the
run counts what is left as well.

All three are covered by [`validation/test_model_instructions.py`](../validation/test_model_instructions.py),
which runs the real notebook cells against a double that applies TMSL's deletion rule.

---

## A caveat to say out loud

AI behaviour is nondeterministic. The same prompt can return different wording, and
occasionally a different answer. Prep data for AI (preview) improves the odds, it does not
guarantee an output. Judge the number, not the sentence, and run the bank more than
once if a result surprises you.

---

Docs:
- https://learn.microsoft.com/power-bi/create-reports/copilot-prepare-data-ai
- https://learn.microsoft.com/power-bi/create-reports/copilot-evaluate-data
- https://learn.microsoft.com/power-bi/developer/projects/projects-overview

Next: [phase 5, report](05-report.md)
