# Approving by email

The evaluation loop needs one human decision: does this proposed sentence go
into the model. Everything before it and after it is automated.

Today that decision is made with `approve.py`. This document is the last mile:
turning it into a button in Outlook, so the person approving never opens a
terminal.

## What already works without any of this

| Step | State |
| --- | --- |
| A regression raises an email | Built. The Activator rule uses `EmailMessage` |
| The dashboard shows the queue and the exact sentence | Built |
| An approval triggers the remediation within a minute | Built |
| The remediation applies, proves it landed, and is re-measured | Built |

So the loop is closed. What follows only changes **where the human clicks**,
and nothing downstream cares, because everything keys off a row in
`eval_approvals` rather than off who created it.

## The contract

An approval is one row. If your flow can write this row, it can approve.

```kusto
.set-or-append eval_approvals <| print
    approval_id  = "<a fresh guid>",
    approved_ts  = datetime(2026-01-01T09:00:00.000Z),
    question_id  = "Q10",
    instruction_target   = "semantic_model",
    proposed_instruction = "<the exact sentence, copied from the defect>",
    decision     = "approved",
    approved_by  = "person@example.com",
    note         = ""
```

Two rules that matter more than they look:

- **Copy the instruction text into the approval.** Do not reference the defect
  and read it later. A person approves a specific sentence, and the proposal
  can change on the next run. The approval is the record of what was agreed.
- **Never write `decision = "approved"` from anything unattended.** The rule
  that applies changes reacts to this row and does not re-check who created
  it. That is the whole trust boundary.

## The flow

Power Automate, five actions. The Azure Data Explorer connector talks to the
eventhouse, so no custom code is needed anywhere.

```
  Recurrence, every 15 minutes
        |
  ADX: Run query  -->  open defects awaiting approval
        |
  Condition: any rows
        |
  For each row:
        |
    Outlook: Post an adaptive card and wait for a response
        |
    Condition: response is Approve
        |
    ADX: Run control command  -->  .set-or-append eval_approvals ...
```

### 1. Trigger

Recurrence, every 15 minutes. A schedule rather than reacting to the alert
email, because the alert fires on a regression while approvals are needed
whenever a defect is open, which is not the same thing.

### 2. Query the queue

Azure Data Explorer, **Run query**. Cluster and database are the eventhouse
values in `build_dashboard.py`. Query:

```kusto
eval_defects
| summarize arg_max(run_ts, *) by question_id
| where auto_appliable == true
| join kind=leftanti (eval_approvals | distinct question_id) on question_id
| project question_id, proposed_instruction, rationale, classification
```

The anti-join is what stops the flow asking about the same defect every
fifteen minutes for the rest of its life.

### 3. Ask

Outlook, **Post an adaptive card to a user and wait for a response**. The card
body, with `@{items('Apply_to_each')?['...']}` bindings:

```json
{
  "type": "AdaptiveCard",
  "version": "1.4",
  "body": [
    { "type": "TextBlock", "size": "Medium", "weight": "Bolder",
      "text": "Data agent accuracy: approval needed" },
    { "type": "FactSet", "facts": [
        { "title": "Question", "value": "@{items('Apply_to_each')?['question_id']}" },
        { "title": "Problem", "value": "@{items('Apply_to_each')?['classification']}" }
    ]},
    { "type": "TextBlock", "wrap": true, "weight": "Bolder",
      "text": "Add this to the model AI instructions:" },
    { "type": "TextBlock", "wrap": true, "separator": true,
      "text": "@{items('Apply_to_each')?['proposed_instruction']}" },
    { "type": "TextBlock", "wrap": true, "isSubtle": true,
      "text": "Why: @{items('Apply_to_each')?['rationale']}" }
  ],
  "actions": [
    { "type": "Action.Submit", "title": "Approve",
      "data": { "decision": "approved" } },
    { "type": "Action.Submit", "title": "Reject",
      "data": { "decision": "rejected" } }
  ]
}
```

Show the sentence itself, not a summary of it. Someone approving a change to a
governed model should be reading the words that will be added.

### 4. Write the decision

Azure Data Explorer, **Run control command**, using the contract at the top of
this page. `approved_by` comes from the responder's email, which the Outlook
action returns, so the audit trail names a person rather than the flow.

### 5. Nothing

There is no step five. The existing Activator rule sees the row within a
minute and runs the remediation notebook.

## Switching to Teams instead

Two changes, both mechanical.

**The alert.** In `build_activator.py`, replace the `EmailBinding` row in the
first rule's `ActStep`. The commented block above it has the exact shape.
Teams takes `recipients` and has no `subject`; email takes `sentTo`, `copyTo`,
`bCCTo` and requires `subject`. Every other field is identical and the rule
around it does not change.

**The approval.** Swap the Outlook action for **Teams: Post an adaptive card
and wait for a response**. The card JSON is unchanged, because Adaptive Cards
are the same in both. Everything after it is unchanged too.

## What this does not do

- **Approve tier 2 defects.** The query filters on `auto_appliable`, so the
  flow never offers a defect that needs a person to open the model. `approve.py`
  refuses those as well, and both are deliberate.
- **Batch approvals.** One card per defect. A single "approve all" button on a
  list of model changes is how a governed model gets edited by somebody who
  read the first line.
- **Replace the dashboard.** The card is enough to decide a defect you already
  understand. The dashboard is where you see the pattern across runs, which is
  usually what tells you the proposal is wrong.

## Related

- [`automation-spec.md`](automation-spec.md), the design and the human gate
- [`approve.py`](approve.py), the same contract as a command
- [`build_activator.py`](build_activator.py), the alert and the apply rule
