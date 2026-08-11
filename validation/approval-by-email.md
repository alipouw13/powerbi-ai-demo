# Where the approval button lives

The evaluation loop needs one human decision: does this proposed sentence go
into the model. Everything before it and after it is automated.

There are three places that decision can be made, and they are ranked here by
how close the click is to the evidence.

| Surface | The person sees | Built | Who the audit trail names |
| --- | --- | --- | --- |
| **A button in the Power BI report** | The queue and the sentence, with Approve next to it | [`build_approval_function.py`](build_approval_function.py) generates it; the report button is added by hand | The caller, verified from their token |
| **An Adaptive Card in Outlook or Teams** | One card per defect, pushed to them | Specified below, flow built by hand | Whatever the flow binds, usually the responder |
| **`approve.py`** | Whatever they query for | Built | Whatever `--by` says |

**Nothing pushes a card today.** If you are looking at a queue of defects and
an empty inbox, that is why: the Activator rules send notifications, and an
Activator email is not interactive. Fabric cannot render a button in an email.
Something has to post one.

## What already works without any of this

| Step | State |
| --- | --- |
| A regression raises an email | Built. The Activator rule uses `EmailMessage` |
| Defects left undecided raise a second email | Built. One digest per run, not one mail per defect |
| The dashboard shows the queue and the exact sentence | Built |
| An approval triggers the remediation within a minute | Built |
| The remediation applies, proves it landed, and is re-measured | Built |

So the loop is closed. Everything below only changes **where the human
clicks**, and nothing downstream cares, because everything keys off a row in
`eval_approvals` rather than off who created it.

## The contract

An approval is one row. If your surface can write this row, it can approve.

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

Do not hand-write it. [`approval_card.py`](approval_card.py) builds this
command and the card below from one place, so the flow and `approve.py` cannot
drift apart and neither can forget the escaping:

```python
from approval_card import approval_command

approval_command(
    question_id="Q10",
    instruction_target="semantic_model",
    proposed_instruction="...",
    approved_by="person@example.com",
)
```

Two rules that matter more than they look:

- **Copy the instruction text into the approval.** Do not reference the defect
  and read it later. A person approves a specific sentence, and the proposal
  can change on the next run. The approval is the record of what was agreed.
- **Never write `decision = "approved"` from anything unattended.** The rule
  that applies changes reacts to this row and does not re-check who created
  it. That is the whole trust boundary.

---

# Option 1: a button in the report

This is the one worth building. The decision happens on the same screen as the
evidence, and the approver is verified rather than declared.

It uses [translytical task flows](https://learn.microsoft.com/power-bi/create-reports/translytical-task-flow-overview),
which is a Power BI report button wired to a Fabric User Data Function.

```
  Power BI report
    input slicer: question id
    input slicer: note
    button: Approve   -->  approve_remediation(question_id, "approved", note)
    button: Reject    -->  approve_remediation(question_id, "rejected", note)
                                |
                                v
                        writes eval_approvals
                                |
                                v
              Activator: "Approved remediation, apply it"
```

## Why this is better than the flow, in one sentence

A flow builds `approved_by` from its own expression, so it is asserted; the
function reads it from `UserDataFunctionContext.executing_user`, which the
platform fills from the caller's Entra token, so it is verified. That is why
`approved_by` is **not a parameter** of `approve_remediation` and there is a
test that keeps it that way.

## Deploy it

The store is a **SQL database in Fabric**, so the deployment is now four
commands and one click. There is no Key Vault, no service principal and no
secret anywhere: earlier drafts of this page described all three, and moving
the approval store from the eventhouse to SQL deleted them.

```powershell
# 1. The database, its schema, and the question bank
python validation/build_sql_schema.py --create
python validation/apply_schema.py

# 2. The function
python validation/build_approval_function.py --deploy

# 3. The mirror, so Activator can still see approvals
python validation/build_mirror_notebook.py
#    then deploy and schedule it every minute
```

`apply_schema.py` needs `FABRIC_SQL_CONNECTION_STRING`, which is on the SQL
database item under **Settings > Connection strings**, or in the item's
`connectionString` property from the REST API. It authenticates as you, and it
is idempotent, so running it twice is a no-op.

Three things cannot be deployed from a script and are done once in the portal.

### 1. The SQL connection

Open the user data functions item, choose **Manage connections**, add a
connection to `SQLDB_AgentEval`, and check the generated alias is
**`agentevalsql`**. Rename it if it is not, because the alias is baked into
the `@udf.connection` decorator.

That is the entire authentication story. Fabric holds the credential, the
function references an alias, and the person's own identity still comes from
their token rather than from the connection.

> **Parameter names are camelCase.** Fabric refuses an underscore in a user
> data function parameter, so the function takes `questionId`, not
> `question_id`. Column names are unaffected.

### 2. The mirror schedule

Schedule the **mirror_approvals** notebook every minute. That interval is the
approval latency: about a minute for the mirror, plus about a minute for the
Activator rule, so roughly two minutes from clicking Approve to the
remediation notebook starting.

It exists because **Activator cannot watch a SQL database**. Its sources are
Power BI semantic models, KQL querysets, Real-Time Dashboards, Eventstreams,
Fabric events and Azure events. So approvals are written where the function
can reach them and copied to where the rule can see them.

It is a **Python notebook, not Spark**, and that is not a preference. It uses
`notebookutils.data.connect_to_artifact`, which does not exist in a Spark
session, and it has to start faster than its own schedule.

### 3. The report button

Full walkthrough below.

## Building the report in Desktop

The button needs a report to sit in. This is the minimum that works, and it
takes about twenty minutes.

### Before you start

The queue lives in `SQLDB_AgentEval`, so the report connects to that, not to
the `ContosoCoffee` model. Keep it as a **separate report**. The Contoso
Coffee report is the demo's subject; this one is the instrument that measures
it, and mixing them makes both harder to explain.

**Use DirectQuery**, or Direct Lake over the OneLake shortcut. Import mode
caches, so after clicking Approve the row would still show as awaiting
approval until the next refresh, and the first thing anyone does after
clicking a button is look to see whether it worked.

### 1. Connect

1. **Get data** > **SQL database** (Fabric), then pick `SQLDB_AgentEval`.
2. Select `remediation_queue`, `feedback`, `runs`, and `answers`.
3. Choose **DirectQuery**.

`dbo.remediation_queue` is a view that already does the work: one row per
question, its latest defect, the sentence, and where it has got to. The
report should not re-derive that, because then there would be two definitions
of "awaiting approval" and they would disagree eventually.

### 2. The queue table

Add a Table visual over `remediation_queue`. Its columns are already named
for display:

| Column | Shows |
| --- | --- |
| Question | The question id, which is what you type into the slicer |
| Asked | The question itself, from the published bank |
| Problem | The classification |
| Target | `semantic_model` or `data_agent` |
| Add this instruction | The exact sentence that would be applied |
| Why | The rationale |
| Status | awaiting approval, approved, applied, verified, rejected |

Filter the visual to `Status = "awaiting approval"` for the decision page, and
leave a second unfiltered table for history.

**Turn on word wrap** for the instruction column, under **Format visual** >
**Grid** > **Options**. The whole point of the tile is reading the sentence
that will be added, and truncated to one line it is decoration.

### 3. The inputs

1. **Insert** > **Text slicer**, bound to `remediation_queue[Question]`. Title
   it `Question to approve`.
2. A second **Text slicer**, not bound to a column, titled `Note (optional)`.

A text slicer rather than a dropdown is deliberate. The function validates the
question id and refuses one it cannot find, so a free text box cannot cause a
bad write, and it keeps the report from having to model the valid set.

### 4. The buttons

**Insert** > **Buttons** > **Blank**. Then in **Format button** > **Action**:

| Setting | Approve | Reject |
| --- | --- | --- |
| Action | On | On |
| Type | Data function | Data function |
| Workspace | your workspace | same |
| Function set | `Approve remediation` | same |
| Data function | `approve_remediation` | same |
| `question_id` | the question slicer | same |
| `decision` | `approved` | `rejected` |
| `note` | the note slicer | same |

Label them **Approve** and **Reject**, and put them directly under the queue
table rather than in a corner.

> If the function does not appear in the dropdown, check it returns a string.
> A data function button will not bind to a function that returns anything
> else, and it fails silently by simply not listing it.

### 5. The feedback page

A second page, and the reason the loop now has an input it never had: a person
saying an answer was wrong.

1. A text slicer for the question id.
2. A text slicer for the comment.
3. Three buttons bound to `submit_feedback`, with `verdict` fixed to `wrong`,
   `misleading` and `right`.
4. A table over `dbo.feedback` filtered to `status = 'new'`, so the triage
   queue is visible next to the thing that fills it.

**Feedback is not an approval and cannot become one.** It records that
somebody believes an answer was wrong, which is evidence a defect may exist. A
person triages it. If a click could turn an opinion into a model change, the
loop would agree with whoever complained most recently and the score would
stop measuring the model.

The name recorded is the logged-in report user, read from their token. Nobody
types it.

### 6. A button worth adding

Bind a button to `list_pending_remediations` with no parameters, labelled
**What is waiting?**. It answers the question the emails raise, from inside
the report, without a refresh.

### 7. Publish

Publish to the workspace. The button works in Desktop, but the people
approving should not need Desktop, and the alert emails should link to the
published report.

### 8. Point the alerts at it

Once the report has a URL, put it in the two alerting rules so the mail leads
somewhere useful instead of describing a command:

```python
# validation/build_activator.py, in the optionalMessage of both email rules
"Open the remediation queue: https://app.powerbi.com/groups/<ws>/reports/<id>"
```

Then re-run `python validation/build_activator.py`.

### What good looks like

1. The queue shows the failing questions with their sentences.
2. Type `Q10`, click **Approve**, and a success string comes back naming you.
3. Within about two minutes `agent_remediate` starts on its own: a minute for
   the mirror pipeline, a minute for the Activator rule.
4. Refresh: `Q10` moves to *approved, not yet applied*, then to *applied*.
5. Type `Q10` and click **Approve** again: it refuses, because there is
   already an open approval.

Step 5 is the one worth doing deliberately. A queue that lets you approve the
same change twice will eventually be asked to.



`list_pending_remediations` returns the queue as text, and
`approve_remediation` returns either

> Approved Q10 as alison@example.com. The remediation runs within a minute and
> the next evaluation says whether it worked. Approval 8faf82f2-...

or a refusal that explains itself, such as *"Q07 is tier 2 and has no
automatically appliable fix. It needs a person in the model."* Those refusals
are `UserThrownError`, which Power BI renders to the user instead of a 500.

## What it deliberately does not do

- **Apply anything.** It writes the approval row and returns. The Activator
  rule starts the notebook. If the function could start the notebook, anyone
  who could reach the function could run a job against a governed model, and
  there is a test asserting the function contains no such call.
- **Expose a public endpoint.** `isPublicEndpointEnabled` is false on both
  functions. Every caller in this design already holds an Entra token.
- **Approve tier 2.** Same refusal as `approve.py`, for the same reason.

---

# Option 2: an Adaptive Card in Outlook or Teams

Use this when the approver should be interrupted rather than asked to open a
report. The card is posted by Power Automate, because Activator cannot post an
interactive one.

## The flow

Power Automate, five actions. The Azure Data Explorer connector talks to the
eventhouse, so no custom code is needed anywhere.

If you already built option 1, replace the last action with **Fabric: invoke a
user data function** instead of writing the row yourself. You get the verified
approver and the tier checks for free, and the flow stops being trusted with
anything except delivering the card.

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
| project question_id, proposed_instruction, instruction_target, rationale,
          classification
```

The anti-join is what stops the flow asking about the same defect every
fifteen minutes for the rest of its life.

This is the same set the "Remediation queue waiting for approval" Activator
rule counts, minus the tier 2 defects it also counts. That rule is the reason
the queue is not silent while you are deciding whether to build this flow: it
emails a digest whenever a run leaves defects nobody has decided on.

### 3. Ask

Outlook, **Post an adaptive card to a user and wait for a response**. Get the
card body from the repo rather than copying it out of this page, so it stays
the card the tests cover:

```powershell
python validation/approve.py --card                 # the flow template
python validation/approve.py --card --question Q10  # rendered, to read first
```

The template it prints, with `@{items('Apply_to_each')?['...']}` bindings
already in place:

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
      "text": "Why: @{items('Apply_to_each')?['rationale']}" },
    { "type": "Input.Text", "id": "note", "isMultiline": true,
      "placeholder": "Optional note, recorded with the decision" }
  ],
  "actions": [
    { "type": "Action.Submit", "title": "Approve", "style": "positive",
      "data": { "decision": "approved",
                "question_id": "@{items('Apply_to_each')?['question_id']}" } },
    { "type": "Action.Submit", "title": "Reject", "style": "destructive",
      "data": { "decision": "rejected",
                "question_id": "@{items('Apply_to_each')?['question_id']}" } }
  ]
}
```

Show the sentence itself, not a summary of it. Someone approving a change to a
governed model should be reading the words that will be added.

### 4. Write the decision

Azure Data Explorer, **Run control command**, using the contract at the top of
this page. Bind the fields like this:

| Field | Value in the flow |
| --- | --- |
| `question_id` | `@{items('Apply_to_each')?['question_id']}` |
| `proposed_instruction` | `@{items('Apply_to_each')?['proposed_instruction']}`, the copy the card displayed |
| `instruction_target` | `@{items('Apply_to_each')?['instruction_target']}` |
| `decision` | `@{body('Post_an_adaptive_card')?['decision']}`, from the button |
| `approved_by` | `@{body('Post_an_adaptive_card')?['responder']?['email']}` |
| `note` | `@{body('Post_an_adaptive_card')?['note']}` |
| `approval_id` | `@{guid()}` |

`approved_by` comes from the responder's email, which the Outlook action
returns, so the audit trail names a person rather than the flow.

Escape `proposed_instruction` and `note` before they go into the command. A
sentence that contains a double quote will otherwise end the Kusto string
literal early, which is a broken command on a good day and an injection on a
bad one. `approval_command` in [`approval_card.py`](approval_card.py) does this,
and there is a test for exactly this case.

### 5. Nothing

There is no step five. The existing Activator rule sees the row within a
minute and runs the remediation notebook.

## Which notebook runs, and for which question

The card's Approve does not start the notebook. It writes a row, and the
"Approved remediation, apply it" rule starts the notebook. That indirection is
the point: the flow is not trusted to run anything, only to record a decision.

The rule passes `QUESTION_ID = ""`, which means "every approved and unapplied
row". Approving three cards in a minute is therefore one notebook run that
applies all three, rather than three runs racing each other for the same
semantic model. The notebook reads the approvals itself, and each one is
consumed only when a remediation row referencing its `approval_id` is persisted,
so nothing is applied twice and nothing is silently skipped.

If you want the run scoped to one question instead, pass that question id as the
`QUESTION_ID` parameter on the rule. It is a supported parameter on the notebook,
but the default is deliberate, and per-question runs will collide if two
approvals land together.

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

---

# Option 3: the command line

`python validation/approve.py --question Q10 --by you@example.com`. It writes
the same row, using the same builder, and it is the right surface for someone
who is already in a terminal looking at the queue. It is the weakest of the
three on provenance, because `--by` is whatever you type.

---

## Choosing

| If | Build |
| --- | --- |
| The approver already opens the report | Option 1. Nothing else to install |
| The approver needs to be interrupted | Option 2, calling option 1's function from the last step |
| Only engineers approve, for now | Option 3, which already works |
| You need the audit trail to survive a challenge | Option 1, because it is the only one where the approver is verified rather than typed |

## Related

- [`automation-spec.md`](automation-spec.md), the design and the human gate
- [`writeback-spec.md`](writeback-spec.md), the proposal to move this into a
  SQL database and delete the Key Vault connection
- [`build_approval_function.py`](build_approval_function.py), the function
  behind the report button, and why it needs a Key Vault connection
- [`approve.py`](approve.py), the same contract as a command
- [`approval_card.py`](approval_card.py), the card and the command, in one place
- [`build_activator.py`](build_activator.py), the alert, the queue reminder, and
  the apply rule
