# Demo: proving a data agent is trustworthy

A 20 minute walkthrough of the accuracy loop, written to be delivered in front
of a customer.

The point of this demo is not the automation. It is the uncomfortable finding
in the middle of it, which is that a data agent most people would have shipped
was wrong in a way nobody would have caught. Everything else is the response to
that.

---

## The argument, in one paragraph

Say this before you open anything, because it is what the demo is for:

> Everyone asks whether the AI is accurate. Almost nobody can answer it,
> because they asked each question once, got a plausible answer, and moved on.
> Ask the same question three times and you find out whether the model is
> right, wrong, or ambiguous. Those are three different problems and only one
> of them is a bug you can fix.

---

## Before they arrive

| Check | Command or place | Why |
| --- | --- | --- |
| Tests pass | `python -m unittest discover -s validation -p "test_*.py"` | Proves the grading logic without touching capacity |
| Ground truth prints | `python validation/ground_truth.py` | The oracle. Q01 is `$412,918.50` |
| Dashboard opens | `Agent Accuracy` | Seven tiles, no error modal |
| There is history | `eval_runs` has several rows | A single row makes the trend argument impossible |
| Capacity is free | Fabric capacity metrics | Each run is 18 questions times 3, and it will queue behind other work |

Have a completed run ready. **Do not run the evaluation live for the first
time in front of anyone**, it takes about nine minutes and the room will die.

---

## Act 1: the question everyone asks. Two minutes

Open the data agent and ask it one thing:

> What is our total net revenue?

It answers `$412,918.50`. Then run `python validation/ground_truth.py` and show
Q01 is the same number.

Say:

> That is the demo most people give. One question, one right answer, and a room
> full of people who now believe the agent is accurate. Watch what happens when
> I ask it eighteen questions three times each instead.

---

## Act 2: what repetition finds. Five minutes

Open the dashboard. Go to **Latest run**.

Point at the score, then at the flake count. The line that lands:

> Six of eighteen questions answered correctly on some attempts and not others.
> A manual pass asks each question once, so it would have scored this same
> model fourteen or fifteen out of fifteen. We would have shipped it.

Then open **Instability over time** and make the harder point:

> A question that is right three times out of five is worse in front of a
> business user than one that is consistently wrong. A consistent error gets
> found once and briefed around. This one gets found by whoever happens to ask
> on the wrong afternoon.

### The finding worth stopping on

Open `eval_results` and show Q10, Q11 or Q12. The question is "Show me net
revenue by region". It carries no time filter, so the answer should cover all
the data. Some attempts answered for the most recent period only.

> The numbers came back looking completely reasonable. They were about a tenth
> of the truth. Nobody in a review would have queried them, because there is
> nothing about ninety thousand dollars that looks wrong until you know it
> should have been a hundred and seventy eight thousand.

That is the moment the demo is for. Let it sit.

---

## Act 3: the guardrails. Three minutes

Ask the agent the three questions it is supposed to refuse:

| Ask | Good answer |
| --- | --- |
| What will revenue be next quarter? | Says it holds historical data only, does not project |
| Which store is most profitable? | Says whether it used margin dollars or margin rate |
| Show me sales for the Northwest region. | Says there is no Northwest region, lists the three that exist |

Then:

> These sit outside the score deliberately. A model can score fifteen out of
> fifteen and still invent a region, and no threshold on the score would ever
> catch it. So they are tracked separately and any regression here is treated
> as high severity regardless of the score.

---

## Act 4: from finding to fix. Five minutes

Open the dashboard's **Remediation queue**.

> Each failing question, and the exact sentence that would fix it. Not a
> description of the fix. The literal text a person is being asked to approve.

Show one row's proposed instruction. Then run:

```bash
python validation/approve.py --list
```

Now show the refusal, which is more persuasive than the approval:

```bash
python validation/approve.py --question Q12 --by you@example.com
```

> It refuses. Q12 is tier 2, which means there is no sentence that fixes it.
> Something needs a person to open the model and think. The system knows the
> difference between a defect it can propose text for and one it cannot, and
> it will not pretend otherwise.

Then approve a real one:

```bash
python validation/approve.py --question <a tier 1 id> --by you@example.com
```

Then stop touching the keyboard.

> Within a minute the activator sees that decision and runs the remediation
> notebook. It appends that exact sentence to the semantic model's AI
> instructions, takes a full backup first, and then proves the write actually
> landed before it reports success.

Show the run appearing on its own in the notebook's run history.

---

## Act 5: the two things that make it safe. Three minutes

This is the part a customer's architect will care about, and it is worth more
than the automation.

**It fixes the model, not the agent.**

> Agent instructions are not passed to the DAX generation step. If we had
> written this fix into the agent instruction box, it would have looked like a
> change and done nothing. That is the most common mistake in this space. The
> fix goes into the semantic model, where it actually affects the query.

**It refuses to lie about success.**

> During the build, a run reported success while changing nothing. The content
> read back matched perfectly, because a read back can be served from the
> session's own copy of the model. It now also requires the server side
> timestamp to move. A remediation loop that reports success without changing
> anything is worse than no loop, because it gives you a green dashboard over a
> broken model.

---

## Act 6: the honest ending. Two minutes

Do not end on a success. End on this:

> We applied the approved fix. The score went from nine to eleven and all three
> guardrails went green. And one question got worse.

> One sentence fixed part of a problem and not the rest. The only reason we
> know that is that the system re-measured instead of assuming. It now marks
> the fix applied but not verified, and if the same sentence comes back as a
> proposal it escalates it to a human instead of offering it again.

> An automated remediation loop needs a way to admit its remedy did not work.
> Without one it will keep prescribing.

---

## Making it land with the customer

### Lead with their risk, not our architecture

Nobody buys an evaluation harness. They buy not being the person who briefed a
number that was a tenth of the truth. Open on the finding, not the design.

### Use their own question bank

The fifteen questions here are about coffee. Ten minutes before the meeting,
ask them for the five questions their executives actually ask, and put those on
screen. A demo answering their questions is worth ten answering ours.

### Match the message to who is listening

| They care about | Say |
| --- | --- |
| Data leader | You cannot govern what you cannot measure. This makes agent quality a number that moves, with an owner |
| Architect | The fix lands in the model, never the agent. Everything is append only and every change is backed up and reversible |
| Analytics lead | It tells you which failures a machine can fix and which need you, and it will not confuse the two |
| Risk or compliance | No change reaches the model without a named approver, and no run can report success without proving the write landed |
| Executive | Ask one question three times before you trust the answer. That is the whole idea |

### Three sentences worth memorising

> Ask each question once and you cannot tell wrong from ambiguous.

> A verified answer is a patch, not a fix. It solves one phrasing and improves
> the model by nothing.

> The instruction has to go where the query is built, or it changes nothing at
> all.

### Do not oversell

Say plainly what it does not do, because the credibility is the product:

- It knows about fifteen questions. It is a regression suite, not a proof.
- It writes sentences from a fixed library. It does not diagnose.
- The ground truth is only trustworthy because the data is synthetic and
  seeded. Against real refreshing data you compare against a reviewed query
  instead, and that is a different design.

An architect who hears you volunteer the limits will believe the rest.

---

## If something breaks

| Symptom | Almost certainly |
| --- | --- |
| Dashboard will not load | Schema version. See the comment in `build_dashboard.py` |
| Notebook will not start | Capacity exhausted. Show the last completed run instead |
| Agent is slow or errors | Shared capacity. The harness records these as errored and excludes them, which is itself a talking point |
| Approval does not trigger | Check the approvals rule is started in the activator |
| Numbers differ from this guide | The agent is nondeterministic. That is the demo, not a fault |

The last one deserves confidence rather than apology. If the numbers move
between runs, say so out loud and point at the flake count. It is the argument.

---

## Related

- [`automation-spec.md`](automation-spec.md), the design and what it found
- [`question-bank.md`](question-bank.md), the fifteen questions and three probes
- [`approval-by-email.md`](approval-by-email.md), the approval card
- [`../docs/08-validate.md`](../docs/08-validate.md), the manual loop underneath
