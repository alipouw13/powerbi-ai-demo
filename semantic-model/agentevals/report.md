# The AgentEvals report

Two pages over the SQL database that holds the loop's state. Page one is the
evidence, page two is the decision, and the decision goes back to SQL through
a user data function.

```
python validation/build_agentevals_report.py --apply
```

One manual step remains, and it is at the bottom of this file.

---

## Why it looks like the product reviews demo

Because it is the same shape. The translytical task flow demo shows product
reviews and their sentiment on one page, then lets an employee write a comment
back to the database on the next. Swap the nouns:

| Product reviews demo | AgentEvals |
| --- | --- |
| Product | Question |
| Customer review, and its sentiment | Answer, and its Grade |
| Agent comment | `Proposed Instruction`, written by the harness |
| Employee comment written back | Approval `Decision` and `Note`, written by a person |
| `Responded` flag | `Persisted`, then `Verified` |

The visual language is lifted from the Contoso Coffee report on purpose:
1280x720, a `#4C7DF0` header band, five KPI cards at `y=100` on a 243px pitch,
and two content rows. The two reports are one product and should look like it.

**One difference is deliberate.** In the reviews demo the employee comment is
the outcome: it is written, and that is the end of it. Here approving only
records a decision. The remediation notebook applies the sentence, and a later
evaluation run is what says it worked. So the cards on page two count
`Approved`, `Awaiting Apply` and `Verified Fix %` separately, and the page says
so in as many words. Collapsing them into one number would let the report claim
a fix that nobody has written and nothing has verified, which is the failure
this whole loop exists to prevent.

---

## Page one, Agent Answer Quality

| Tile | Reads |
| --- | --- |
| Five KPI cards | `Score Headline`, `Score %`, `Flaky Questions`, `Failing Questions`, `Guardrails Lost` |
| Attempts by question and grade | Every attempt, coloured by grade. A question with two colours is a flake |
| Attempts by grade | The overall split, including `Errored`, which is not the same as wrong |
| Questions and how they were answered | The review list: question, outcome, grade, and the answer verbatim |
| What the harness proposes to fix it | The agent's own comment on each defect |

The last two are separate visuals rather than one wide table, and that is not a
layout preference. `Answers` and `Defects` both point at `Questions`, so a
table mixing their columns asks Power BI to relate one attempt to one proposed
fix. No such relationship exists. It renders as **"Can't determine
relationships between the fields"**, which is exactly how the first version of
this page shipped, and `test_agentevals_report.py` now fails the build for any
visual that uses columns from two fact tables.

## Page two, Review & Approve Fixes

| Tile | Reads |
| --- | --- |
| Five KPI cards | `Defects In Latest Run`, `Awaiting Apply`, `Approved`, `Rejected`, `Verified Fix %` |
| **Proposed fixes awaiting a decision** (left table) | The queue. Selecting a row is what chooses the question the button acts on |
| **Decisions already written back** (right table) | What the function has recorded, and who recorded it |
| Two input slicers, and a button | The decision, the note, and submit |
| Defects by fix tier | Tier 1 is safe to apply, tier 3 is a human judgement |

The input slicers have **no data column bound**. With one they would filter the
page; without one they are input controls, which is what a task flow needs.

---

## The manual step: bind the button

The report ships with the button in place and the action unbound, because the
binding names a workspace, a function set and a function by id. Those are
tenant facts, and this repo keeps them out of source control.

In the Power BI service, edit the report, go to **Review & Approve Fixes**,
select the button under *Then submit your decision:*, and in **Format button**
> **Action** set:

| Parameter | Value |
| --- | --- |
| Type | `Data function` |
| Workspace | the workspace holding the loop |
| Function set | `Approve remediation` |
| Data function | `approve_remediation` |
| `questionId` | **fx** > Format style `Field value` > `Questions` > **Selected Question ID** |
| `decision` | the **Decision (approved or rejected)** input slicer |
| `note` | the **Note for the record** input slicer |

Turn **Auto clear** on, so the note does not carry over to the next decision.

> **If the report editor was already open**, reload the page first. It caches
> the model's field list, so a measure added since you opened it will not be
> in the picker.

### Why `questionId` binds to a measure

`Selected Question ID` sits at the top of the `Questions` table, above the
columns, with no display folder to expand:

```dax
Selected Question ID = SELECTEDVALUE ( 'Questions'[Question ID] )
```

The `Question ID` column works too, but it needs an aggregation such as `First`
or `Max`, and that silently picks one row out of however many are selected and
records a decision against a question the approver did not mean.
`SELECTEDVALUE` returns blank unless exactly one question is in context, so an
ambiguous selection cannot be approved at all. Selecting a row in **Proposed
fixes awaiting a decision** is what puts one question in context.

This model used to set `discourageImplicitMeasures`, and that made the column
fail outright with:

> This field can't be used here because the data model has discourage implicit
> measures property enabled, and a measure is required here.

The flag is now off. It was protecting against summing a per-run score across
runs, and every one of those columns is already hidden, so nobody can drag one
onto a visual in the first place. It was buying almost nothing and breaking the
report's main interaction.

While you are in that pane, set the button's **Text** to `Submit decision` and
its **Fill** to `#4C7DF0`. The generated definition already carries both, and
Fabric stores them, but they do not survive to a rendered export: four
different property shapes were published and exported to establish that, and
all four rendered as an empty outline while `outline` itself was honoured. So
the button is given a strong blue outline, which does render, and a caption
above it, so that the page reads correctly before anyone has been near the
format pane.

`submit_feedback(questionId, verdict, comment)` is the other function on the
same set, for a second button if you want readers to flag an answer without
approving anything. Feedback is evidence that a defect may exist. It is not an
approval and cannot become one.

---

## Testing checklist

- The tables are empty until an evaluation run has written to the SQL
  database. Cards showing `--` mean no runs yet, not a broken report.
- Run `python validation/build_agentevals_report.py --apply` after any change
  to the model: a renamed field leaves the report definition valid and the
  visual broken, and `test_agentevals_report.py` is what catches it.
- Click the button once and check `dbo.approvals` has exactly one new row. A
  data function button that has not been styled for its loading state looks
  identical while it runs, and gets clicked twice.
