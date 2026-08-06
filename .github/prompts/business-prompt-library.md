# Business user prompt library

Copy-paste prompts for the person who consumes the report rather than builds it. Every
prompt here is written for the `ContosoCoffee` model produced by phases 1 to 5, and every
expected number comes from `python validation/ground_truth.py`, so you can check any
answer live.

Use this alongside [`validation/question-bank.md`](../../validation/question-bank.md).
The question bank is the accuracy test, asked word for word and never reworded. This
library is the opposite exercise: it is what a real business user should actually type
once the model has passed that test.

- Phase guide for the Copilot surfaces: [`docs/06-insights.md`](../../docs/06-insights.md)
- Phase guide for the data agent: [`docs/07-agents.md`](../../docs/07-agents.md)

---

## 1. Prerequisites, because they decide the answer

The prompt is the last five percent. Almost every bad answer in this demo traces back to
something in this table being missing, not to the wording of the question.

| Prerequisite | Why the business user feels it | Where it is set | Phase |
| --- | --- | --- | --- |
| Paid F2 or higher, or P1 or higher with Fabric enabled | No Copilot button at all. Trial capacity does not qualify | Capacity settings | [0](../../docs/00-setup.md) |
| Tenant setting `Users can use Copilot and other features powered by Azure OpenAI` | Copilot silently absent for some users | Admin portal | [0](../../docs/00-setup.md) |
| Business-friendly table, column and measure names | Copilot answers using names the user does not recognise, so nobody trusts it | Semantic model | [3](../../docs/03-model.md) |
| Relationships defined, date table marked | Every time-based question is wrong or refused | Semantic model | [3](../../docs/03-model.md) |
| A description on every measure, meaning first | Copilot reads the first 200 characters and picks the wrong measure without it | Semantic model | [3](../../docs/03-model.md) |
| Summarisation set to `Don't summarize` on keys, years and sort columns | Nonsense totals such as a summed year | Semantic model | [3](../../docs/03-model.md) |
| AI instructions | Ambiguous words such as revenue, best and profitable resolve to the wrong measure | Prep data for AI (preview) | [4](../../docs/04-prep-for-ai.md) |
| AI data schema | Copilot picks a raw column instead of a curated measure | Prep data for AI (preview) | [4](../../docs/04-prep-for-ai.md) |
| Verified answers | Common questions return a freshly generated query instead of the visual leadership already signed off | Prep data for AI (preview) | [4](../../docs/04-prep-for-ai.md), pinned in [5](../../docs/05-report.md) |
| `Approved for Copilot` (preview) | A banner warns the user that answer quality could be low, before they see anything | Semantic model settings | [4](../../docs/04-prep-for-ai.md) |
| Q&A enabled on the semantic model | Nothing in Prep data for AI takes effect | Semantic model settings | [4](../../docs/04-prep-for-ai.md) |
| Descriptive visual titles on the published report | The data agent grounds on visual metadata, so `Total Net Sales by Region` helps and `Chart 3` does not | Report | [5](../../docs/05-report.md) |
| Read access to the report, the model, and any data agent | No answer at all, or a different answer from a colleague if row-level security is in play | Workspace | [1](../../docs/01-provision.md) |

**The five minute readiness check before you put this in front of anyone.**

1. Open the Copilot pane. If there is no button, it is capacity, every time.
2. Ask `What is our total net revenue?` and confirm `$412,918.50`.
3. Ask `Show me net revenue by region.` and confirm you get the pinned visual back, not a
   new table.
4. Ask `Show me sales for the Northwest region.` and confirm it says there is no such
   region rather than substituting West.
5. Expand `How Copilot arrived at this` on one answer and read the measure it used out
   loud. If you cannot explain that measure, the audience cannot either.

---

## 2. Choose the surface before you choose the prompt

| Surface | Status | Use it for | Do not use it for |
| --- | --- | --- | --- |
| Copilot pane in a report | GA | Explaining what is already on the page, summarising, follow-ups inside one report | Questions the report was never built to answer |
| Standalone Copilot in Power BI | Preview | Cross-item questions where the user does not know which report holds the answer | A guaranteed answer from one signed-off report |
| Fabric data agent, in-product chat | GA | Analytical, multi-part questions, and anything you want to reuse from another system | Pixel-perfect visuals. It returns data and prose |
| Data agent in Microsoft 365 Copilot or Teams | Preview | Meeting the user where they already work, `@` mention in a channel | Anything you have not tested in Fabric first |
| Data agent over MCP | Preview | Wiring the governed model into your own app or another agent | A demo you have not permission-tested |

Say this out loud once: **every surface in that table reads the same Prep data for AI
configuration.** If two of them disagree, that is a real finding about the model, not
noise about the tool.

---

## 3. What to use AI for, and what to keep doing yourself

Best practice starts with scoping the tool honestly. Copilot over a governed semantic
model is strong at some things and structurally incapable of others, and knowing which is
which is most of the skill.

| Use AI for | Why it works here | Keep doing yourself |
| --- | --- | --- |
| Getting to a first number fast | It reads the whole model, you do not have to know where the field lives | Signing off the number for external use |
| Slicing a known measure a new way | The measure logic is fixed in DAX, only the grouping changes | Defining what the measure should mean |
| Summarising a page or a visual you already trust | It is describing reviewed content, not inventing it | Deciding what belongs on the page |
| Multi-part questions you would otherwise raise a ticket for | It does five joins and a rank in one turn | Interpreting what the rank means for the business |
| Finding the question you had not thought to ask | It sees the whole schema, you see the page | Choosing which of those questions matters |
| Explaining a number to a non-analyst | It writes plain language faster than you do | Checking that the plain language is true |

| Do not use AI for | Why not |
| --- | --- |
| Forecasting or projecting | This model holds history only, 1 January 2024 to 31 December 2025. Any forward number is invented |
| Anything the model does not contain | No customer table, no returns, no competitor data. It cannot know what is not there |
| A number you will not check | If you cannot expand `How Copilot arrived at this` and explain the measure, do not quote it |
| Deciding what a metric means | Definitions belong in DAX and in AI instructions, agreed by humans, once |
| Bypassing a reviewed visual | If a verified answer exists, that is the higher-trust route |

The one-line version worth repeating to a business audience: **AI is fast at finding and
phrasing, and it is not accountable.** You stay accountable, which is why every prompt in
this library ends up asking it to show its work.

---

## 4. How to write a prompt that gets a usable answer

A good business prompt has five parts. Missing any one of them is how you get a number
you cannot defend.

| Part | Example fragment | What goes wrong without it |
| --- | --- | --- |
| Role or lens | `Act as a category manager` | You get a generic answer with no point of view |
| Scope | `for the Beverage category` | The whole model is in context and the number is a grand total |
| Measure | `by gross margin, in dollars` | It picks the wrong one out of 20 |
| Period | `for 2025` | Time intelligence measures compare two years against one and return nonsense |
| Output shape | `as a table, top 5, then one sentence on what to do` | You get prose you then have to re-ask for |

**Weak against strong, same intent.**

| Weak | Strong |
| --- | --- |
| `How are we doing?` | `Act as a retail CFO. For 2025, give me total net sales, gross margin, gross margin percent, and year over year growth. State the period and any filter you applied.` |
| `Which store is best?` | `Rank stores by net sales for 2025. Then rank them by net sales per store to show whether the ranking changes, and tell me which ranking I should quote to leadership and why.` |
| `Why did sales drop?` | `Show net sales by month for 2025 and name the three months with the largest month over month decline. For each, break the decline down by category and by channel.` |
| `Give me insights` | `Summarise this page in five bullets: what happened, what changed most, what is at risk, what is working, and the single number I should open with.` |
| `Forecast next quarter` | `The model holds history only. Give me the 2025 monthly trend and the average month over month change, and tell me explicitly that this is not a forecast.` |

Three habits worth teaching alongside the prompts:

- **Ask for the filter back.** `State the time period and any filter you applied` turns an
  undefendable number into a defendable one.
- **Ask it to show its choice.** `Which measure did you use, and why that one?` catches the
  revenue against gross sales mix-up before it reaches a slide.
- **Ask twice.** AI is nondeterministic. If a number surprises you, ask again before you
  conclude anything.

---

## 5. Persona prompt sets

Each set starts with a meta prompt. The meta prompt is the one to run live in a demo,
because it makes Copilot propose the agenda rather than answer a question you already
knew the answer to.

### 5.1 Executive, preparing a leadership readout

**The meta prompt.**

```text
Act as a retail executive preparing a leadership readout from this report. Based only on
the data in this semantic model, tell me the ten questions I should ask you to get the
most insight, ranked by how much they would change a decision. For each, say in one line
what the answer would let me do. Do not answer them yet.
```

Then pick three or four of what it proposes and ask them. That is the demo: Copilot
setting the agenda from the model it can actually see, not from generic retail knowledge.

**The prompt set.**

```text
Give me an executive summary of this page in five bullets: headline performance, the
largest change, the biggest risk, what is working, and the one number I should open with.
```

```text
For 2025, give me total net sales, gross margin, gross margin percent, order count and
year over year growth versus 2024. Present it as a table and state the period explicitly.
```

```text
Net sales grew 4.9 percent in 2025. Decompose that growth: how much came from each region,
each product category, and each channel? Tell me which single split explains the most.
```

```text
Which three things in this data would most concern a board, and which three would I want
to lead with? Use only what is in the model and say so if the data cannot support a claim.
```

```text
Write three bullets I can paste into a board slide about 2025 performance. Every number
must be one you can show me the source of.
```

**What good looks like.** Total net sales `$412,918.50` all time, `$211,396.15` in 2025
against `$201,522.35` in 2024, growth `4.90%`, gross margin `$283,482.20` at `68.65%`.

**The trap.** Ask `How much did we grow?` with no year and a well-configured model tells
you it filtered to 2025 and says so. An unprepped model quietly compares two years of
sales against one and reports a three-digit growth rate. That exact bug is documented in
[phase 5](../../docs/05-report.md). Run this question before and after phase 4 if you can.

### 5.2 Finance and margin owner

**The meta prompt.**

```text
Act as the finance business partner for this retail chain. Given the measures available in
this model, what are the eight margin and discount questions I should be asking every
month? Rank them and say which measure each one uses.
```

**The prompt set.**

```text
Show gross margin percent by product category for 2025, sorted lowest to highest, and tell
me which category is diluting the blended rate.
```

```text
What is our discount rate percent, and how does it differ by channel? Show total discount
in dollars alongside it so I can see the size of the giveaway, not just the rate.
```

```text
Compare average order value and average selling price by channel for 2025. Explain in one
line why they are different measures and which one answers a pricing question.
```

```text
Which products have above-average net sales but below-average gross margin percent? Those
are the ones I need to look at first.
```

```text
Show gross margin and gross margin percent by month for 2025. Flag any month where the
percent moved more than one point from the prior month.
```

**What good looks like.** Blended gross margin percent `68.65%`. Beverage is the largest
category at `$298,987.00`, Food `$79,779.50`, Retail `$34,152.00`.

**The trap.** `Which store is most profitable?` is ambiguous between margin dollars and
margin rate. After phase 4 the model should either state that it used margin dollars or
ask which you meant. Before phase 4 it silently picks one. Ask it deliberately and let the
room see the difference.

### 5.3 Retail and store operations

**The meta prompt.**

```text
Act as a regional operations director for eight coffee stores. Using only this model, what
should I ask you each week to know where to spend my time? Give me the questions, not the
answers, and note which ones are unfair comparisons unless normalised.
```

**The prompt set.**

```text
Rank stores by net sales for 2025. Then show net sales per store by region and explain why
the regional ranking can differ from the store ranking.
```

```text
Compare weekend and weekday net sales, and show it per store type as well as in total.
```

```text
Which store type has the highest average order value, and which has the highest units per
order? Say what that difference implies about how those formats are being used.
```

```text
Show net sales by month for 2025 for the Central region only, and name the weakest month.
```

```text
List every store with its region, store type and 2025 net sales, sorted descending, and
tell me which stores are more than 20 percent below the average for their store type.
```

**What good looks like.** Top store `Contoso Midtown` at `$75,663.08`. Regions West
`$178,256.56`, East `$144,668.89`, Central `$89,993.05`. Weekend `$96,223.79` against
weekday `$316,694.71`.

**The trap.** Comparing regions on total net sales is unfair because the regions hold
different numbers of stores. The AI instructions tell Copilot to use net sales per store
for these comparisons and to say that it did. If it does not say it, the instruction is not
being read, and that is a phase 4 finding.

### 5.4 Merchandising and category management

**The meta prompt.**

```text
Act as a category manager for a coffee retailer. Based on this model, what are the product
and assortment questions worth asking, and which of them this data genuinely cannot answer?
Be explicit about the second list.
```

**The prompt set.**

```text
Show net sales and gross margin percent by product category and subcategory for 2025 in one
table, sorted by net sales.
```

```text
Which five products drive the most net sales, and what share of the total do they account
for together?
```

```text
Which products sell in high units but contribute little net sales? Show total quantity and
net sales side by side.
```

```text
Compare category mix between 2024 and 2025 as a percentage of net sales, and tell me which
category gained the most share.
```

```text
For the Beverage category only, show net sales by channel and by store type for 2025.
```

**What good looks like.** Top product `Latte Regular` at `$57,045.27`. Total units
`94,417`. Average order line value `$6.42`.

**The trap.** Ask about `List Price` or `Cost per Unit` and a naive model averages them and
presents the result as an actual selling price. Those are list values on the product
dimension, not transaction values. The correct answer uses `Average Selling Price`. Try
`What is our average price per item?` and check which one it reaches for.

### 5.5 Channel and marketing

**The meta prompt.**

```text
Act as the head of digital and channel for this chain. From this model alone, what should I
be asking about channel performance and mix, and what would I need extra data to answer?
```

**The prompt set.**

```text
Break down net sales by sales channel for 2025 and show each channel as a share of total.
```

```text
How has channel mix changed between 2024 and 2025? Show it as percentage of net sales per
year, not just dollars.
```

```text
Compare average order value across In Store, Mobile Order and Delivery, and tell me which
channel is worth more per order.
```

```text
Show gross margin percent by channel. Is the fastest-growing channel also the most
profitable one?
```

```text
Show monthly net sales for Mobile Order in 2025 and name the three strongest months.
```

**What good looks like.** In Store `$256,105.03`, Mobile Order `$111,125.55`, Delivery
`$45,687.92`.

**The trap.** `How many customers ordered on mobile?` has no answer. There is no customer
table. `Order Count` counts sales order lines, and `Total Quantity` counts items. A good
model says so plainly. A bad one hands you an order count and lets you call it customers,
which is the kind of error that survives all the way into a strategy deck.

### 5.6 The analyst who has to defend the number

This persona is not asking for insight. They are auditing the previous five.

```text
For the answer you just gave, list the exact measures, columns and filters you used, and
show me the query.
```

```text
Is that number affected by any filter currently applied to this page? Say which, and give
me the unfiltered value as well.
```

```text
You used Total Net Sales. What would the same answer be using Gross Sales, and why is Total
Net Sales the right default here?
```

```text
What in this model could make this answer misleading? Name the assumptions rather than
repeating the number.
```

Then check it against `python validation/ground_truth.py`. If it disagrees, the fix order
is: the model, then the AI data schema, then the verified answers, then the AI
instructions. It is almost never the wording of the question.

---

## 6. Work the visuals, not just the chat box

The chat box is the least governed way to ask a question. The visuals on the page have
already been reviewed, and there are three ways to make AI use them.

### 6.1 Verified answers, the highest-trust path

A verified answer pins a specific reviewed visual to a set of trigger phrases. When a user
question matches, Copilot returns **that visual**, not a freshly generated query. It is the
only mechanism here where a human has pre-approved the exact output.

Three are pinned in this demo: `Total Net Sales by Region`, `Total Net Sales by
Year-Month`, and `Net Sales by Category`.

**Prompts that should hit them.**

```text
Show me net revenue by region.
```

```text
How have total net sales changed over time?
```

```text
What is the trend of net sales by month?
```

```text
Show me net sales by category.
```

**How to tell you hit one.** The response renders the pinned visual, formatting and title
included, rather than a generated table. If you get a plain table instead, the phrasing did
not match a trigger.

**How to use them well.**

- Pin the two or three visuals your leadership already quotes. Not more. Every verified
  answer is a promise you maintain when the model changes.
- Add trigger phrases in the words users actually use, including the sloppy ones:
  `revenue by region`, `regional sales`, `how is each region doing`.
- Let Copilot suggest phrases from the selected visual, then delete the ones nobody would
  say. Its suggestions are a starting point, not the list.
- Test the phrase that a user types under pressure, not the one you wrote. `sales by
  region` and `region sales` are different strings.
- When a verified answer stops matching after a model change, that is the signal to
  revisit it. Treat a missed match as a defect, not as user error.

### 6.2 Ask about the visual that is already on screen

In read mode, with the report open, the Copilot pane can work against what is on the page.
These prompts are the ones a business user gets most value from, because the answer is
anchored to a visual somebody has already validated.

```text
Explain what this visual is telling me in plain language, and name the measure it uses.
```

```text
Summarise this page for someone who has thirty seconds.
```

```text
What is the most surprising thing on this page, and what would I need to check before I
repeat it?
```

```text
This chart shows a dip. Break that dip down by category and by channel and tell me which
one accounts for most of it.
```

```text
Suggest three follow-up questions this page raises that I cannot answer from it.
```

That last prompt is the natural handoff to standalone Copilot or the data agent, and it is
the cleanest way to show why more than one surface exists.

The classic `Analyze` options on a data point, such as explaining an increase or a
decrease, are a separate statistical feature rather than a Copilot one. They are still
worth showing next to the Copilot answers, because they explain a change without generating
prose, and the two together are more convincing than either alone.

### 6.3 The narrative visual

The narrative visual is the same summarisation pinned to the page, so it refreshes with the
data and every reader sees the same words. A business user does not write this prompt, they
inherit its output. Ask your report author for it in these words:

```text
Add a narrative visual that summarises net sales performance for 2025 compared to 2024.
```

Use it where a report is consumed without anyone present to interpret it: an app, an email
subscription, a screen in an office. Read its output aloud before you publish. If it says
something untrue, the fault is in the model or the AI instructions, not the visual.

Copilot summaries in standard email subscriptions are the least flashy feature in this
whole demo and consistently the one people adopt first. Show it.

---

## 7. The leadership readout, in six prompts

Run these in order, in one Copilot pane session, with the executive page open. It takes
about four minutes and it is the most convincing sequence in the demo because each prompt
depends on the last.

**Turn 1, frame the page.**

```text
Summarise this page in five bullets for a leadership audience.
```

**Turn 2, get the headline numbers.**

```text
For 2025, give me total net sales, gross margin, gross margin percent and year over year
growth versus 2024, as a table. State the period you used.
```

**Turn 3, find where the growth came from.**

```text
Decompose that growth by region, by category and by channel. Which split explains the
most?
```

**Turn 4, make the comparison fair.**

```text
Compare regions fairly. Use net sales per store as well as total net sales and tell me
whether the ranking changes.
```

**Turn 5, surface the limits.**

```text
What are the two biggest risks visible in this data, and what would I need that this
model does not contain to confirm them?
```

**Turn 6, package it.**

```text
Turn all of that into five bullets for a board slide. Every number must be traceable to
a measure you can name.
```

Turn 5 is the important one. A well-prepared model answers it with the limits of its own
data: no customer table, no returns, history only to 31 December 2025. A poorly prepared
one invents a market view. That contrast is worth more than any correct number.

---

## 8. Data agent prompts

Same business questions, different vehicle. What changes:

| | Copilot pane | Fabric data agent |
| --- | --- | --- |
| Grounding | Semantic model plus the open report | Semantic model, plus report visual metadata |
| Verified answers | Returns the pinned visual | Informs the answer, but the reply is data and prose |
| Output | Visuals and prose | Text and tables, capped at 25 rows and 25 columns |
| Multi-part questions | Weaker | Stronger, it is built for them |
| Reuse | Inside Power BI | Teams, Microsoft 365 Copilot, Foundry, Copilot Studio, MCP |
| Where behaviour is configured | Prep data for AI | Prep data for AI for the query, agent instructions for the reply |

### 8.1 Prerequisites specific to the agent

- Everything in section 1. The agent inherits every model weakness, it does not fix any.
- One data source: the `ContosoCoffee` semantic model. Adding the lakehouse gives the
  orchestrator an ungoverned route to the same numbers.
- The tables ticked in the agent Explorer match the tables in the phase 4 AI data schema.
  If they differ, the agent and the Copilot pane will disagree and neither will be wrong.
- A real publish description. It becomes the tool description that Microsoft 365 Copilot and
  MCP clients read when deciding whether to call your agent.
- Read permission on the semantic model is enough. Build is not required for agent queries.
- Queries run read only, under the calling user's permissions, so two users can correctly
  get two different answers.

### 8.2 The meta prompt

```text
You have access to the Contoso Coffee sales model. Describe what you can and cannot answer,
list the measures and dimensions available to you, and give me the ten highest-value
questions a retail leadership team should be asking you. Do not answer them yet.
```

This is the first prompt to run against any new agent. If the description of its own scope
is vague, so is the publish description, and every downstream system that reads it will make
poor routing decisions.

### 8.3 Multi-part prompts, where the agent earns its place

```text
For 2025, give me a table of net sales, gross margin and gross margin percent by region. Add
net sales per store as a fourth column, and tell me which region looks strongest on each of
the two views.
```

```text
Compare 2024 and 2025 across category, channel and store type. For each, give me the
percentage point change in share of net sales, and rank the changes by size.
```

```text
Identify the three months in 2025 with the largest month over month decline in net sales.
For each month, break the decline down by category and name the largest contributor.
```

```text
Build me a one-page monthly performance summary for December 2025: net sales, gross margin
percent, order count, average order value, top three products, top three stores, and channel
mix. Label every number with the period it covers.
```

```text
Which stores are in the bottom quartile on gross margin percent but the top half on net
sales? Explain what that combination usually means.
```

### 8.4 Consumption prompts, once the agent is published

In Microsoft 365 Copilot or Teams, `@` mention the agent inside the conversation where the
decision is being made:

```text
@Contoso Coffee Analyst what were net sales and gross margin percent in 2025, and how did
that compare with 2024?
```

```text
@Contoso Coffee Analyst before this review, give me the three numbers I should have in my
head about Central region performance.
```

That is the argument for building an agent rather than only a report: the answer arrives in
the meeting, not in a tab somebody has to remember to open.

### 8.5 Prompts that should be refused

Run these deliberately. A confident wrong answer here tells you more about your setup than
five correct ones.

```text
What will revenue be next quarter?
```

```text
How many unique customers did we serve in 2025?
```

```text
Show me sales for the Northwest region.
```

```text
What is our market share against other coffee chains?
```

```text
How did we perform in 2026?
```

Good behaviour: the model contains history only from 1 January 2024 to 31 December 2025,
there is no customer table, the regions are West, Central and East, and there is no
competitor or market data in scope. Each refusal traces to a specific line in the AI
instructions, so a refusal that does not happen is a phase 4 gap you can point at.

### 8.6 Verify every agent answer the same way

```text
Show me the query you used for that answer.
```

Expand the generated DAX. Then compare against `python validation/ground_truth.py`. Record
it as pass D in [`validation/scorecard.md`](../../validation/scorecard.md).

---

## 9. Anti-patterns

| Anti-pattern | Why it hurts | Do this instead |
| --- | --- | --- |
| Rewording a question until the answer looks right | Hides a real defect and teaches users the tool is unreliable | Record the failure, fix the model or the AI instructions |
| Asking for growth without naming a year | Time intelligence needs a single period in context | Name the year, or ask it to state which year it used |
| Accepting a number with no stated filter | Undefendable the moment somebody asks | Add `state the period and any filter you applied` |
| Treating order count as customers | There is no customer table in this model | Ask what the measure counts before you quote it |
| Comparing regions on totals | The groups hold different numbers of stores | Ask for net sales per store as well |
| Averaging list price to get a selling price | List price is a catalogue value, not a transaction value | Use `Average Selling Price` |
| Asking for a forecast | The model holds history only | Ask for the trend and the average change, and label it as history |
| Pinning a dozen verified answers | Each one is a maintenance promise | Pin the two or three leadership actually quotes |
| Putting business definitions in the data agent instruction box | They are not passed to the DAX generation step | Put them in Prep data for AI |
| Demoing only the questions you know work | The failures are the part that builds trust | Run the three that should fail, on purpose |

---

## 10. The one page to hand a business user

1. Say who you are and what decision you are making. `Act as ...` genuinely changes the
   answer.
2. Name the period. Almost always the year.
3. Name the measure if you know it. Say `net sales` rather than `sales` when you mean after
   discounts.
4. Ask for the shape you want back: a table, five bullets, top 5.
5. Always end with `state the period and any filter you applied`.
6. Expand `How Copilot arrived at this` before you repeat a number to anyone.
7. If it surprises you, ask again. AI is nondeterministic.
8. If it refuses, read the refusal. It usually names a real limit of the data.
9. If the answer comes back as a familiar chart, you hit a verified answer. That is the
   highest-trust answer available to you.
10. If it is wrong, report the question and the measure it used. That is a model defect and
    somebody can fix it.
