# AI instructions and AI data schema for the AgentEvals model

The `AgentEvals` model reads the SQL database that holds the evaluation loop's
state. Its job is to answer "how accurate are our AI surfaces, and what are we
doing about it" — including from Copilot, which is a pleasing kind of circular:
the model that measures AI accuracy has to itself be accurate under AI.

Everything structural — names, descriptions, relationships, hidden columns,
measures — is deployed from the spec in
[`validation/build_agentevals_model.py`](../../validation/build_agentevals_model.py):

```
python validation/build_agentevals_model.py --apply
```

This file covers the three things that script cannot do, because they are
authored in the portal rather than in TMDL.

---

## What the generated model looked like before

Fabric generates a semantic model over a SQL database automatically, and what
it generates is a faithful copy of the database. That is correct and useless:

| What Fabric generated | What it costs |
| --- | --- |
| Tables called `runs`, `answers`, `defects` | Nobody asks about "runs". They ask about evaluation runs |
| snake_case columns, no descriptions | Copilot has only the name to go on, so `flake_count` is a guess |
| No relationships at all | "How did Q7 do?" is unanswerable — nothing joins `answers` to `questions` |
| Every integer set to **sum** | `SUM(runs[score])` over ten runs returns 130 out of 15, which reads as a number rather than as nonsense |
| Keys visible | A GUID is offered as something to group by, and a GUID is never an answer |
| No measures | Every question becomes an implicit aggregation, which is the failure above |

The clean-up is the same three rules as the Contoso Coffee model:

1. **Rename in the model, never in the source.** `dbo.runs` stays `dbo.runs`;
   other things write to it. The model calls it `Evaluation Runs`.
2. **Hide anything that must not be aggregated.** 32 of the 79 columns are
   hidden: every key, and every raw count that has a measure over it.
3. **Describe everything visible.** 47 columns, 7 tables and 35 measures, all
   with a description that leads with the meaning.

---

## 1. AI instructions

Paste this into the AI instructions box. As with the Contoso Coffee model, it
is deliberately about **rules that are not visible in the schema**. Restating
a column name here adds nothing.

```text
This model measures how accurate Microsoft Fabric and Power BI AI surfaces are
when answering questions about the Contoso Coffee data. It does not contain
coffee sales. A question about revenue, stores or products is about the other
model, not this one.

"Score" and "accuracy" mean Latest Score, which is the most recent run only.
Scores belong to a single run and must never be added together: a score of 13
out of 15 summed across ten runs gives 130, which is meaningless. Every
"latest" measure reports the run that Latest Run Time points at.

A question counts as passed only when every repeat of it was answered
correctly. That is why Score % is lower than Correct Attempt %: the first
credits a question, the second credits an attempt. When someone asks how
accurate the model is, use Score %.

A flake is a question answered correctly sometimes and wrongly other times. It
is worse than a steady failure, because it cannot be predicted or briefed
around before a demo. If asked what to fix first, rank flakes above failures.

Errored is not wrong. An errored attempt means the AI surface itself failed,
and those attempts are excluded from grading. A run with many errors has a
less trustworthy score rather than a lower one; say so rather than reporting
the score alone.

Two runs are only comparable when they share a Question Bank Version. If a
comparison spans more than one version, say that the question bank changed and
that the scores measure different things.

Surface has three values: the Copilot pane, the standalone Copilot experience,
and the Fabric data agent. Two surfaces are never comparable to each other; a
question about "the score" without a named surface should be answered per
surface, not pooled.

Feedback is not approval. Feedback is a report reader's opinion that an answer
looked wrong. An approval is a person agreeing to a specific sentence. Nothing
in this model lets feedback become an approval, and answers should never imply
that it does.

Approved is not applied. An approval authorises a change; Remediations Applied
counts the changes actually written; Remediations Verified counts the ones a
later run proved worked. When asked whether a problem is fixed, use
Remediations Verified. Awaiting Apply is the work queue.

Question Kind has two values. "scored" questions make up the score. "probe"
questions test whether the surface correctly refuses to answer, and they are
reported through Guardrails Lost rather than through the score. Any value of
Guardrails Lost above zero means the surface invented something it should have
declined to say, which is more serious than a wrong number.

Grade applies to one attempt and has five values: Correct, Partly correct,
Wrong, Refused, Errored. Question Outcome applies to a whole question in a
run and has four: stable_pass, stable_failure, flake, errored.

This model has no forecast and no target. If asked whether the score will
improve, say the model records what happened and does not predict.
```

### Why each line is there

| Instruction | The failure it prevents |
| --- | --- |
| This is not the sales model | "What is our revenue?" answered from a table of evaluation runs |
| Scores never sum | 130 out of 15 on a card, which looks like a number |
| Passed means every repeat | Score % and Correct Attempt % quoted interchangeably, ~10 points apart |
| Rank flakes above failures | A remediation plan that fixes the predictable things first |
| Errored is not wrong | An outage reported as a model regression |
| Bank version gates comparison | A score "improvement" that was a reworded question |
| Surfaces are not comparable | One pooled number that describes none of the three surfaces |
| Feedback is not approval | The loop appearing to change the model because somebody complained |
| Approved is not applied | "Fixed" claimed for a sentence nobody has written anywhere |
| Probes are separate | A lost guardrail buried inside a score that still looks fine |
| No forecast | A hallucinated projection of next month's accuracy |

---

## 2. AI data schema

Fewer, better fields. Select the **same tables** here and in any data agent
over this model, or the two surfaces will disagree.

**Include**

- All 35 analysis measures from [`measures.dax`](measures.dax)
- `Questions`: `Question ID`, `Question Kind`, `Question Text`, `What It Tests`
- `Evaluation Runs`: `Run Time`, `Surface`, `Question Bank Version`,
  `Alert Severity`
- `Answers`: `Grade`, `Question Outcome`, `Attempt Number`
- `Defects`: `Defect Outcome`, `Fix Tier`, `Fix Target`, `Instruction Target`,
  `Proposed Instruction`
- `Approvals`: `Decision`, `Decided By`, `Decision Time`, `Decision Source`
- `Remediations`: `Persisted`, `Verified`, `Applied Time`, `Instruction Target`
- `Feedback`: `Verdict`, `Triage Status`, `Feedback Time`

**Exclude**

- Every `*_id` column. All 32 are hidden in the model already, and a GUID is
  never an answer.
- `Evaluation Runs`: the raw counts — `Run Score`, `Run Max Score`,
  `Run Previous Score`, `Run Flake Count`, `Run Failure Count`,
  `Run Guardrails Lost Count`, `Run Errored Count`. Every one has a measure,
  and a visible numeric column is an invitation to sum it.
- `Answers`: `Answer Text`, `Grader Detail`. Long free text that Copilot will
  try to summarise into an answer rather than count.
- `Approvals` / `Feedback`: `Approver Object ID`, `Submitter Object ID`.
- `Questions`: `Bank Version`, `Published`. Version metadata, not analysis.
- `Selected Question ID`, the one measure in the **Report bindings** folder.
  It exists so the approval button can pass the selected question to the user
  data function, and it answers no business question: offered to Copilot it
  would be quoted as though it meant something.

---

## 3. Verified answers

Keep the list short. Every verified answer is a promise you have to maintain,
and **a verified answer cannot reference a hidden column**, so pin visuals
built on measures.

| Visual to pin | Trigger questions |
| --- | --- |
| `Score Headline` card with `Score Change` | `How accurate is the data agent?`, `What is our current accuracy score?`, `How did the latest evaluation run do?`, `What is the agent accuracy score right now?`, `Show me the latest score` |
| `Latest Score by Run Time`, line chart | `How has accuracy changed over time?`, `Show me the accuracy trend`, `Is the agent getting better or worse?`, `Score over time`, `What is the trend in evaluation scores?` |
| `Defects In Latest Run by Fix Tier`, bar chart | `What is broken right now?`, `Which questions are failing?`, `Show me the open defects`, `What should we fix first?`, `What did the last run find?` |

Five to seven triggers each, formal and conversational, complete questions
rather than fragments, because matching is semantic. Up to three filters per
verified answer.

**If you rename anything, reopen every verified answer that touches it and
save it again**, or it silently stops matching.

---

## 4. Approved for Copilot (preview)

Power BI service, semantic model, `Settings`, expand `Approved for Copilot`,
tick, `Apply`.

Do this last. The badge is a claim about the work, so do the work first — and
on this model in particular, the claim is checkable: run the question bank
against it.

---

## Testing checklist

- Re-run `python validation/build_agentevals_model.py --apply`. It reframes
  the model and evaluates all 35 measures; a measure that does not evaluate is
  reported by name.
- Close and reopen the Copilot pane after every save, or changes will not
  appear.
- Expand `How Copilot arrived at this` on every answer and check it used a
  measure rather than summing a column.
- Ask "what is our total score" and confirm it reports the latest run rather
  than a sum across runs. That is the single failure this model is most likely
  to produce.
