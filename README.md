# Power BI AI Demo: build, publish, use, and validate

A small, end-to-end demo of what AI actually does across the whole Power BI lifecycle on
Microsoft Fabric. One synthetic dataset, nine short phases and one gate, and a scored
accuracy loop at the end so you can prove the answers were right.

It covers **Power BI Copilot**, **GitHub Copilot**, the **Fabric MCP servers**, a
**Fabric data agent**, and optionally a **Fabric IQ ontology**.

---

## The point of it

Most AI demos are one trick: Copilot makes a chart, everyone claps, nobody learns
anything durable.

This one makes a different argument:

> The AI is the same before and after. The only thing that changes is how well your
> semantic model describes itself. Everything you can do to make Copilot better is
> modelling work you should have been doing anyway.

So you ask the same 15 questions twice: once before you prepare the model for AI, once
after. The gap between those two scores is the entire demo. Everything else is context.

---

## What you will build

**Contoso Coffee**, a fictional retailer. 8 stores, 3 regions, 12 products, 2 years of
daily sales. About 64,000 rows, which is deliberately tiny so nothing takes long.

```
CSVs  ->  Lakehouse  ->  semantic model  ->  report  ->  Copilot  ->  data agent
                              ^                                          |
                              +--------- the accuracy loop --------------+
```

---

## The nine phases, plus one gate

| # | Phase | Time | What the AI does | Guide |
| --- | --- | --- | --- | --- |
| 0 | Setup | 20 min | Nothing yet. Capacity, tenant settings, MCP servers. | [00-setup](docs/00-setup.md) |
| 1 | Provision | 10 min | **Fabric MCP** creates the workspace and lakehouse from a chat prompt | [01-provision](docs/01-provision.md) |
| 2 | Load | 10 min | **GitHub Copilot** writes the ingestion notebook | [02-load](docs/02-load.md) |
| 3 | Model | 25 min | **GitHub Copilot** writes DAX measures and descriptions; **DAX Copilot** explains them | [03-model](docs/03-model.md) |
| 3b | Readiness audit | 15 min | Nothing. Score the model against the Microsoft Learn checklist before you score the AI. | [03b-readiness-audit](docs/03b-readiness-audit.md) |
| 4 | Prep for AI | 20 min | **Prep data for AI** (preview): AI instructions, AI data schema, verified answers, Approved for Copilot (preview) | [04-prep-for-ai](docs/04-prep-for-ai.md) |
| 5 | Report | 15 min | **Power BI Copilot** builds report pages from a prompt | [05-report](docs/05-report.md) |
| 6 | Insights | 15 min | **Copilot pane** and **standalone Copilot** answer business questions | [06-insights](docs/06-insights.md) |
| 7 | Agents | 25 min | **Fabric data agent** over the model and lakehouse; **Fabric IQ ontology**, optional | [07-agents](docs/07-agents.md) |
| 8 | Validate | 15 min | Nothing. This is the human check on all of the above. | [08-validate](docs/08-validate.md) |

Those times add up to about **170 minutes** the first time, including setup. Phase 7's
optional ontology step adds another 20.

**Short on time?** Phases 0, 3, 3b, 4, 6, 8 is the smallest run that still makes the
point, and comes to about 110 minutes.

---

## Before you start

One prerequisite catches almost everyone:

> **Copilot in Power BI needs a paid F2 or higher Fabric capacity, or P1 or higher.
> Fabric trial capacities do not qualify.** You can build everything else on a trial,
> but the Copilot button will not appear.

After buying or scaling a capacity, allow up to 24 hours for Copilot to show up.

You also need:

- A Fabric administrator to turn on the Copilot tenant settings, listed in
  [phase 0](docs/00-setup.md)
- Power BI Desktop, current release
- VS Code with the GitHub Copilot Chat extension
- Python 3.10 or later, standard library only, no pip installs

---

## Quickstart

```bash
git clone https://github.com/alipouw13/powerbi-ai-demo.git
cd powerbi-ai-demo

# generate the data (already committed, this just proves it is reproducible)
python data/generate_data.py

# print the correct answer to every question in the question bank
python validation/ground_truth.py
```

Then open [`docs/00-setup.md`](docs/00-setup.md) and work down.

Copy the MCP config sample if you want the Fabric Core MCP server in VS Code:

```bash
cp .vscode/mcp.json.example .vscode/mcp.json
```

---

## The accuracy loop

This is the part other demos skip.

```
ask the 15 questions  ->  score against ground truth  ->  find the failures
        ^                                                       |
        |                                                       v
   re-ask the same 15  <-  fix the model, not the prompt  <------+
```

[`validation/question-bank.md`](validation/question-bank.md) has 15 questions with known
answers, plus 3 that are designed to fail so you can see what a bad answer looks like.

[`validation/ground_truth.py`](validation/ground_truth.py) computes the correct answer
for all 15 straight from the CSVs. Every number quoted anywhere in this repo comes from
that script, never from prose written by hand.

[`validation/scorecard.md`](validation/scorecard.md) is where you record five passes:

| Pass | Surface | After |
| --- | --- | --- |
| A | Copilot pane, before Prep data for AI | phase 3b |
| B | Copilot pane, after Prep data for AI | phase 4 |
| C | Standalone Copilot (preview) | phase 6 |
| D | Fabric data agent | phase 7 |
| E | Data agent plus ontology (preview, optional) | phase 7 |

Three rules that make the loop honest:

1. Ask the questions exactly as written. Rewording until it works hides a failure.
2. Fix the model, not the prompt. Descriptions, summarisation, names, AI instructions.
3. A verified answer is a patch, not a fix. It solves one phrasing, not the model.

---

## Score the model before you score the AI

If the argument is that model quality decides AI quality, then measuring model quality
should come first. Otherwise you are asserting the thing you claim to be proving.

Microsoft publishes exactly the list you need:
[Optimize your semantic model for Copilot in Power BI](https://learn.microsoft.com/power-bi/create-reports/copilot-evaluate-data).
Five areas: model structure, measures and KPIs, columns and data quality, refresh and
security and metadata, and DAX query considerations. None of it is AI-specific advice.
It is the modelling work a good BI developer already does, which is the whole point.

[`semantic-model/ai-readiness-checklist.md`](semantic-model/ai-readiness-checklist.md)
turns that page into a checklist with the Contoso Coffee specifics filled in, and
[phase 3b](docs/03b-readiness-audit.md) is the fifteen minutes you spend running it.

You come out of it holding a written list of **predicted failures**. Pass A then tells
you which predictions were right. That is a much better moment than a failure nobody saw
coming.

Three items on it catch nearly everyone:

- Copilot uses only the **first 200 characters** of a description, so put the business
  meaning first and the caveats last.
- **Calculation items are not in the model metadata at all.** The only place Copilot can
  learn that `YTD`, `MTD` and `PY` exist is the calculation group column's description.
- **A measure defined in a report is invisible** to anything reading the semantic model,
  including data agents.

If you want it scored automatically, the community
[Semantic Model AI Readiness Analyzer](https://github.com/SoomroFarhanH/SemanticModelBPforAI/tree/main/SemanticModel-AI-Readiness-Analyzer)
is a Fabric notebook that runs most of the checklist and ranks findings Critical,
Important, Recommended. It is a community project, not a Microsoft product and not
supported by Microsoft. It is built on
[Semantic Link Labs](https://github.com/microsoft/semantic-link-labs), which is.

---

## Specialist agents

Every phase from 1 onward has an agent definition in [`.github/agents/`](.github/agents),
plus an orchestrator that routes between them. Phase 0 is setup, so it has no agent. They are
prompt files, so they work in GitHub Copilot in VS Code and read fine as documentation
if you would rather do it by hand.

| Agent | Owns |
| --- | --- |
| `demo-orchestrator` | Runs the whole demo, routes to the others |
| `fabric-provisioner` | Phase 1, workspace and lakehouse via Fabric MCP |
| `data-loader` | Phase 2, CSVs to Lakehouse tables |
| `semantic-model-author` | Phase 3, DAX, relationships, metadata |
| `model-readiness-auditor` | Phase 3b, the AI readiness audit before pass A |
| `copilot-readiness` | Phase 4, Prep data for AI, Approved for Copilot |
| `report-builder` | Phase 5, Copilot-authored report pages |
| `insights-analyst` | Phase 6, consumption and the question bank |
| `data-agent-builder` | Phase 7a, Fabric data agent |
| `ontology-architect` | Phase 7b, Fabric IQ ontology, optional |
| `accuracy-validator` | Phase 8, scoring, diagnosis, the loop |

Copy-paste prompts for each phase are in
[`.github/prompts/README.md`](.github/prompts/README.md).

---

## What is in the repo

```
.github/agents/      11 specialist agents: an orchestrator, then one or more per phase from 1 onward
.github/prompts/     copy-paste prompts, one section per phase from 1 onward
data/                synthetic CSVs and the seeded generator that made them
fabric/              notebook to land the CSVs as Lakehouse tables
semantic-model/      DAX measures, the AI instructions text, the AI readiness checklist
validation/          question bank, ground truth script, scorecard
docs/                one short guide per phase
SPEC.md              the demo contract: phases, personas, success criteria
```

---

## Feature status

Preview features move. Re-check before you present.

| Feature | Status |
| --- | --- |
| GitHub Copilot in VS Code | GA |
| Copilot in Power BI, report pane | GA |
| DAX query view with Copilot | GA |
| Fabric data agent | GA |
| Fabric Core MCP Server, remote | Preview |
| Fabric MCP Server, local | Preview |
| Power BI MCP Server, local (model authoring) | Preview |
| Power BI MCP Server, remote (chat with data) | Preview |
| Copilot in Power BI, standalone | Preview |
| Prep data for AI | Preview |
| Approved for Copilot | Preview |
| Fabric IQ ontology | Preview |
| Data agent consumption outside Fabric | Preview |

Every phase guide links to the Microsoft Learn page it is based on. If a menu has moved,
Learn is right and this repo is out of date.

---

## Honest caveats

- **AI is nondeterministic.** The same prompt can return different wording and
  occasionally a different answer. Judge the number, not the sentence. Run the bank more
  than once if a result surprises you.
- **Copilot is good at the first 70 percent** of a report and does not know which 30
  percent it got wrong. That is how to use it, not a criticism of it.
- **Nothing here replaces reading the docs.** This is a guided path through them.
- **No real data.** Everything is synthetic and generated by a seeded script.

---

## Licence

MIT. See [LICENSE](LICENSE).

Contoso is a fictional company used in Microsoft documentation and samples. This repo is
a community demo and is not an official Microsoft product.
