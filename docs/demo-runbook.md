# The demo, end to end

A running order for showing this repo to an internal audience in about 45 minutes.
The phase docs (`docs/00-setup.md` onward) are the build instructions. This is the
performance: what to open, what to say, and why anybody should care.

If you have 15 minutes rather than 45, do steps 6, 8, 9 and 10 and say the rest.

---

## The argument you are making

Say this at the start and again at the end, because everything else is evidence for it:

> The AI is the same before and after. The only thing that changes is how well the
> semantic model describes itself. Every trick for making Copilot better turns out to be
> modelling work you should have been doing anyway.

And the second half, which is the part most demos skip:

> If you cannot say how often it is right, you have not deployed AI. You have deployed a
> demo.

**Do not hide the failures.** A score of 15/15 proves nothing except that you picked easy
questions. The wrong answers are the most valuable thing on the screen, because they are
the only part that shows the loop working.

---

## Before you start

| Check | Why |
| --- | --- |
| `az account show` is the demo tenant | The CLI silently reverts to corp, and then every Fabric call 404s as if the items do not exist |
| Fabric capacity is running | A paused capacity fails jobs with `CapacityNotActive` |
| The workspace is open in one tab | You will move between about eight items |
| You know the current score | Open the KQL dashboard first so nothing surprises you |

Have these open in tabs, in this order: the workspace, the **ContosoCoffee** report, the
**AgentEvals** report, the **Agent Accuracy** dashboard, and VS Code.

---

## Step 1. The problem, before any Fabric at all

**Screen:** a slide, a whiteboard, or just talk. Thirty seconds, no clicking.

**Say:** "Everyone here has seen Copilot make a chart. Nobody here has seen anyone prove
it was right. The number one blocker for AI on BI is not capability, it is trust, and
trust is a measurement problem. So this demo ends with a score."

**Impact:** frames the whole session as governance rather than a toy. This is the line
that makes a sceptical data lead lean forward.

---

## Step 2. Provision the workspace from Copilot Chat

**Screen:** VS Code, GitHub Copilot Chat. `docs/01-provision.md`.

**Show:** the Fabric MCP server creating the workspace and lakehouse from a prompt.

**Say:** "This is not a portal click-through. Copilot is driving Fabric through an MCP
server, so provisioning is a conversation that leaves a transcript."

**Impact:** platform teams get repeatable environments without a portal runbook, and the
transcript is the audit trail.

> Keep this short. It is context, not the point. If you are short on time, say it and skip.

---

## Step 3. Land the data

**Screen:** the `load_to_lakehouse` notebook, then **LH_ContosoCoffee** > Tables.

**Show:** four Delta tables — `fact_sales`, `dim_date`, `dim_store`, `dim_product`.
About 64,000 rows.

**Say:** "Deliberately tiny. Nothing here takes long, so nothing hides behind a progress
bar. The dataset is boring on purpose — coffee, eight stores, two years — because the
argument is about the model, not the data."

**Impact:** shows the pattern is portable. Whatever they have, this shape fits it.

---

## Step 4. The model, and the honest bit

**Screen:** **ContosoCoffee** semantic model, model view.

**Show:** the star schema, the relationships, then open two or three measures and show the
`Description` on each.

**Say:** "This is a normal star schema. The only unusual thing is that every measure has a
description written for a reader who is not in the room. That is the whole trick."

**Impact:** this is the moment a data team realises the work is familiar. Not a new
product to buy — descriptions, names, and summarisation settings they already know how to
write.

---

## Step 5. Score it before you help it

**Screen:** the **Agent Accuracy** KQL dashboard, or the AgentEvals report.

**Say:** "We asked the model fifteen questions with known right answers, three times each,
before doing anything to prepare it for AI. Here is the score."

**Show:** the early runs. Your real history starts at **12/15**, and one early run scored
**9/15** with **7 flakes**.

**Say:** "Look at the flakes rather than the score. Seven questions gave a different answer
on repeat runs. That is worse than being wrong, because you cannot brief around it and you
cannot reproduce it in front of a customer."

**Impact:** the single most useful idea in the session. Most teams measure accuracy once;
almost nobody measures **stability**. A flake is an outage you cannot see.

---

## Step 6. Prep data for AI

**Screen:** **ContosoCoffee** > `Prep data for AI` > `AI instructions`.

**Show:** the instruction block. Read two lines aloud:

> *"Revenue, sales and turnover all mean Total Net Sales, which is after discounts."*
>
> *"Region groups stores and has exactly three values: West, Central, East. If a user
> names a value that is not in these lists, say it does not exist. Do not substitute the
> nearest match."*

**Say:** "This is not prompt engineering. Nobody types this at query time. It lives with
the model, it is version controlled, and it applies to every question anyone ever asks."

**Impact:** the answer to *"so we will be maintaining prompts forever?"* — no. You maintain
the model once and every front door improves at the same time.

> The second instruction is the interesting one. It tells the AI what does **not** exist.
> Most accuracy work is negative space.

---

## Step 7. Four front doors onto one model

**Screen:** the **ContosoCoffee** report, then the Copilot pane.

**Show:** ask the Copilot pane a question. Then mention the other three doors: standalone
Copilot, the Fabric data agent, and the optional Fabric IQ ontology.

**Say:** "Same model, four different front doors. When we fix the model in a minute, all
four get better at once. That is the leverage."

**Impact:** kills the fear of maintaining a separate AI stack per surface.

---

## Step 8. Run the loop and show a failure

**Screen:** the `agent_eval` notebook, then the **AgentEvals** report, page
**Agent Answer Quality**.

**Run:** `agent_eval` with `REPEAT=1`, `SURFACE=D`. About nine minutes, so start it and
keep talking, or use the run from earlier.

> Pass `REPEAT` as a number, not as text. A parameter of `"1"` makes `range(1, REPEAT + 1)`
> raise `TypeError` about a minute in, after the lakehouse reads and before any question is
> asked, and the only thing you see is the session being cancelled.

**Say:** "Fifteen questions, graded against ground truth computed from the source tables —
not from anything the AI said. If the grader asked the AI whether it was right, we would
be measuring nothing."

**Show:** a failing question and its evidence.

**Impact:** grading against source data, not model output, is what makes the number worth
anything. Say that out loud; it is the difference between a metric and a vanity number.

---

## Step 9. A human approves the fix

**Screen:** **AgentEvals** report, page **Review & Approve Fixes**.

**Show:** the queue. Every row has the question, the proposed instruction, the reason, and
crucially a **Target** column saying exactly where the change lands — `semantic_model` or
`data_agent`.

**Say:** "The loop proposes. A person decides. Nothing reaches the model without a name
against it, and the row tells you where the text will be written before you agree to it.
That distinction matters: an instruction on the agent changes how an answer reads, and
cannot change a number. Only the model can do that."

**The row to point at** is `F03`. The question was *"Show me sales for the Northwest
region."* There is no Northwest region.

**Say:** "This one is a trap we set. The dataset has West, Central and East. A helpful AI
rounds that to the nearest real thing and gives you a confident number for a region that
does not exist, and nobody ever checks. The fix is one sentence telling the model what is
not there."

**Then:** open page **Same Fix, Several Questions**.

**Say:** "One wrong behaviour usually shows up as four or five failing questions with the
same fix. Approving them one at a time is five clicks that all mean the same thing. This
approves the set once, and closes the others without writing the same sentence five
times."

**Impact:** this is the governance story. Auditors do not ask whether the AI is clever,
they ask who approved the change and where it went. Both are on screen.

---

## Step 10. Activator applies it, unattended

**Screen:** **Agent Accuracy Alerts** (the Reflex item), then the `agent_remediate`
notebook.

**Say:** "The approval lands in SQL, gets mirrored to the eventhouse, and Activator is
watching. It launches the remediation notebook itself — nobody runs anything."

**Show:** in the notebook run, the backup written to `Files/model_backups`, and the
instructions growing by one line under `## Automated remediation`.

**Say:** "Append only. It has never rewritten a line a person wrote, and there is a test
that fails if it ever tries. It also takes a census of the model before and after, because
this is a whole-model write and the naive version would report success after deleting
every measure."

**Impact:** the automation is safe by construction and the safety is testable. That is the
sentence that gets this into production.

---

## Step 11. The payoff

**Screen:** the **Agent Accuracy** dashboard.

**Say:** "Same fifteen questions. Same AI. Different model."

**Show:** the score history. Real numbers from this workspace:

| | Score | Flakes |
| --- | --- | --- |
| Early run | 9 / 15 | 7 |
| Middle | 12 / 15 | 4 |
| Best | **14 / 15** | **0** |

**Say:** "Nine to fourteen, and — more importantly — seven flakes down to zero. We changed
nothing about the AI. We described the model properly."

**Impact:** the whole argument, in one chart, with a number in it.

---

## Step 12. The bit nobody else demos

**Screen:** **AgentEvals** report, **Review & Approve Fixes**.

This is your strongest moment and it happened by accident. Somebody edited the AI
instructions by hand in the portal, which removed a fix the loop had applied and approved.
Nothing in any database changed, because nothing in any database was involved.

**Show:** the rows reading **"applied before, but not in the model now."**

**Say:** "Somebody edited the model outside this process. No backup, no record, nothing to
audit. The loop noticed on the next run and said so in plain words. The score went from
fourteen back to eleven, and it re-proposed the fixes that had gone missing."

**Say next:** "Every other status in this table is our own paper trail. This one is the
model itself. A system that only trusts its own log will tell you a fix is in place long
after somebody deleted it."

**Impact:** governance that survives people. Anyone who has run a platform knows the
change that gets made by hand at 5pm on a Friday. This catches it and names it.

### Sequencing, so this does not vanish mid-demo

The drift rows survive steps 10 and 11. Applying `F03` adds only `F03`'s sentence, and the
one Q10 and Q11 need is a different sentence that is still missing, so they keep failing
and keep reporting drift on every run until somebody approves *their* fix.

That gives you a choice:

- **Show it and leave it.** Safe. Nothing you do in steps 8 to 11 clears it.
- **Close the loop on stage.** Approve Q10 and Q11 from the queue, let the remediation
  apply, and re-run `agent_eval`. The rows change to "applied and verified" and the score
  climbs. It is the strongest version and it costs about ten minutes of run time, so only
  do it if you can talk over a progress bar.

The one thing that *will* clear it silently is somebody re-adding those instructions by
hand in the portal — the same act that caused the drift in the first place. If you are
rehearsing, do not tidy the model first.

---

## Closing

**Say:** "Three things to take away. One, everything that made the AI better was modelling
work, not AI work. Two, measure stability, not just accuracy — a flake is an outage you
cannot see. Three, a human approved every change, and the system checks the model rather
than believing its own records."

**If you only say one sentence:** *"We did not make the AI smarter. We made the model
easier to read, and we can prove it moved the number."*

---

## Questions you will get

**"How long did this take to build?"**
The phase docs are about three hours end to end. The loop is the part worth copying, and
it is a few notebooks and a table.

**"Would this work on our model?"**
The loop is model-agnostic. The question bank and ground truth are yours to write, and
writing them is the actual work — that is the useful discovery, not a limitation.

**"What if the AI is wrong in a way the grader misses?"**
Then the question bank is not good enough, and the fix is to add the question. The loop is
only ever as honest as its questions, which is why they are in source control with a hash
stamped on every run.

**"Why not just tell people the right prompt?"**
Because it does not survive the person who learned it. An instruction on the model applies
to everyone, forever, including the four front doors in step 7.

**"Is any of this preview?"**
Prep data for AI, standalone Copilot, the MCP servers and Fabric IQ are preview. The data
agent, the Copilot pane and everything in the loop are GA. Say which is which; being
straight about it buys credibility for the rest.
