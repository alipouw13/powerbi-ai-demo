# Phase 6. Get insights as a business user

**Agent:** `insights-analyst`
**Time:** 15 minutes
**AI on show:** Copilot pane (GA), standalone Copilot in Power BI (preview)

Now be the person the whole rest of the demo exists to serve. You know nothing about the
model. Behave accordingly.

---

## Two surfaces, and the difference matters

**Copilot pane in a report. Generally available.**
Scoped to the report that is open. Summarises a page, explains a visual, answers
questions about the data behind the report. In the service and in Desktop.

**Standalone Copilot in Power BI. Preview.**
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

If standalone Copilot answers from a semantic model that is **not** marked
`Approved for Copilot`, it shows a banner saying answer quality could be low, and the
user has to select `View answer` to see it. Once the model is approved, no banner.

If you can, show it both ways. Ask a question before you approve the model, then approve
it and ask again.

An admin can go further with `Only show approved items in the standalone Copilot in
Power BI experience`, in which case unapproved content never appears at all.

---

## Run the question bank

Ask all 15 questions in
[`validation/question-bank.md`](../validation/question-bank.md), **exactly as written**,
in both surfaces. Record the results as pass C in
[`validation/scorecard.md`](../validation/scorecard.md).

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

---

## Read the answer properly

Every answer has a **How Copilot arrived at this** section. Expand it. It lists the
fields, measures, and filters Copilot chose from the semantic model.

When an answer is wrong, this tells you exactly which piece of metadata misled it. That
is your diagnosis, and it is what you hand back to phase 3 or phase 4.

If an answer has no such section, it came from the model's general knowledge rather than
your semantic model. For a data question, treat that as a red flag.

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
