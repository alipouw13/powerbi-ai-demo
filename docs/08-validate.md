# Phase 8. Validate

**Agent:** `accuracy-validator`
**Time:** 15 minutes per pass
**AI on show:** none. This phase is the human check on everything above it.

Most AI demos end at phase 6 with a nice chart and no evidence. This phase is why this
one is different.

---

## The loop

```
ask the 15 questions  ->  score against ground truth  ->  find the failures
        ^                                                       |
        |                                                       v
   re-ask the same 15  <-  fix the model, not the prompt  <------+
```

Three rules:

1. **Ask the questions exactly as written.** Rewording a question until it works is not a
   fix, it is hiding a failure.
2. **Fix the model, not the prompt.** The fix belongs in a description, a summarisation
   setting, a name, an AI instruction, or a verified answer.
3. **A verified answer is a patch, not a fix.** It solves one phrasing. Log it as a patch
   so nobody mistakes it for a model improvement.

---

## Get the ground truth

```powershell
python validation/ground_truth.py
```

This reads the CSVs in `data/` and prints the correct answer for all 15 questions. It is
the only source of expected values in this repo. Never type a number in from memory.

Because `data/generate_data.py` is seeded, these numbers are the same for everyone who
runs the demo.

---

## Run a pass

1. Open [`validation/question-bank.md`](../validation/question-bank.md).
2. Ask Q01 to Q15, in order, in one surface. These are the only questions that count
   toward the `/ 15` score.
3. Grade each answer: **Correct**, **Partly correct**, **Wrong**, **Refused**.
   - Partly correct means the number is right but the framing is wrong, or the right
     ranking with a wrong value.
   - Refused counts as a failure for Q01 to Q15, because the model should be able to
     answer them.
4. Record the result in [`validation/scorecard.md`](../validation/scorecard.md).
5. Ask F01 to F03 and record how they behaved in the scorecard's failure questions table.
   They do not change the `/ 15` score. For those probes, refusal or clarification can be
   the correct behaviour.

Five passes are defined:

| Pass | Surface | Run after |
| --- | --- | --- |
| A | Copilot pane, before Prep data for AI (preview) | phase 3b |
| B | Copilot pane, after Prep data for AI (preview) | phase 4 |
| C | Standalone Copilot (preview) | phase 6 |
| D | Fabric data agent | phase 7 |
| E | Data agent plus ontology (preview, optional) | phase 7 |

Score each pass as the count of **Correct** answers across Q01 to Q15. Partly correct,
Wrong, and Refused all count as misses for the score, then belong in the failure log.

**B minus A is the headline.** It is the only number in this demo that measures the value
of the modelling work rather than the value of the product.

Pass A also settles the [phase 3b](03b-readiness-audit.md) audit. Every finding you
recorded there came with a predicted failure attached. Go back and mark which
predictions pass A confirmed. A confirmed prediction is the strongest evidence this demo
produces, because it shows the failure was visible in the metadata before anyone asked
the AI anything.

---

## Diagnose a failure

For every answer that was not Correct, expand **How Copilot arrived at this** and read
the fields, measures, and filters it used. Then find the cause in this table.

| Symptom | Usual cause | Fix |
| --- | --- | --- |
| A total that is a few percent too high | It used `Gross Sales`, not `Total Net Sales` | AI instruction defining the default sales measure |
| A year total of 4,050 | `year` is set to Sum | Set `year` to Don't summarize |
| Confident answer about a region that does not exist | No constraint on region values | AI instruction listing the three regions |
| A forecast | No statement that the model is historical | AI instruction saying there is no forecast |
| Picks the wrong column with a similar name | Two columns, no descriptions | Add descriptions, or exclude one via the AI data schema |
| Correct number, useless wording | Nothing wrong with the model | Verified answer, and log it as a patch |
| Ignores a measure entirely | Not in the AI data schema | Include it |
| Uses the wrong table's `Date` column | Duplicate visible column names across tables | Rename or hide one, or exclude it from the AI data schema |
| Never uses `YTD` or `PY` | Calculation items are not in model metadata | List and explain the items in the calculation group column description |
| Cannot find a number that exists in a report | It is a report-scoped measure | Move it into the semantic model |
| Description is there but ignored | The meaning starts after character 200 | Rewrite so the meaning comes first |

Rows 8 to 11 are the ones that come out of the
[readiness checklist](../semantic-model/ai-readiness-checklist.md). If you ran
[phase 3b](03b-readiness-audit.md) properly, you already predicted them.

Log every one of these in the failure log table in the scorecard, with the cause named as
a piece of metadata, not as "Copilot got it wrong".

---

## Then re-run

Re-run the whole bank, not just the questions that failed. Fixing one description can
change an unrelated answer, and you want to know about that before your audience does.

Note that AI is nondeterministic. If a single answer changes between two runs with no
model change in between, that is expected. Judge the number, not the sentence, and if a
result surprises you, run it again before concluding anything.

---

## Running it automatically

Everything above is the manual pass, and it is still the right thing to do the first time
because watching the answers is how you learn what the model is doing.

The repo also automates it, end to end.
[`validation/automation-spec.md`](../validation/automation-spec.md) covers the design; the
short version is:

1. A Fabric notebook asks every question three times and grades against ground truth.
2. Results go to Delta, and a summary goes to an eventhouse.
3. An Activator rule emails an alert when a run regresses, and a second rule emails a
   digest whenever a run leaves defects nobody has approved or rejected yet.
4. A real-time dashboard shows the failures next to the exact sentence that would fix each
   one. It is read only: it is where you decide, not where you act.
5. A human approves one sentence, from whichever surface suits them: a button in the
   report, an Adaptive Card in Outlook, or
   `python validation/approve.py --question Q10 --by you@example.com`. All three write the
   same row.
6. A third Activator rule runs the remediation notebook, which appends that sentence to
   the model AI instructions and proves the write landed.
7. The next evaluation run says whether it actually worked.

Only step 5 is a person, and only step 5 changes the model.
[`validation/approval-by-email.md`](../validation/approval-by-email.md) compares the three
surfaces. The report button is the one worth building, because it is the only one where
the approver's identity is read from their token rather than typed into a field.

Three things it caught immediately that the manual pass cannot:

- **Nondeterminism.** Six of the eighteen questions answered correctly on some attempts
  and not others. A manual pass asks each question once, so it would have scored the same
  model 14 or 15 out of 15. A question that is right three times in five is worse in front
  of an audience than one that is consistently wrong, because you cannot brief around it.
- **Silent time narrowing.** Q10, Q11 and Q12 carry no time filter, and the agent
  sometimes answered for the most recent period only. The numbers looked plausible and
  were roughly a tenth of the truth.
- **A fix that only half worked.** The approved instruction took the score from 9 to 11
  and fixed the guardrails, and Q10 got worse. The loop knows that only because it
  re-measured.

Run the tests for the grading logic with:

```bash
python -m unittest discover -s validation -p "test_*.py"
```

Three rules from that spec are worth knowing even if you never run it:

- **Repeat every question.** One sample cannot distinguish wrong from ambiguous.
- **The fix goes in the model, not the agent.** Agent instructions are not passed to the
  DAX generation step, so a fix written there looks like a change and does nothing.
- **Never let automation write verified answers.** A loop optimising a `/ 15` score will
  pin its way to 15/15 over a model that is still wrong. A verified answer is a patch, not
  a fix, and that rule has to hold hardest when a machine is applying it.

---

## Repo checks before you present

Run through the checklist at the bottom of
[`validation/scorecard.md`](../validation/scorecard.md):

- `python data/generate_data.py` reproduces the committed CSVs
- `python validation/ground_truth.py` runs clean
- Every number in `docs/` matches that output
- Every preview feature is labelled preview at the point of use
- Every community or third-party asset is labelled as such, and linked not vendored
- Every product claim links to a live Microsoft Learn page
- No tenant IDs, workspace IDs, capacity IDs, or real data anywhere

---

## What to say at the end

The demo has one message, and it belongs here rather than at the start:

> The AI is the same in both passes. The only thing that changed is how well the model
> described itself. Everything you can do to make Copilot better is modelling work you
> should have been doing anyway.

Back to the [README](../README.md).
