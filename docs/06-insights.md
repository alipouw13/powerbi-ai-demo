# Phase 6. Get insights as a business user

**Agent:** `insights-analyst`
**Time:** 15 minutes
**AI on show:** Copilot pane (GA), standalone Copilot in Power BI (preview)

Now be the person the whole rest of the demo exists to serve. You know nothing about the
model. Behave accordingly.

**Start here after phase 5**, with the report published to the workspace and its visuals
checked against ground truth. On the short path, where phase 5 is skipped, use
`Auto-create report` on the `ContosoCoffee` model to get a report page to work against.

Two different jobs happen in this phase. **Scoring** the model against the question bank,
which is below. And **using** it the way a business user would, which is the
[business prompt library](../.github/prompts/business-prompt-library.md): persona prompt
sets, a six-prompt leadership readout, and how to get the most out of verified answers and
the visuals already on the page.

---

## What must be true before a business user gets a good answer

The prompt is the last five percent. Almost every bad answer traces back to this table
rather than to the wording of the question.

| Prerequisite | What the user sees when it is missing | Set in |
| --- | --- | --- |
| Paid F2 or higher, or P1 or higher with Fabric on | No Copilot button at all | [phase 0](00-setup.md) |
| Business-friendly names, relationships, marked date table | Answers that use names nobody recognises, or refuse anything time based | [phase 3](03-model.md) |
| A description on every measure, meaning first | The wrong measure out of 20 | [phase 3](03-model.md) |
| AI instructions | Revenue, best and profitable resolve to the wrong thing | [phase 4](04-prep-for-ai.md) |
| AI data schema | A raw column instead of a curated measure | [phase 4](04-prep-for-ai.md) |
| Verified answers | A freshly generated query instead of the visual leadership signed off | [phase 4](04-prep-for-ai.md) |
| `Approved for Copilot` (preview) | A low-quality warning banner before any answer | [phase 4](04-prep-for-ai.md) |
| Q&A enabled on the model | Nothing in Prep data for AI takes effect | [phase 4](04-prep-for-ai.md) |
| Descriptive visual titles | Weaker grounding, especially for the phase 7 agent | [phase 5](05-report.md) |

Five minute readiness check: open the Copilot pane, ask `What is our total net revenue?`
and confirm `$412,918.50`, ask `Show me net revenue by region.` and confirm you get the
pinned visual back rather than a new table, then ask `Show me sales for the Northwest
region.` and confirm it refuses instead of substituting West.

---

## Two surfaces, and the difference matters

**Copilot pane in a report. Generally available.**
Scoped to the report that is open. Summarises a page, explains a visual, answers
questions about the data behind the report. In the service and in Desktop.

**Standalone Copilot in Power BI (preview).**
Full screen, across items. It searches the reports, semantic models, and Fabric data
agents you have access to, then picks what to answer from. Reached from the Copilot icon
in the left navigation of the Power BI service, or from Power BI Home. Also in the mobile
apps, in preview.

The tenant setting `Users can access a standalone, cross-item Power BI Copilot
experience (preview)` has been on by default since September 2025, but check it if the
icon is missing.

---

## The friction treatment

This is the clearest way to show why phase 4 exists.

If standalone Copilot (preview) answers from a semantic model that is **not** marked
`Approved for Copilot` (preview), it shows a banner saying answer quality could be low, and the
user has to select `View answer` to see it. Once the model is approved, no banner.

If you can, show it both ways. Ask a question before you approve the model, then approve
it and ask again.

An admin can go further with `Only show approved items in the standalone Copilot in
Power BI experience` (preview), in which case unapproved content never appears at all.

---

## Run the question bank

Ask all 15 questions in
[`validation/question-bank.md`](../validation/question-bank.md), **exactly as written**.
Use the report Copilot pane if you still need pass B. Use standalone Copilot (preview) for
pass C, then record the results in [`validation/scorecard.md`](../validation/scorecard.md).

Do not reword a question to get a better answer. A reworded question is a hidden failure,
and the failures are the interesting part.

Then ask the three that are designed to fail:

```text
What will revenue be next quarter?
```

```text
Which store is most profitable?
```

```text
Show me sales for the Northwest region.
```

Before phase 4 these usually fail badly. F01 invents a projection. F02 silently picks one
interpretation. F03 quietly substitutes West. After phase 4 they should behave, because
the AI instructions cover exactly those three cases.

Your end-of-phase check is complete when pass C has 15 scored answers and the three failure
questions have notes in the scorecard.

---

## Read the answer properly

Every answer has a **How Copilot arrived at this** section. Expand it. It lists the
fields, measures, and filters Copilot chose from the semantic model.

When an answer is wrong, this tells you exactly which piece of metadata misled it. That
is your diagnosis, and it is what you hand back to phase 3 or phase 4.

If an answer has no such section, it came from the model's general knowledge rather than
your semantic model. For a data question, treat that as a red flag.

---

## Ask like a business user, not like a tester

The question bank is deliberately mechanical. Real users are not. A prompt that produces a
number somebody will act on has five parts, and dropping any one of them is how you get a
number you cannot defend.

| Part | Fragment | What goes wrong without it |
| --- | --- | --- |
| Role or lens | `Act as a retail CFO` | A generic answer with no point of view |
| Scope | `for the Beverage category` | You get a grand total |
| Measure | `by gross margin, in dollars` | It picks the wrong one out of 20 |
| Period | `for 2025` | Time intelligence compares two years against one |
| Output shape | `as a table, top 5` | Prose you have to re-ask for |

The single highest-value habit to teach: end every prompt with `state the period and any
filter you applied`. It converts an undefendable number into a defendable one.

**The prompt to run live.** This one makes Copilot set the agenda from the model it can
actually see, rather than answering a question you already knew the answer to.

```text
Act as a retail executive preparing a leadership readout from this report. Based only on
the data in this semantic model, tell me the ten questions I should ask you to get the
most insight, ranked by how much they would change a decision. For each, say in one line
what the answer would let me do. Do not answer them yet.
```

Then pick three of what it proposes and ask them.

Full persona sets for the executive, finance and margin owner, store operations,
merchandising, channel and marketing, and the analyst who has to defend the number, each
with expected values and the specific trap that persona falls into, are in the
[business prompt library](../.github/prompts/business-prompt-library.md). The six-prompt
leadership readout chain in section 7 of that file is the strongest four minutes in the
whole demo.

---

## Work the visuals, not just the chat box

The chat box is the least governed way to ask a question. The visuals on the page have
already been reviewed. There are three ways to make AI use them.

**Verified answers, the highest-trust path.** A verified answer pins a reviewed visual to a
set of trigger phrases. When a question matches, Copilot returns **that visual**, not a
generated query. It is the only mechanism here where a human pre-approved the exact output.
Three are pinned in phase 5: `Total Net Sales by Region`, `Total Net Sales by Year-Month`
and `Net Sales by Category`.

Show it working, then show it missing:

```text
Show me net revenue by region.
```

```text
Break net revenue down by region and then by store type.
```

The first returns the pinned visual. The second does not match a trigger, so Copilot
generates a query instead. That contrast is the whole point of verified answers in one
pair of prompts. Pin the two or three visuals leadership already quotes and no more, since
every verified answer is a maintenance promise when the model changes.

**Ask about the visual on screen.** In read mode these anchor the answer to something
somebody already validated:

```text
Explain what this visual is telling me in plain language, and name the measure it uses.
```

```text
Summarise this page for someone who has thirty seconds.
```

```text
Suggest three follow-up questions this page raises that I cannot answer from it.
```

That last one is the natural handoff to standalone Copilot (preview) and to the phase 7
data agent.

**The classic `Analyze` options on a data point**, such as explaining an increase or a
decrease, are a separate statistical feature rather than a Copilot one. Worth showing next
to the Copilot answers, because the two together are more convincing than either alone.

---

## Also worth showing

- **Copilot summaries in email subscriptions.** Available on standard subscriptions in
  the service. It is the least flashy feature here and often the one people actually
  adopt.
- **The narrative visual** on the report page from phase 5. Same summarisation, pinned to
  the page, so it refreshes with the data.
- **Ask a question a report cannot answer.** Standalone Copilot will look across your
  other items. That is the difference between the two surfaces, in one prompt.

---

## Say this out loud

AI is nondeterministic. The same question can come back worded differently, and
occasionally with a different answer. Judge the number, not the sentence. If a result
surprises you, ask again before you conclude anything.

---

Docs:
- https://learn.microsoft.com/power-bi/create-reports/copilot-ask-data-question
- https://learn.microsoft.com/power-bi/explore-reports/copilot-chat-with-data-standalone
- https://learn.microsoft.com/power-bi/create-reports/copilot-reports-overview

Next: [phase 7, agents](07-agents.md)
