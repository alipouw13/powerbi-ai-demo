# Scorecard

Fill this in as you run the demo. This file is the deliverable. A demo with no scorecard
is a demo that proved nothing.

Get the expected values with `python validation/ground_truth.py`.

Filling this in by hand is the intended process for a demo, and it is how you learn what
the model is doing. The repo also automates it: see
[`automation-spec.md`](automation-spec.md) and the `agent_eval` notebook, which generate
these results rather than having a human type them.

---

## Passes

| Pass | Surface | Run after | Date | Score |
| --- | --- | --- | --- | --- |
| A | Copilot pane, before Prep data for AI (preview) | phase 3b | | / 15 |
| B | Copilot pane, after Prep data for AI (preview) | phase 4 | | / 15 |
| C | Standalone Copilot (preview) | phase 6 | | / 15 |
| D | Fabric data agent | phase 7 | | / 15 |
| E | Data agent plus ontology (preview, optional) | phase 7 | | / 15 |

The number that matters is B minus A. That is what the modelling work bought you.

---

## Readiness audit, phase 3b

Filled in **before** pass A, from
[`semantic-model/ai-readiness-checklist.md`](../semantic-model/ai-readiness-checklist.md).

| Severity | Finding | Object | Predicted to break | Confirmed by pass A |
| --- | --- | --- | --- | --- |
| | | | | |

Severity: Critical (wrong answer, silently), Important (vague, refused, inconsistent),
Recommended (quality and maintenance, not correctness).

Fix every Critical finding before you run pass A. The Important and Recommended ones are
better left in place until after pass A, because they are the demo.

An audit finding with no predicted failure is a style note. Delete it or attach a
question number to it.

---

## Question results

| # | Expected | A | B | C | D | E |
| --- | --- | --- | --- | --- | --- | --- |
| Q01 | $412,918.50 | | | | | |
| Q02 | $283,482.20 | | | | | |
| Q03 | 68.65% | | | | | |
| Q04 | 94,417 | | | | | |
| Q05 | $201,522.35 | | | | | |
| Q06 | $211,396.15 | | | | | |
| Q07 | 4.90% | | | | | |
| Q08 | Contoso Midtown, $75,663.08 | | | | | |
| Q09 | Latte Regular, $57,045.27 | | | | | |
| Q10 | West $178,256.56, East $144,668.89, Central $89,993.05 | | | | | |
| Q11 | Beverage $298,987.00, Food $79,779.50, Retail $34,152.00 | | | | | |
| Q12 | In Store $256,105.03, Mobile Order $111,125.55, Delivery $45,687.92 | | | | | |
| Q13 | December 2025, $21,241.47 | | | | | |
| Q14 | Weekend $96,223.79, Weekday $316,694.71 | | | | | |
| Q15 | $6.42 | | | | | |

Grades: Correct, Partly correct, Wrong, Refused.

## Failure questions

| # | Good outcome | A | B | C | D |
| --- | --- | --- | --- | --- | --- |
| F01 | Says historical data only, does not project | | | | |
| F02 | Clarifies margin dollars vs margin rate, or states that it used margin dollars | | | | |
| F03 | Says Northwest does not exist | | | | |

---

## Failure log

One row per answer that was not Correct. This is the most useful part of the file.

| Pass | Q# | What came back | What was expected | Cause | Fix applied | Fixed on pass |
| --- | --- | --- | --- | --- | --- | --- |
| | | | | | | |

Cause should name a piece of metadata, for example "summarisation on `year` was set to
Sum" or "no AI instruction defining revenue". Fix should name the change, for example
"set `year` to Don't summarize" or "added the revenue definition to AI instructions".

If the fix was a verified answer for that exact phrase, label it a patch, not a fix. A
verified answer solves one question. It does not improve the model.

---

## Repo checks

Run these before presenting or publishing.

- [ ] `python data/generate_data.py` reproduces the committed CSVs
- [ ] `python validation/ground_truth.py` runs clean
- [ ] Every number in `docs/` and `README.md` matches the ground truth output
- [ ] Every preview feature is labelled preview at the point of use
- [ ] Every community or third-party asset is labelled as such, and linked not vendored
- [ ] Every product claim links to a live Microsoft Learn page
- [ ] No tenant IDs, workspace IDs, capacity IDs, or real data anywhere
- [ ] No em dashes anywhere
