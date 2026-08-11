# Spec: automated agent evaluation and guarded remediation

**Status:** built and running. See [What was built](#0-what-was-built).
**Scope:** pass D, the Fabric data agent. Extends to passes B and C where noted.

Before this, the accuracy loop in [`docs/08-validate.md`](../docs/08-validate.md) was
entirely manual. A human asked 15 questions, graded them by eye, and typed the result into
[`scorecard.md`](scorecard.md). Nothing was scheduled, nothing called an API, and the only
trigger was a person deciding to run a pass.

This spec describes the production version, and the repo now implements it.

---

## 0. What was built

| Artefact | Where | What it does |
| --- | --- | --- |
| [`eval_harness.py`](eval_harness.py) | repo | Pure grading, classification, fix routing and instruction merging. No Fabric imports, so all of it is unit tested on a laptop |
| [`agent_client.py`](agent_client.py) | repo | Standard library MCP client for the data agent (preview) |
| [`run_eval.py`](run_eval.py) | repo | Runs the loop from a laptop, for development and debugging |
| [`approve.py`](approve.py) | repo | The human gate. Lists the queue, approves or rejects one line at a time, and prints the approval card |
| [`approval_card.py`](approval_card.py) | repo | The approval contract: one Adaptive Card and one Kusto append command, shared by the command line and any flow |
| [`build_approval_function.py`](build_approval_function.py) | repo | Generates and deploys the approval user data function, the one surface where the approver is verified rather than typed |
| [`build_eval_notebook.py`](build_eval_notebook.py) | repo | Generates the eval notebook so the embedded copy cannot drift |
| [`build_remediation_notebook.py`](build_remediation_notebook.py) | repo | Generates the remediation notebook |
| [`build_activator.py`](build_activator.py) | repo | Creates all three Activator rules through the Fabric REST API |
| [`config.py`](config.py) | repo | Deployment values, read from the environment, with fail fast |
| [`test_no_secrets.py`](test_no_secrets.py) | repo | Proves no tenant id, hostname or address is committed |
| [`build_dashboard.py`](build_dashboard.py) | repo | Creates the real-time dashboard, and runs the load endpoint's validation rules first |
| [`build_schedule.py`](build_schedule.py) | repo | Puts the eval notebook on a daily schedule |
| [`file_issues.py`](file_issues.py) | repo | Files tier 2 defects as GitHub issues, with evidence |
| [`approval-by-email.md`](approval-by-email.md) | repo | The approval surfaces, the deployment order, and the Desktop report walkthrough |
| [`writeback-spec.md`](writeback-spec.md) | repo | The SQL writeback design, and what of it is built |
| [`build_sql_schema.py`](build_sql_schema.py) | repo | Generates `schema.sql` and creates the SQL database |
| [`publish_question_bank.py`](publish_question_bank.py) | repo | Publishes the bank from git to SQL, stamped with `bank_sha` |
| [`build_mirror_notebook.py`](build_mirror_notebook.py) | repo | Copies approvals to the eventhouse so Activator can see them, and remediations back |
| [`apply_schema.py`](apply_schema.py) | repo | Applies schema.sql and publishes the question bank over the SQL endpoint |
| [`build_agent_remediation_notebook.py`](build_agent_remediation_notebook.py) | repo | The agent instruction path, isolated from the model path |
| [`test_dashboard.py`](test_dashboard.py) | repo | Asserts the dashboard definition would load, without opening a browser |
| [`test_activator.py`](test_activator.py) | repo | Asserts each rule can fire at all, and that the approval command cannot be injected into |
| [`test_approval_function.py`](test_approval_function.py) | repo | Runs the function against a stubbed Fabric runtime, and proves the approver cannot be passed in |
| [`test_eval_harness.py`](test_eval_harness.py) | repo | Grading, routing and merge tests, including replays of real agent answers |
| [`test_notebook_drift.py`](test_notebook_drift.py) | repo | Regenerates both notebooks and executes their embedded code |
| `agent_eval` notebook | Fabric | Runs the bank, grades, writes Delta, publishes to the eventhouse |
| `agent_remediate` notebook | Fabric | Applies an approved instruction, backs up first, proves it persisted |
| `EH_AgentEval` eventhouse | Fabric | The event spine Activator can watch |
| `Agent Accuracy Alerts` | Fabric | Three rules: alert on a high severity run, chase the approval queue, and apply an approved remediation |
| `Approve remediation` | Fabric | User data function. Records a decision, with the approver read from the caller's token |
| `Agent Accuracy` dashboard | Fabric | Score, instability, alerts, and the remediation queue |

Run the tests with:

```bash
python -m unittest discover -s validation -p "test_*.py"
```

### Configuration

Nothing in this repo carries a workspace id, a Kusto hostname, a notebook id or
a recipient address. Those are tenant facts. A repo that hardcodes them leaks
its own topology into every fork, and a committed notebook that already points
at a workspace will run against it on import.

Every deployment script reads its values from the environment through
[`config.py`](config.py) and fails before doing anything if one is missing,
naming all of them at once. Copy [`.env.example`](.env.example), fill it in,
and load it.

The committed notebooks ship with empty `WORKSPACE_ID`, `DATA_AGENT_ID` and
`KUSTO_URI`, and with no lakehouse dependency metadata. Supply those when you
deploy, and attach the lakehouse in the workspace.

[`test_no_secrets.py`](test_no_secrets.py) enforces this. It scans the
committed tree for the *shape* of the things that must not be there, so a new
id pasted in next month is caught as well as the ones removed today.

### The loop, end to end

```
  agent_eval (scheduled)
        |  writes eval_runs, eval_results, eval_defects
        |  each defect carries the literal sentence to add
        v
  Activator rule 1 ---> email: a run regressed (high severity only)
  Activator rule 2 ---> email: n defects are waiting for a decision
        |
        v
  a human reads the dashboard and runs
     python validation/approve.py --question Q10 --by you@example.com
        |  writes eval_approvals
        v
  Activator rule 3 ---> runs agent_remediate
        |  appends the approved line to the model AI instructions
        |  backs up first, proves the write persisted
        v
  agent_eval again ---> did the score actually move
```

Rules 1 and 2 answer different questions and both are needed. Rule 1 is "did
this run get worse", which is a change. Rule 2 is "is anything waiting for
me", which is a state, and a state does not raise itself: a run steady at
medium severity, or a high severity email that arrived last week and was never
acted on, both look identical to silence. If the queue has rows in it and no
mail has arrived, rule 2 is the one to check.

### Where the human actually approves, today

Worth being exact about, because the diagram makes it look more finished than
it is.

| Surface | What it does today | Can you approve from it |
| --- | --- | --- |
| Email alert from Activator | Tells you a run regressed, or that the queue has n defects waiting | No. Activator's email and Teams actions send a notification, not an interactive card |
| Real-time dashboard | Shows the queue and the exact sentence per defect | No. A KQL dashboard is read only. It is where you decide, not where you act. The tile title says "approve or reject each line" because that is the decision it supports, not a control it offers |
| `approve.py` | Writes the approval row that everything else keys off | Yes, and it is the only surface that needs nothing else deployed |
| `Approve remediation` function | Same row, with the approver read from the caller's token | Yes, once deployed. Built by [`build_approval_function.py`](build_approval_function.py) |
| Power BI report button | Calls that function from next to the queue | Yes, once the button is added to the report by hand |
| Power Automate card | Not deployed here. Posts the card and calls the function or writes the row | Yes, once built. See [`approval-by-email.md`](approval-by-email.md) |

So the *trigger* is automated and the *decision* is a person. Once the approval
row exists, everything after it is hands off: Activator sees the decision
within a minute, runs the remediation, and the next evaluation says whether it
worked.

**Where the click should live.** The three surfaces differ in one way that
matters, which is whether `approved_by` is verified or asserted:

| Surface | Where `approved_by` comes from |
| --- | --- |
| `approve.py` | The `--by` argument. Whatever you type |
| Power Automate writing the row itself | A flow expression, usually the responder's email. Whatever the flow author bound |
| The user data function | `UserDataFunctionContext.executing_user`, filled by the platform from the caller's Entra token |

Only the third is evidence. That is why `approved_by` is not a parameter of
`approve_remediation` and there is a test that keeps it that way, and it is why
a flow that posts the card should call the function rather than write the row.

The function still does not apply anything. It writes the row and returns, and
Activator starts the notebook. If the function could start the notebook, anyone
who could reach the function could run a job against a governed model.

### One rough edge

`approve.py` writes the approval straight to the eventhouse. That still works,
because the remediation notebook reads the eventhouse, but the row never
reaches `dbo.approvals`, so the report will not show it and
`dbo.open_approvals` will not count it.

It is the break-glass path now, for when the report is unavailable. The report
button is the normal one, and it is also the only surface where the approver
is verified rather than typed. If the CLI becomes the normal path again, it
should be pointed at SQL.

### Three decisions worth knowing

**No `%pip install` in either notebook.** The first version installed the `mcp` package.
That pulls new builds of pydantic, anyio, typing-extensions and jsonschema over the ones
the Spark runtime ships, and the scheduled job died in twelve seconds. The MCP wire
protocol is a handful of JSON-RPC calls, so `agent_client.py` speaks it with `urllib`.

**Activator cannot watch a Delta table.** Its supported sources are Eventstream, KQL,
Real-Time Hub and Digital Twin Builder. So the notebook writes the history to Delta, which
is what you query, and publishes one summary row per run to an eventhouse, which is what
Activator watches.

**The fix goes in the model, never the agent.** Agent-level instructions are not passed to
the DAX generation step for a semantic model source. A wrong number, an unrequested
filter, or an invented region can only be fixed in the model's own AI instructions, which
live at `model.cultures[en-US].linguisticMetadata.content.CustomInstructions` and are
reached over XMLA with sempy. `getDefinition` is blocked for that item, so the definition
API is not an option. The remediation notebook refuses any instruction whose target is not
the model, precisely so that a fix cannot be applied somewhere it would look successful
and change nothing.

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

1. Approval triggers `agent_remediate`, which appends the approved line.
2. The next evaluation run re-asks every question.
3. Stable pass closes the defect and records the fix in `eval_defects`.
4. Anything else reopens it and escalates to tier 2.

Step 2 re-runs the whole bank rather than the affected question, deliberately. AI
instructions interact. A line added to fix Q10 can change how Q03 is answered, and a
per-question re-run will not see it.

### The check that stops a lie

The remediation notebook proves the write landed before it reports success, and it does so
with two independent pieces of evidence:

| Check | What it catches |
| --- | --- |
| The instruction text reads back as expected | A write that was rejected or truncated |
| The server side `lastUpdate` moved | A write that never reached the model at all |

The second one exists because of a real incident during this build. A run reported success,
recorded a remediation, and marked the approval applied, while the content read back
matched perfectly. The model had not changed. The content read back can be served from the
session's own copy of the model, so it will happily show the value you just set even when
nothing reached the server. `lastUpdate` is server side and is the only honest witness.

The same incident produced two more rules that are now enforced in code:

- **An approval is only consumed when the change is in the model.** Consuming it after a
  no-op loses the work and leaves a defect nobody is ever prompted about again.
- **An instruction that is already present also satisfies the approval.** Otherwise an
  approval applied by an earlier run, or by a person editing the model directly, sits open
  forever.

A remediation loop that reports success without changing anything is worse than no loop,
because it produces a green dashboard over a model that is still wrong. Everything above
exists to make that outcome impossible rather than unlikely.

---

## 5. What it found on its first real runs

Worth recording, because it is the argument for the whole design.

**Six questions were nondeterministic.** Q01, Q03, Q10, Q11, Q12 and F03 each answered
correctly on some attempts and not others. A manual pass asks every question once, so it
would have scored this model 14 or 15 out of 15 and moved on.

**Three of them share one defect.** Q10, Q11 and Q12 carry no time filter, so the expected
answer covers all available data. The agent sometimes silently answered for the most
recent period instead. On one run it reported December 2025 figures for Q11 as though they
were the whole picture, and the three category totals summed to exactly the December total.
That is a missing default rather than a broken measure, so it routes to tier 1.

**One "failure" was the agent falling over, not the model being wrong.** An attempt
returned "The Data Agent run failed before producing a result." Counted as a wrong answer,
it turned a healthy question into a false flake. Attempts that error are now excluded
before the model is judged, and a separate alert fires if the error rate goes above ten
percent.

**Two of the first three defects the grader reported were the grader's fault.** F02 and
F03 were graded Wrong on answers that were correct. Generic refusal detection is not
precise enough for the probes, because a good refusal often contains no refusal language:
"Northwest is not a valid region. The valid regions are Central, East and West" is the
perfect answer and contains no "cannot" anywhere. Acceptance is now driven by per-probe
rules written from the good outcome column of the question bank, and every one of those
real replies is now a regression test.

The general lesson is the one that matters when anybody builds this for real. **Validate
the grader against real answers before you trust a single score it produces.** A grader
that cries wolf on a correct answer is worse than no grader, because people stop reading
the alerts.

### What happened when a fix was actually applied

The first real pass through the full loop is worth recording honestly, because it did not
end in a clean fix.

A human approved the default time scope instruction. The remediation notebook appended it
to the model, proved the write persisted, and the next evaluation run scored 11 out of 15
against 9 before. Q08 and Q12 went from flake to stable pass, and all three guardrail
probes went to stable pass.

**Q10 got worse.** It moved from flake to stable failure. Q11 and Q04 were still flakes.

So one sentence fixed part of a defect class and not the rest, and the loop only knows
that because it re-measured. This is exactly what the verification step is for, and it is
why a merge is never recorded as a fix.

It also exposed a stuck state that is now closed. Left alone, the next run would propose
the same sentence for Q10, a human would approve it, the merge would be a no-op because
the text is already there, and the defect would never close while everyone felt busy. The
harness now reads which instructions are already in the model and escalates any defect
whose only proposal has already been tried:

> The instruction this defect would propose is already in the model and the question is
> still failing. Adding it again changes nothing.

An automated remediation loop needs a way to admit that its remedy did not work. Without
one it will keep prescribing.

---

## 6. What this does not solve

Stated plainly, because a spec that claims to close the loop entirely is selling something.

- **It only knows about 15 questions.** A model can pass all 15 and be wrong about the
  sixteenth thing a user asks. The bank is a regression suite, not a proof of correctness.
- **It cannot judge wording.** Anything in tier 3 needs a human, and wording is most of
  what a business user actually experiences.
- **It writes sentences, it does not diagnose.** The instruction library is a fixed set of
  lines written by people. The loop chooses between them from evidence; it does not
  compose new guidance, and the first live application fixed only part of the defect class
  it was aimed at.
- **It has no opinion on whether the question is worth asking.** Coverage is a human
  design problem.
- **Tolerance-based comparison can mask a compensating error.** Two offsetting mistakes
  that land within tolerance grade as Correct.
- **Ground truth is only trustworthy because the data is synthetic and seeded.** Against
  real, refreshing data there is no oracle, and the whole design changes: you compare the
  agent against a reviewed DAX query rather than a fixed number.

That last point is the one to raise with anyone who wants to lift this into production.

---

## 7. Build order and what is left

Each step is useful on its own. The first eight are built and running.

| Step | Delivers | State |
| --- | --- | --- |
| 1 | Eval notebook, results to `eval_runs` and `eval_results` | Built |
| 2 | Repetitions and flake classification | Built, highest value per hour spent |
| 3 | Eventhouse publish and Activator alert | Built |
| 4 | Errored attempts separated from model defects | Built |
| 5 | Defect classification and tiered proposals with literal text | Built |
| 6 | Real-time dashboard with the remediation queue | Built |
| 7 | Approval gate, and Activator applying an approved instruction | Built |
| 8 | Escalation when a proposed fix has already been tried | Built |
| A | One approval store, open work derived not stored | Built |
| B | Daily schedule on the eval notebook | Built |
| C | Email alerts, and the Outlook approval card specified | Built, flow not wired |
| F | Queue reminder rule, so waiting work chases itself | Built |
| G | Approval function, approver verified from the caller's token | Built, report button added by hand |
| D | Auto verification of applied remediations | Built |
| E | Tier 2 issues with per-attempt evidence | Built |

### What is genuinely left

**The Power Automate flow.** [`approval-by-email.md`](approval-by-email.md) specifies it
exactly, including the queries and the card, and the card itself is produced by
[`approval_card.py`](approval_card.py), so what a person pastes into the flow comes out of
tested code rather than out of a document. The flow still has to be created in Power
Automate by a person, because a flow cannot be deployed from this repo. Everything it
talks to already exists and is tested.

**The report button, and three portal steps.** The function, the schema, the
pipeline and both notebooks deploy from this repo. Running `schema.sql`, adding the
SQL connection to the function item, scheduling the mirror, and building the report in
Desktop are done by a person. None of them is scriptable, and the report is where the
approver's identity finally becomes evidence rather than something typed.

**Nothing else is designed and unbuilt.** The next thing worth doing is running it for a
few weeks and seeing which of the assumptions here turn out to be wrong.

### Deliberately not doing

**Automatic composition of new instruction text.** The instruction library is a fixed set
of lines written by people, and the loop chooses between them from evidence. Letting a
model write its own remediation text removes the one part of this design a reviewer can
actually check.

**Automated tier 2 fixes.** Anything that changes a number needs a person to open the
model and think.

**Batch approval.** One decision per sentence. An "approve all" button over a list of
model changes is how a governed model gets edited by somebody who read the first line.

---

## 8. Validate it yourself

Before commissioning anything further, these are the checks worth doing in this
order. Each one either passes or tells you something specific.

### On a laptop, two minutes, no capacity needed

```bash
python -m unittest discover -s validation -p "test_*.py"
python validation/ground_truth.py
```

157 tests should pass, and the ground truth should print `$412,918.50` for Q01.
If the tests pass but a number has moved, the data generator has changed and
every figure in `docs/` is now wrong.

These also check things that used to need a browser and a Spark session: the
dashboard definition would load, both notebooks match their generators, the
embedded code compiles and grades correctly, and nothing tenant specific is
committed.

### Before anything touches Fabric

```bash
cp validation/.env.example validation/.env.local   # then fill it in
python validation/build_dashboard.py               # should fail fast if unset
```

A script that runs without complaint when nothing is configured is a script
about to create items somewhere unexpected.

### In the workspace, in this order

| # | Check | Where | What good looks like |
| --- | --- | --- | --- |
| 1 | The dashboard opens | `Agent Accuracy` | Seven tiles render. No "Missing migration" modal |
| 2 | The remediation queue has rows | Same, middle tile | Each failing question with the exact sentence that would fix it |
| 3 | The schedule exists and is on | `python validation/build_schedule.py --list` | Enabled, every 1440 minutes |
| 4 | The eval notebook runs clean | `agent_eval` | Around nine minutes, ends with a score and a written run |
| 5 | The score history is growing | `eval_runs` | One row per run, `previous_score` populated after the first |
| 6 | All three activator rules are on | `Agent Accuracy Alerts` | Three rules, all started |
| 7 | The alert actually arrives | Outlook | An email naming the questions that regressed |
| 7b | The queue chases you | Outlook | After a run leaves defects undecided, a second email with `pending_count` and the question ids |
| 8 | The queue matches the last run | `python validation/approve.py --list` | Same question ids as `eval_defects` |

If the dashboard shows a queue but no mail ever arrives, the cause is almost
always one of three, in this order:

1. **The rules were created after those runs.** An Activator KQL source only
   evaluates rows whose event time falls in the window it is currently polling.
   Defects from before the rule started running are in the queue, in the
   dashboard, and permanently outside every window the rule will ever look at.
   Run `agent_eval` once and watch for mail from that run.
2. **Nothing was high severity.** Rule 1 only matches `alert_severity == "high"`,
   so a run whose worst finding is `below_floor` or `agent_errors` is medium and
   sends nothing. That is what rule 2 exists for.
3. **`AGENT_ACCURACY_RECIPIENTS` was not set when the activator was deployed.**
   The address is baked into the rule at build time, so changing the variable
   afterwards does nothing until `build_activator.py` is run again.

### The one that proves the loop, end to end

```bash
python validation/approve.py --list
python validation/approve.py --question <id> --by you@example.com
python validation/approve.py --open
```

Then watch, without touching anything:

1. Within a minute, `agent_remediate` starts on its own. Check the notebook's
   run history.
2. It finishes, and `eval_remediations` gains a row with `persisted = true`.
3. `approve.py --open` now returns nothing, because the approval is closed by
   the remediation rather than by a flag somebody set.
4. The instruction is in the model, under `## Automated remediation`.
5. Run `agent_eval` again. If the question reaches stable pass, the same run
   marks the remediation `verified = true`.

If step 1 does not happen, the approval reached the eventhouse but the rule did
not fire. If step 2 says `persisted = false`, the run could not write to the
model, and the identity it ran as is named in the error.

### Tier 2

```bash
python validation/file_issues.py --dry-run
```

Prints the issues it would file, with the grades and the answers the agent
actually gave. Drop `--dry-run` to file them.

### What a healthy failure looks like

Four of these are features, not faults, and it is worth recognising them:

- `approve.py` refusing a tier 2 defect. There is nothing safe to apply.
- A defect escalating to tier 2 with "the instruction is already in the model
  and the question is still failing". The loop is admitting its remedy did not
  work, which is the behaviour you want.
- The remediation notebook refusing with "the model changed while this run was
  preparing its edit". Two changes overlapped and it declined to overwrite one
  with the other. Re-run it; the approval is still open.
- The remediation notebook refusing with "the write did not reach the model".
  The content read back looked right but the server side `lastUpdate` did not
  move, so it was a silent no-op and is reported as a failure rather than a
  success.

---

## 9. Related

- [`approval-by-email.md`](approval-by-email.md), the Outlook approval card
- [`docs/08-validate.md`](../docs/08-validate.md), the manual loop this automates
- [`question-bank.md`](question-bank.md), the fixed 15 plus 3
- [`scorecard.md`](scorecard.md), the manual artefact `eval_runs` replaces
- [`ground_truth.py`](ground_truth.py), the oracle, `--json` for machine use
- [`docs/07-agents.md`](../docs/07-agents.md), MCP endpoint and agent constraints
- [`docs/04-prep-for-ai.md`](../docs/04-prep-for-ai.md), where most tier 1 fixes land
