# Spec: automated agent evaluation and guarded remediation

**Status:** proposed, not built. Nothing in this repo implements it yet.
**Scope:** pass D, the Fabric data agent. Extends to passes B and C where noted.

Today the accuracy loop in [`docs/08-validate.md`](../docs/08-validate.md) is entirely
manual. A human asks 15 questions, grades them by eye, and types the result into
[`scorecard.md`](scorecard.md). That is deliberate for a demo, and it does not scale past
one person running it once.

This spec describes what a production version looks like: scheduled evaluation, drift
detection, a human confirmation gate, and guarded remediation.

---

## 1. Design principles

These come from the repo's own doctrine and from what the platform will and will not let
you automate. Read them before the architecture, because two of them rule out the obvious
implementation.

**1.1 The agent is not where most fixes go.** For a semantic model source, agent-level
instructions are **not passed to the DAX generation step**
([`docs/07-agents.md`](../docs/07-agents.md)). Editing the agent instruction box cannot
fix a wrong number. It changes how the reply is worded, nothing more. Any automation that
"modifies the agent" in response to a wrong figure will appear to act and will change
nothing. Remediation targets Prep data for AI (preview), the model metadata, and the AI
data schema. The agent is the last thing you touch.

**1.2 Never let the loop write verified answers.** A verified answer pins one phrase to
one reviewed visual. It raises the score for that phrasing and improves the model by
nothing. An automated remediation loop optimising a `/ 15` score will discover this
immediately and pin its way to 15/15 over a model that is still wrong. That is Goodhart's
law with commit rights. The repo already says a verified answer is a patch, not a fix.
Here that becomes a hard constraint: **verified answers are human-authored only, and never
close a defect.**

**1.3 One failure is not a defect.** AI is nondeterministic. A single wrong answer is a
sample, not evidence. Every question runs `N` times per evaluation and is classified on
the distribution, not the last response.

**1.4 Ground truth is the only oracle.** `data/generate_data.py` is seeded, so
`ground_truth.py --json` is deterministic and identical for everyone. It is safe to
compare against automatically. Nothing else in the loop is.

**1.5 Automate detection fully. Gate correction.** Detection, scoring, diagnosis and
proposal have no blast radius and should run unattended. Applying a change to a governed
semantic model does. Nothing reaches production without a human merge.

**1.6 Every automated change must be reversible and reviewable.** Which means it arrives
as a pull request against this repo, not as a live edit through an API. The artefacts that
matter here already live in source control.

---

## 2. Architecture

```
  schedule (daily)
        |
        v
  [1] eval notebook  ---- MCP endpoint (preview) ---->  Fabric data agent
        |                                                     |
        |  <---------------- answer + generated DAX ----------+
        v
  [2] score vs ground_truth.py --json      (N runs per question)
        |
        v
  [3] Delta tables in lakehouse: eval_runs, eval_results, eval_defects
        |
        v
  [4] eval semantic model + report  --->  [5] Activator alert on the visual
                                                      |
                                                      v
                                          [6] Teams Adaptive Card to owner
                                                      |
                                   confirmed defect ---+--- flake / expected
                                                      |            |
                                                      v            v
                                          [7] classify + propose   log, no action
                                                      |
                                                      v
                                          [8] pull request, human merge
                                                      |
                                                      v
                                          [9] re-run, verify, close
```

### Component 1, the eval runner

A Fabric notebook, scheduled. Not a GitHub Action, because it needs a Fabric identity to
reach the agent and the lakehouse.

- Reads questions from [`question-bank.md`](question-bank.md), parsed from the existing
  markdown table. One source of questions, not two.
- Queries the agent over the **MCP endpoint (preview)**,
  `https://api.fabric.microsoft.com/v1/mcp/workspaces/{workspaceId}/dataagents/{dataAgentId}/agent`,
  scope `https://api.fabric.microsoft.com/.default`. Prefer this over the Python client
  path, which builds on the OpenAI Assistants API and has an announced shutdown date of
  26 August 2026.
- Asks each question **exactly as written**. The runner must not template, expand or
  soften them. That rule exists so scores stay comparable across passes.
- `N = 5` repetitions per question, in fresh threads, so that history does not leak between
  runs.
- Captures for each response: the answer text, the generated DAX, latency, and any refusal.
- Runs Q01 to Q15 for scoring, and F01 to F03 for behaviour.

### Component 2, scoring

Comparison is numeric with tolerance, never string equality. An answer of
`$412,918.50`, `412918.5` and `roughly 412.9k` are the same result and only the third is
arguably a miss.

| Grade | Rule |
| --- | --- |
| Correct | Every expected value present, within tolerance |
| Partly correct | Right ranking or right value, wrong framing or one value off |
| Wrong | A value is present and outside tolerance |
| Refused | No value returned |

Tolerance: exact to the cent for totals, 0.01 percentage points for rates, exact string for
member names such as `Contoso Midtown`. Rounding to the nearest dollar is Correct. Being
out by a percent is Wrong, because that is the `Gross Sales` versus `Total Net Sales`
failure this demo exists to catch.

For F01 to F03 the pass condition is a refusal or a clarification, not a value. Score them
separately, exactly as the scorecard already does. They never contribute to `/ 15`.

Per-question classification across the `N` runs:

| Pattern | Classification | Action |
| --- | --- | --- |
| `N` of `N` correct | Stable pass | None |
| 0 of `N` correct | Stable failure | Raise defect |
| Anything between | **Flake** | Raise defect, severity high |

Flakes deserve the higher severity. A question that is right three times in five is a
model that is ambiguous rather than wrong, and it is far more damaging in front of a
business user than a consistent error, because it cannot be predicted or briefed around.

### Component 3, storage

Three Delta tables in the lakehouse. Append only, so history is preserved and drift is
measurable.

| Table | Grain | Key columns |
| --- | --- | --- |
| `eval_runs` | One row per evaluation | `run_id`, `run_ts`, `surface`, `agent_version`, `model_version`, `score`, `flake_count` |
| `eval_results` | One row per question per repetition | `run_id`, `question_id`, `attempt`, `grade`, `answer_text`, `generated_dax`, `latency_ms` |
| `eval_defects` | One row per open defect | `defect_id`, `question_id`, `first_seen_run`, `classification`, `status`, `proposed_fix`, `pr_url` |

`model_version` matters. Correlating a score drop with a model change is the entire point
of storing history, and it is what turns this from an alert into a diagnosis.

### Component 4 and 5, detection and alerting

Activator does not trigger natively on a Delta table write. Two supported routes:

| Route | When to use |
| --- | --- |
| Power BI report visual alert, over a small semantic model on `eval_runs` | Default. Simplest, and it keeps the whole loop inside Power BI |
| Eventstream into Activator | If you need sub-hourly detection or already have an event backbone |

Take the first. A demo about Power BI AI quality that monitors itself with a Power BI
alert is coherent, and it is one item rather than three.

Trigger conditions, in priority order:

| Condition | Severity | Why |
| --- | --- | --- |
| Score drops by 2 or more versus the previous run | High | Regression, usually a model change |
| Any question moves from stable pass to stable failure | High | Named, reproducible defect |
| Any question is classified flake | High | Unpredictable in front of a user |
| F01 to F03 stop refusing | High | A guardrail has been lost, worse than a wrong number |
| Score below an agreed floor, for example 13 | Medium | Absolute quality gate |
| Median latency up 50 percent | Low | Not correctness, but it is felt |

The fourth row is the one teams forget. A model that starts confidently forecasting again
has regressed harder than one that is a few dollars out, and no score threshold catches it
because F01 to F03 are outside the `/ 15`.

### Component 6, the human gate

Activator posts an Adaptive Card to the owner in Teams containing the question, the
expected value, what came back across all `N` attempts, the generated DAX, and the
proposed classification.

Three buttons:

| Response | Effect |
| --- | --- |
| Genuine defect | Proceed to classification and proposal |
| Flake, retry | Re-run that question with a larger `N`, do not open a defect yet |
| Expected, accept | Close, and record why. Baseline updated |

The third option needs to exist. Sometimes the data changes and the ground truth moves,
and a loop with no way to say "this is correct now" trains people to ignore it.

---

## 3. Error classification and fix routing

This is the part that decides whether automation is safe. The taxonomy extends the
diagnosis table already in [`docs/08-validate.md`](../docs/08-validate.md).

| Symptom | Cause | Fix target | Tier |
| --- | --- | --- | --- |
| Total a few percent high | Used `Gross Sales` not `Total Net Sales` | AI instruction, default measure | 1 |
| Year total of 4,050 | `year` summarisation set to Sum | Model metadata, `Don't summarize` | 1 |
| Confident answer for a region that does not exist | No closed value list | AI instruction listing West, Central, East | 1 |
| Returns a forecast | No statement that the model is historical | AI instruction, historical only | 1 |
| Measure ignored entirely | Not in the AI data schema | AI data schema, include it | 1 |
| Picks a similarly named column | Two columns, no descriptions | Column descriptions | 1 |
| Wrong table's `Date` column | Duplicate visible column names | Rename, hide, or exclude | 2 |
| Never uses `YTD` or `PY` | Calculation items absent from metadata | Calculation group description | 2 |
| Ranking correct, values wrong | Measure logic | DAX | 2 |
| Compares regions on totals | Different store counts per group | AI instruction plus `Net Sales per Store` | 2 |
| Correct number, poor wording | Nothing wrong with the model | Agent instructions, or a verified answer | 3 |

### Tier definitions

| Tier | Meaning | Automation |
| --- | --- | --- |
| 1 | Additive, metadata only, reversible, machine-verifiable | Bot opens a PR with the proposed diff. Human merges |
| 2 | Changes semantics or numbers | Bot opens an **issue** with the diagnosis and evidence. Human writes the fix |
| 3 | Cosmetic, or a verified answer | Human only. Never automated. See principle 1.2 |

Tier 1 is deliberately narrow. It is limited to changes that add information the model was
missing, never changes that reinterpret information it already had. Adding a description to
an undescribed column is safe. Rewriting an existing description is not, because a human
wrote it for a reason the loop cannot see.

### Never automated, under any tier

- Writing or editing verified answers.
- Deleting or hiding any model object.
- Anything touching row-level security or permissions.
- Editing DAX.
- Changing `ground_truth.py`, `generate_data.py` or the question bank. Editing the test to
  match the answer is the failure mode this whole design exists to prevent.

### The proposed fix payload

The bot writes a diff against this repo, not a live API call to the workspace. Targets:

- `semantic-model/ai-instructions.md` for instruction additions
- `semantic-model/measures.dax` descriptions for measure metadata
- A generated `semantic-model/proposed/{defect_id}.md` explaining the evidence

The PR body carries the question, the expected value, the observed distribution across `N`
attempts, the generated DAX, the tier, and the reason this fix class was chosen. A reviewer
who was not on call should be able to judge it without opening the notebook.

---

## 4. Closing the loop

A fix is not verified because it merged. It is verified because the same question, asked
the same way, now passes repeatedly.

1. Merge triggers a targeted re-run of the affected question at `N = 10`.
2. Stable pass closes the defect and records the fix in `eval_defects`.
3. Anything else reopens it and escalates to tier 2.
4. The next full scheduled run confirms nothing else regressed.

Step 4 matters. AI instructions interact. An instruction added to fix Q07 can change how
Q03 is answered, and a per-question re-run will not see it.

---

## 5. What this does not solve

Stated plainly, because a spec that claims to close the loop entirely is selling something.

- **It only knows about 15 questions.** A model can pass all 15 and be wrong about the
  sixteenth thing a user asks. The bank is a regression suite, not a proof of correctness.
- **It cannot judge wording.** Anything in tier 3 needs a human, and wording is most of
  what a business user actually experiences.
- **It has no opinion on whether the question is worth asking.** Coverage is a human
  design problem.
- **Tolerance-based comparison can mask a compensating error.** Two offsetting mistakes
  that land within tolerance grade as Correct.
- **Ground truth is only trustworthy because the data is synthetic and seeded.** Against
  real, refreshing data there is no oracle, and the whole design changes: you compare the
  agent against a reviewed DAX query rather than a fixed number.

That last point is the one to raise with anyone who wants to lift this into production.

---

## 6. Build order

Each step is useful on its own. Stop wherever the value runs out.

| Step | Delivers | Effort |
| --- | --- | --- |
| 1 | Eval notebook, results to `eval_runs` and `eval_results`, no alerting | Small. Already replaces the manual pass |
| 2 | `N` repetitions and flake classification | Small, and the highest value per hour spent |
| 3 | Eval report and Activator alert to Teams | Medium |
| 4 | Confirmation card with the three responses | Medium |
| 5 | Tier 2 issue creation with diagnosis | Medium |
| 6 | Tier 1 PR generation | Large, and the least valuable. Do it last |

Steps 1 and 2 remove the manual pass and catch nondeterminism the current process cannot
see, because a human runs each question once. Step 6 is the headline feature and the
smallest real gain, because tier 1 fixes are the ones a human already writes in about two
minutes.

---

## 7. Related

- [`docs/08-validate.md`](../docs/08-validate.md), the manual loop this automates
- [`question-bank.md`](question-bank.md), the fixed 15 plus 3
- [`scorecard.md`](scorecard.md), the manual artefact `eval_runs` replaces
- [`ground_truth.py`](ground_truth.py), the oracle, `--json` for machine use
- [`docs/07-agents.md`](../docs/07-agents.md), MCP endpoint and agent constraints
- [`docs/04-prep-for-ai.md`](../docs/04-prep-for-ai.md), where most tier 1 fixes land
