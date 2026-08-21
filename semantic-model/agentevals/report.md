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
| Questions and how they were answered | The review list: question, outcome, grade, attempts, and the answer verbatim |
| What the harness proposes to fix it | The agent's own comment on each defect, and how many runs have found it |

The last two are separate visuals rather than one wide table, and that is not a
layout preference. `Answers` and `Defects` both point at `Questions`, so a
table mixing their columns asks Power BI to relate one attempt to one proposed
fix. No such relationship exists. It renders as **"Can't determine
relationships between the fields"**, which is exactly how the first version of
this page shipped, and `test_agentevals_report.py` now fails the build for any
visual that uses columns from two fact tables.

### Every table mixing two tables carries a measure

Look at the tables and you will find a count in each: `Attempts`, `Defects
Found`, `Decisions Made`. They are there to be read, but they are also load
bearing, and removing one is a data correctness bug rather than a cosmetic
change.

A table of **columns alone**, drawn from a dimension and a fact, is a cross
join. Power BI groups by the columns it was given and, with no measure to
evaluate, keeps every combination rather than only the ones the relationships
support. The approval queue shipped that way: it listed all eighteen questions
against every outcome and every tier, including questions that had never
failed, plus a blank question id for the combinations belonging to no question
at all. Seventy-six rows where thirteen were real, and each one looked exactly
like a genuine proposed fix.

The relationships were never wrong. Adding any measure over the fact table
fixes it, because a row whose measures are all blank is dropped, and a fact
measure is blank precisely where no fact row exists. A measure over the
*dimension* does not work: it is non-blank for every row of the cross join, so
the visual stays wrong and now looks deliberate. `test_agentevals_report.py`
checks both halves of that rule.

## Page two, Review & Approve Fixes

| Tile | Reads |
| --- | --- |
| Five KPI cards | `Defects In Latest Run`, `Awaiting Apply`, `Approved`, `Rejected`, `Verified Fix %` |
| **Proposed fixes awaiting a decision** (left table) | The queue. Selecting a row is what chooses the question the button acts on |
| **Decisions already written back** (right table) | What the function has recorded, and who recorded it |
| Two input slicers, and a button | The decision, the note, and submit |
| Defects by fix tier | Tier 1 is safe to apply, tier 3 is a human judgement |

The queue carries a **Writes To** column, sitting ahead of the instruction
rather than behind it, because the instruction is wide enough to push anything
after it out of view and a reviewer should not have to scroll to find out what
they are changing. A semantic model instruction lands in exactly one property,
`cultures['en-US'].linguisticMetadata.content.CustomInstructions`, which is the
**AI instructions** box under Prep data for AI. It is not the model
description, and it is never a table, a column or a measure: a fix needing one
of those is tier 2 and leaves the automated loop for a person.

`Writes To` is blank for anything not in the decision queue, and that blank is
what makes the table a queue rather than a log. `In Decision Queue` is 1 only
when the **most recent run** found the defect and nobody has yet decided on
that exact sentence for that question. Both halves matter:

- **Latest run only.** The loop re-detects everything still wrong on every
  run, so a defect from an older run is history, not work. Without this the
  same question appears once per run it ever failed in, each row offering the
  same fix, and the reviewer cannot tell which one is current.
- **Not already decided.** Once a sentence has been approved or rejected for a
  question, it is no longer awaiting a decision, and leaving it in the queue
  invites a second write of a line that is already there.

The input slicers have **no data column bound**. With one they would filter the
page; without one they are input controls, which is what a task flow needs.

## Page three, Same Fix, Several Questions

| Tile | Reads |
| --- | --- |
| Five KPI cards | `Questions Sharing This Fix`, `Awaiting Apply`, `Covered By Another Approval`, `Instructions Written`, `Already Present` |
| **Questions proposing the same sentence** | The group: one sentence, every question it was proposed for |
| Two input slicers, and a button | The decision, the note, and submit |
| **What has already been decided** | Who has decided what, for the questions in view |

The harness proposes fixes from a small library, so one wrong behaviour usually
appears as the same sentence against four or five questions at once. Approving
them one at a time on page two is five clicks that all mean the same thing, and
four of the five would queue a write that changes nothing, because the first
one already added the line.

This page records the decision once. Approve a question on page two first, then
come here: `approve_similar` writes an approval row for every other question
carrying that sentence, each marked `covered_by` the approval that carries the
change, together with a remediation row that has **no applied time**. Every
question has a real decision against it, the approvals are closed so nothing
queues a second write, and `Already Present` counts them separately from
`Instructions Written` so the report never claims a fix it did not make.

Choosing not to approve them is a valid answer. They stay in the queue and can
be decided one at a time.

The two writeback buttons are on separate pages on purpose. They take the same
three parameters and mean very different things, and side by side, approving a
group when you meant to approve one question is a slip rather than a decision.

---

## The manual step: bind the buttons

The report ships with the buttons in place and their actions unbound, because
the binding names a workspace, a function set and a function by id. Those are
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

Then do the same on **Same Fix, Several Questions**, for the button under *Then
approve the rest of the group:*, with the same parameters and
`approve_similar` as the data function. Bind its `decision` and `note` to
**that page's** input slicers, not page two's.

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

### Rebuilding does not undo it

`build_agentevals_report.py --apply` replaces every part of the report, so on
the face of it a rebuild would delete the binding you just configured. It does
not: the builder reads the deployed report first and carries the binding
across, printing

```
kept the existing data function binding (approve_remediation)
```

when it finds one, once per bound button. That works because the visual ids are
deterministic, so the slicers the binding names are still there under the same
ids after a rebuild. The builder checks that rather than assuming it, and says
so if a referenced slicer has gone.

This was found the hard way. The first version of the carry-over looked for
the binding under `objects`; it lives under `visualContainerObjects`, so it
found nothing, said nothing, and the rebuild silently dropped a working
binding. Both containers are searched now, and the test uses the real one, so
a test that passes cannot mean a carry-over that does not.

If you change the binding in the portal, the change is picked up by the next
rebuild automatically. It only lives in the deployed report, so it is worth
knowing that a deleted workspace takes it with it.

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

---

## If every visual says "Something's wrong with one or more fields"

Check the model's **table names** first:

```bash
python validation/build_agentevals_model.py --verify
```

A Direct Lake schema sync can reset table names to the source names, turning
`Evaluation Runs` back into `runs`. The report binds by name, so every visual
that touches that table breaks at once, and the error names a measure rather
than a table:

> Something's wrong with one or more fields: (Evaluation Runs) Score %

Re-running `--apply` fixes it in about a minute.

Two things make this worth knowing rather than guessing at.

**The measures keep working.** Fabric rewrites their DAX to the new table
name, so all 36 still evaluate. An earlier version of `--verify` checked only
the measures and reported a clean model while the report was entirely broken.
It now checks the table names first, and that is the check that matters.

**`Evaluation Runs` is the only rename that can break.** Six of the seven
model tables differ from their source only in case — `questions` to
`Questions` — and DAX is case-insensitive, so a sync that reverts those
changes nothing. `runs` to `Evaluation Runs` is the single genuine rename in
the model, which makes it the single point of failure.
