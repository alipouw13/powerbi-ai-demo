# Spec: moving the loop's state into Fabric

**Status:** phases 1, 3 and 4 are **built**. Phase 2 is the report, which is a
manual Desktop task documented in
[`approval-by-email.md`](approval-by-email.md). Phase 5 is not started.

Decisions taken since this was written:

| Question | Answer |
| --- | --- |
| Who may approve | Admin, alerts to the existing `AGENT_ACCURACY_RECIPIENTS` address |
| Is feedback anonymous | No. The name is the logged-in report user, read from their token |
| Does the agent-instruction path matter | Yes, built as a narrow, guarded path |
| Is two minutes acceptable | Yes. Option A, the pipeline mirror |

The proposal was to stop keeping the loop's state in a mix of markdown, Delta
and an eventhouse, and put the operational parts in a SQL database in Fabric,
so that a Power BI report can read it and a user data function can write to it.
Approvals and feedback then happen in the report, and the loop reacts.

Most of this was right and is now built. Two parts did not work as described,
one for a hard platform reason and one because it would have removed the thing
that makes the score trustworthy. Both were resolved in ways that keep the
intent.

---

## 1. What the proposal gets right

**The Key Vault connection disappears.** This is the strongest argument for
the whole change, and it is worth stating first because it is also the answer
to "what is the KV connection".

Today the approval function needs one because a user data function has managed
connections to **SQL databases in Fabric, warehouses, lakehouses and mirrored
databases**, and an eventhouse is not on that list. `eval_approvals` lives in
the eventhouse, because that is the only thing Activator can watch. So the
function has to authenticate to Kusto itself:

```
UDF  --generic connection, audience KeyVault-->  Azure Key Vault
     <--service principal client secret--
UDF  --client_credentials-->  Entra  --token-->  Kusto
```

That is three moving parts, a secret, and a service principal that needs
ingest rights, all to work around one missing connector. Move the approval
store to a SQL database and the function uses `@udf.connection` with a managed
connection, and **all of it goes away**: no vault, no secret, no principal, no
`APPROVAL_*` variables in `config.py`.

**The report becomes the place decisions happen.** A KQL dashboard is read
only. A Power BI report with a data function button is not, and the evidence
and the button end up on the same screen, which is where they belong.

**Joins get easy.** Right now a question is a row in a markdown table, its
answers are in Delta, its defects are in an eventhouse and its approval is in a
third place. One database makes "show me every answer this question has ever
given, and every fix anyone proposed for it" a query rather than a project.

---

## 2. What does not work as described

### 2.1 Activator cannot watch a SQL database

> "have a trigger when a new item is populated in the sql db approving the
> update and when triggered a notebook runs"

Activator's sources are:

| Kind | Sources |
| --- | --- |
| Query | Power BI semantic models, KQL Querysets, Real-Time Dashboards |
| Streaming | Eventstreams, Fabric events, Azure events |

A SQL database in Fabric is not one of them. This is the same constraint
`automation-spec.md` already records for Delta tables, and it is why the
eventhouse exists in this design at all.

Three ways to keep the intent. All of them end at the same rule that already
works, so nothing downstream changes:

| Option | How the notebook gets triggered | Latency | Cost |
| --- | --- | --- | --- |
| **A. Pipeline mirror** | A Data Factory pipeline copies new approvals from SQL to the eventhouse on a schedule; the existing rule fires | ~1 min mirror + ~1 min rule | One pipeline. **No secrets anywhere** |
| **B. Dual write** | The function writes SQL, then the eventhouse | ~1 min | Keeps Key Vault, and has a partial-failure case |
| **C. Fabric/OneLake event** | An event on the mirrored table triggers the rule directly | Unmeasured | No mirror at all, but the least proven |
| **D. Power BI source** | Activator watches a measure on the Direct Lake model | Default hourly | Simplest, far too slow |

**Recommend A.** It is the only one that removes the Key Vault connection
completely, which was the point of moving to SQL. Two minutes from click to
notebook start is not meaningfully worse than the ~one minute today, and
nobody is watching a stopwatch during an approval.

If B is chosen instead, the write order matters and is not arbitrary: **SQL
first, eventhouse second**. If the eventhouse write fails you have a recorded
decision that did not fire, which a sweeper can retry. Reverse the order and a
failure leaves a change applied with no record of who approved it.

C is worth trying once the rest is running, because it removes the mirror. It
fires on file change rather than on row, which is fine here: the rule already
passes `QUESTION_ID = ""` and the notebook processes every approved and
unapplied row, so it does not need to know which one landed.

### 2.2 The question bank should not be authored in SQL

> "instead of a md file for the questions"

The bank is the measuring instrument. The repo's first rule is *ask the
questions exactly as written; a reworded question is a hidden failure*, and
`question-bank.md` is in version control so that rewording one is a diff
somebody reviews.

Put the bank in a mutable table and a question can be softened by anyone with
write access, the score goes up, and nothing anywhere records that the
instrument changed. That is the one failure this whole loop exists to prevent,
and it would be self-inflicted.

**The fix keeps both.** Git authors, SQL publishes:

```
validation/question-bank.md   (source of truth, reviewed in PRs)
        |
        |  python validation/publish_question_bank.py
        v
dbo.questions  (bank_sha stamped on every row)
        |
        +--> joins, report display, feedback foreign keys
```

Every run records the `bank_sha` it ran against. Two runs with different
hashes are not comparable, and the report can say so instead of drawing a
misleading trend line. Direct edits to `dbo.questions` are overwritten by the
next publish, and a check reports the divergence rather than silently losing it.

This gets every benefit the proposal wanted — joins, report display, no
markdown parsing at query time — and gives up nothing.

### 2.3 "Update the data agent or the semantic model" is not a choice of two equals

The repo already has `instruction_target` for this, and the remediation
notebook deliberately **refuses** anything that is not the semantic model. The
reason is in its header: agent-level instructions are not passed to the DAX
generation step, so they shape the reply after the query has run. A wrong
number, an unrequested filter or an invented region can only be fixed in the
model's own AI instructions. Writing it in the agent instruction box feels
productive and changes nothing.

So the agent path is real but narrow: tone, framing, when to refuse, how to
present a caveat. It is not a branch of the same decision.

**Keep the refusal.** Add the agent path as a separate target with its own
guard: an agent-targeted remediation may never be proposed for a defect whose
evidence is a wrong value. If the loop ever proposes one, that is a routing
bug, and it should fail rather than write.

---

## 3. The design

### 3.1 Where everything lives

| Store | Holds | Why there |
| --- | --- | --- |
| **Git** | Question bank, ground truth, harness, all generated artifacts | Reviewable. The instrument must not be editable at runtime |
| **SQL database in Fabric** | questions, runs, answers, defects, feedback, approvals, remediations | Managed UDF connection, mirrors to OneLake for Direct Lake, relational joins |
| **Eventhouse** | An append-only copy of approvals, and run summaries | The only thing Activator can watch |
| **Lakehouse** | Raw per-attempt evidence, model backups | Cheap, and nobody queries it interactively |

The eventhouse stops being the approval store and becomes only the event
spine. That resolves the "one rough edge" `automation-spec.md` already flags,
in the direction it suggested.

### 3.2 Schema

```sql
-- Published from git. Never edited here.
questions(
  question_id      varchar(8)  primary key,
  kind             varchar(16) not null,      -- 'scored' | 'probe'
  prompt           nvarchar(500) not null,
  tests            nvarchar(500),
  good_outcome     nvarchar(500),             -- probes only
  bank_sha         char(40) not null,
  published_ts     datetime2 not null
)

runs(
  run_id           uniqueidentifier primary key,
  run_ts           datetime2 not null,
  surface          varchar(64) not null,
  bank_sha         char(40) not null,         -- which instrument this used
  score            int not null,
  max_score        int not null,
  previous_score   int null,
  flake_count      int not null,
  failure_count    int not null,
  guardrails_lost_count int not null,
  alert_severity   varchar(16) not null
)

answers(
  run_id           uniqueidentifier not null references runs(run_id),
  question_id      varchar(8) not null references questions(question_id),
  attempt          int not null,
  grade            varchar(16) not null,
  classification   varchar(16) not null,
  latency_ms       int not null,
  answer           nvarchar(max),
  primary key (run_id, question_id, attempt)
)

defects(
  run_id           uniqueidentifier not null references runs(run_id),
  question_id      varchar(8) not null references questions(question_id),
  classification   varchar(32) not null,
  tier             int not null,
  instruction_target varchar(32) not null,    -- 'semantic_model' | 'data_agent'
  proposed_instruction nvarchar(max),
  rationale        nvarchar(max),
  auto_appliable   bit not null,
  primary key (run_id, question_id)
)

-- New. A person saying an answer was wrong. Never an approval.
feedback(
  feedback_id      uniqueidentifier primary key,
  created_ts       datetime2 not null,
  created_by       nvarchar(256) not null,    -- from the caller's token
  run_id           uniqueidentifier null references runs(run_id),
  question_id      varchar(8) not null references questions(question_id),
  verdict          varchar(16) not null,      -- 'wrong' | 'misleading' | 'right'
  comment          nvarchar(max) not null,
  status           varchar(24) not null       -- 'new' | 'triaged' | 'dismissed'
)

approvals(
  approval_id      uniqueidentifier primary key,
  approved_ts      datetime2 not null,
  question_id      varchar(8) not null references questions(question_id),
  instruction_target varchar(32) not null,
  proposed_instruction nvarchar(max) not null,  -- the copy, not a pointer
  decision         varchar(16) not null,
  approved_by      nvarchar(256) not null,      -- from the caller's token
  approver_oid     varchar(64) not null,
  source           varchar(16) not null,        -- 'report' | 'card' | 'cli'
  note             nvarchar(max),
  covered_by       uniqueidentifier null,       -- the approval that carries the change
  mirrored_ts      datetime2 null               -- set by the pipeline
)

remediations(
  remediation_id   uniqueidentifier primary key,
  recorded_ts      datetime2 not null,
  applied_ts       datetime2 null,              -- null means nothing was written
  approval_id      uniqueidentifier not null references approvals(approval_id),
  question_id      varchar(8) not null references questions(question_id),
  instruction      nvarchar(max) not null,
  applied_by       nvarchar(256) not null,
  persisted        bit not null,
  verified         bit not null,
  verified_run_id  uniqueidentifier null
)
```

Three things carried over deliberately:

- **`approvals.proposed_instruction` is still a copy.** A foreign key to
  `defects` would be tidier and would mean the applied text could change after
  it was approved. A person approves a sentence.
- **"Open" is still derived**, now as a `left join ... where r.approval_id is
  null` instead of a Kusto anti-join. Same rule, one definition, in a view:
- **`applied_ts` is still nullable, and now that null means something.**
  `persisted` with a time is "this run wrote it". `persisted` with no time is
  "this approval is satisfied and nothing was written", either because the
  sentence was already there or because another approval carries it. Adding a
  status column instead would have meant migrating an append-only eventhouse
  table that four writers share, to record something the schema could already
  express.

```sql
create view open_approvals as
select a.* from approvals a
left join remediations r
  on r.approval_id = a.approval_id and r.persisted = 1
where a.decision = 'approved' and r.approval_id is null;
```

`mirrored_ts` is the one concession to option A: the pipeline stamps it, so an
approval that never reached the eventhouse is a query rather than a mystery.

### 3.3 The flow

```
  agent_eval (scheduled)
        |  writes runs, answers, defects to SQL
        v
  SQL database  --auto-mirror-->  OneLake  --shortcut-->  Direct Lake model
        |                                                        |
        |                                                        v
        |                                            Power BI report
        |                                              - the queue
        |                                              - the sentence
        |                                              - [Approve] [Reject]
        |                                              - [Send feedback]
        |                                                        |
        |                                                        v
        |                                          UDF (managed connection)
        |                                            approver from token
        |                                                        |
        |<-------------------- writes approvals / feedback ------+
        |
        v
  pipeline, every minute: new approvals --> eventhouse
        |
        v
  Activator "Approved remediation, apply it"
        |
        v
  agent_remediate --> semantic model (or, narrowly, the agent)
        |
        v
  next agent_eval --> verified, or escalated to tier 2
```

Activator's alerting rules stay where they are and keep their job: tell
somebody a run regressed, and chase a queue nobody has emptied. The one change
is that the email now links to the report rather than telling the reader to
run a command, which is the "activators would bring the user to the Power BI
report" part of the proposal, and it is a one-line change to the rule body.

### 3.4 What must not change

These are the properties the current design has, and any version of this that
loses one of them is worse than what exists today.

1. **The approver is read from the caller's token**, never passed in.
2. **Recording and acting are separate.** The function writes a row. Activator
   starts the notebook. A function that could start a notebook would let
   anyone who can call it run a job against a governed model.
3. **Feedback is not an approval.** It creates a candidate for triage. If a
   person could turn their own opinion into a model change in one click, the
   loop would agree with whoever complained most recently.
4. **Nothing writes a verified answer, ever.** That is how a loop raises its
   own score.
5. **Tier 2 is refused, not approximated.**
6. **The instrument is versioned.** Every run records `bank_sha`.
7. **Applied means applied.** A remediation is only recorded as a change when
   the text can be read back from the thing that was supposed to change: the
   server-side `lastUpdate` for a semantic model, the **published**
   configuration for a data agent. Anything else lets the report show a fix
   that never happened, which is worse than showing none.

### 3.5 One sentence, several questions

The harness proposes from a small library, so one wrong behaviour usually
appears as the same sentence against four or five questions at once. They are
one decision, and the model or the agent should get one line.

`approve_similar` records the decision for every question in the group. The
extra rows carry `covered_by`, naming the approval that makes the change, and
each one gets a remediation row with `persisted = 1` and **no** `applied_ts`.
That closes the approval, so nothing queues a second identical write, while
keeping a real decision against every question.

`applied_ts` is doing real work here and it is worth being explicit about it.
`persisted` with a time means "this run wrote the sentence". `persisted` with
no time means "this approval is satisfied and nothing was written", which
happens two ways: the sentence was already there, or another approval carries
it. Both are correct outcomes and neither is a fix, so the report counts them
as `Already Present` rather than as `Instructions Written`.

The mirror gained a third leg for this. Approvals go SQL to eventhouse and
remediations come back, but these closing rows are written in SQL by the
function and have to reach the eventhouse too, or the leftanti join the
remediation notebook uses to find open work would treat all four questions as
outstanding. They are copied out **before** the approvals leg, so a covered
approval can never reach the eventhouse ahead of the row that closes it.

### 3.6 Staging is not the agent

An instruction applied to a data agent goes to its **staging** configuration.
Staging is a draft. The MCP endpoint answers from the published configuration,
and so does anybody looking at the agent, and staging only becomes published
when something calls the publish endpoint.

The first version of the agent path did not, and mixed two APIs while it was
at it: the write PATCHes `aiInstructions` on staging through the public API,
while the deprecated `get_configuration` reads `additionalInstructions`
from the workload host. So the notebook wrote a draft, read a different field
back, decided the write had not landed, and raised. Its caller caught the
exception and printed one line among fifty.

Two approvals sat applied-but-absent for days, and every surface said the loop
was healthy. The fixes are in three places, and all three matter:

* the agent path uses one plane end to end and publishes,
* it verifies against the **published** configuration before recording
  anything,
* a failed handoff is printed as a banner rather than a line, because a quiet
  failure here is indistinguishable from success.

The four calls, all on `/v1/workspaces/{ws}/dataAgents/{id}`:

| Step | Call |
| --- | --- |
| Read the draft | `GET /staging/settings` |
| Write the draft | `PATCH /staging/settings` with `{"aiInstructions": ...}` |
| Publish it | `POST /staging/publish` with `{"publishedDescription": ...}` |
| Verify | `GET /settings` |

`publishedDescription`, not `description`. The endpoint accepts both and
silently ignores the latter, so a publish can look recorded and carry no note.

There is deliberately no SDK here. `fabric-data-agent-sdk` makes these same
calls, and installing it at run time cancelled the notebook's Spark session in
ten seconds on the first agent-targeted approval that ever reached it, before
a line of its own code ran.

---

## 4. Phases

Each phase is independently useful and leaves the loop working. Nothing here
requires a big-bang cutover, because the eventhouse stays in the picture the
whole way.

| Phase | Delivers | Removes |
| --- | --- | --- |
| **1. SQL as the read store** | The database, the schema, the publish script, dual writes from the eval notebook | Nothing yet |
| **2. The report** | Direct Lake model, queue page, the buttons | The dashboard as the place you go to decide |
| **3. Writeback** | UDF on a managed connection, pipeline mirror | **Key Vault, the service principal, three env vars** |
| **4. Feedback** | The feedback table, the report page, triage into defect candidates | Nothing. This is new capability |
| **5. Retire the duplicates** | Eventhouse holds only run summaries and mirrored approvals | Delta as a query surface |

Phase 3 is the one that pays for the project. Phases 1 and 2 are what make it
possible.

---

## 5. What is built, and what is left

| Piece | Where | State |
| --- | --- | --- |
| Schema, views, indexes | [`build_sql_schema.py`](build_sql_schema.py), [`schema.sql`](schema.sql) | **Deployed** |
| Applying the schema | [`apply_schema.py`](apply_schema.py) | **Deployed**, 7 tables and 2 views |
| Question bank publisher | [`publish_question_bank.py`](publish_question_bank.py) | **Deployed**, 18 questions |
| Eval notebook writes to SQL | [`build_eval_notebook.py`](build_eval_notebook.py) | Built, skipped when unconfigured |
| Approval + feedback function | [`build_approval_function.py`](build_approval_function.py) | **Deployed**. No Key Vault |
| Mirror | [`build_mirror_notebook.py`](build_mirror_notebook.py) | **Deployed and run**, needs its schedule |
| Agent instruction path | [`build_agent_remediation_notebook.py`](build_agent_remediation_notebook.py) | Built, isolated |
| The report | Power BI Desktop | Manual, walkthrough in `approval-by-email.md` |
| Retiring Delta as a query surface | — | Not started |

### Verified end to end

A synthetic defect and approval were pushed through the real database:

```
dbo.remediation_queue   Q10  awaiting approval
   -> insert approval
dbo.remediation_queue   Q10  approved, not yet applied   admin@...
dbo.open_approvals      1
   -> run mirror_approvals
eval_approvals          Q10  approved  admin@...
dbo.approvals           Q10  mirrored
```

The instruction used in that test contained a double quote and a backslash,
and arrived in Kusto intact, which is the escaping the tests assert and the
one thing a mirror gets quietly wrong.

### The three manual steps

1. Add the SQL connection to the function item, alias `agentevalsql`.
2. Schedule `mirror_approvals` every minute.
3. Build the report in Desktop.

### Two things the tenant taught us

**A user data function parameter cannot contain an underscore.** The deploy
fails validation with a clear message, but only at deploy time. Parameters are
camelCase; columns are not.

**The mirror is a notebook, not a pipeline.** A Data Factory pipeline was the
design and the first implementation. Its definition cannot be validated
offline, and the copy activity's linked service for a Fabric SQL database was
rejected by the real API on every shape tried. The notebook is generated,
drift tested, has its cells compiled in unit tests, and was run against the
real workspace. It is also cheaper: a Python notebook on a one minute
schedule, rather than a Spark session that takes longer to start than the work
takes to run.

### Known rough edge

`approve.py` still writes directly to the eventhouse. It remains the
break-glass path when the report is unavailable, and it works, because the
remediation notebook reads the eventhouse. But a row it writes never appears
in `dbo.approvals`, so the report will not show it and `dbo.open_approvals`
will not count it. Prefer the report button. If the CLI becomes the normal
path again, it should be pointed at SQL.

---

## 6. What the answers changed

**Approving as admin.** No group check was added. The function records the
verified caller and the alerts go to the existing address, so the audit trail
names whoever clicked rather than a role. If approval later needs restricting,
the check belongs in the function, where it can be tested, rather than in
report permissions.

**Named feedback.** `dbo.feedback.created_by` and `created_oid` come from
`executing_user`, identically to an approval. Nobody types a name, and nobody
can submit feedback as somebody else.

**The agent path.** Built as its own notebook, reached by a reference run, and
guarded twice: `eval_harness.agent_target_is_safe` refuses to route a defect
whose evidence is a missing value, and the notebook re-checks the target
rather than trusting its caller. The SDK it needs is installed at run time,
which is why it is not in the notebook that writes to the semantic model.

**Two minutes.** The mirror runs every minute and the Activator rule polls
every minute. `mirrored_ts` makes a failed mirror a query rather than a
mystery.

---

## Related

- [`automation-spec.md`](automation-spec.md), the design as built today
- [`approval-by-email.md`](approval-by-email.md), the approval surfaces, the
  deployment order, and the report walkthrough
- [`build_approval_function.py`](build_approval_function.py), the function this
  spec simplified
