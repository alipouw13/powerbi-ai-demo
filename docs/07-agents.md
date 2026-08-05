# Phase 7. Agents

**Agents:** `data-agent-builder`, then optionally `ontology-architect`
**Time:** 25 minutes, plus 20 for the optional ontology
**AI on show:** Fabric data agent (GA), Fabric IQ ontology (preview)

Phases 5 and 6 put AI inside Power BI. This phase takes the same governed model and
serves it to anything that can hold a conversation.

---

## Part A. Fabric data agent

A Fabric data agent is a conversational analyst scoped to data you choose. It is
**generally available**.

### Prerequisites

- Paid F2 or higher Fabric capacity, or P1 or higher with Fabric enabled
- Tenant settings, under Copilot and Azure OpenAI:
  - `Users can use Copilot and other features powered by Azure OpenAI`
  - The cross-geo processing and cross-geo storing settings, if your capacity is outside
    the EU data boundary and the US
- Read access to every source you add
- To use the agent from Copilot in Power BI, the standalone Copilot tenant setting on
- Phase 4 finished. Prep data for AI is not optional here, it is the thing that makes the
  agent accurate. See "why the instruction box is not where the work happens" below.

### One source, on purpose

This agent gets **one** data source: the `ContosoCoffee` semantic model.

Not the lakehouse. The lakehouse holds the same numbers in raw, ungoverned form. Adding
it gives the orchestrator a second way to answer "what was revenue in 2025", one that
bypasses every measure, description and business rule built in phases 3 and 4. You would
then spend the demo writing routing instructions to talk the agent out of using a source
you chose to give it.

An agent supports up to five sources. Use fewer. Fewer sources means less ambiguity,
better routing, and lower latency.

### Build it

1. In the workspace, `+ New item`, search `Fabric data agent`, select it.
2. Name it `Contoso Coffee Analyst`.
3. The OneLake catalog opens. Add one source: the `ContosoCoffee` semantic model.
4. In the Explorer pane, tick the tables the agent may use: `Date`, `Sales`, `Product`,
   `Store`. Select the **same tables you chose in the phase 4 AI data schema**. If the two
   disagree, the agent and the Copilot pane will answer differently and you will not know
   which to trust.
5. `Data agent instructions`. The text to paste is in
   [`.github/prompts/README.md`](../.github/prompts/README.md), phase 7. Read the note
   below first so you understand what this box does and does not do.
6. `Example queries`. **Not available.** Semantic model sources do not support example
   query pairs, data source instructions, or data source descriptions. Verified answers in
   Prep for AI are the equivalent, which is another reason phase 4 comes first.
7. Test in the chat canvas. Expand the generated DAX on each answer and check it before
   you believe the number.
8. `Publish`. Write a real description. It becomes the MCP tool description and the
   Microsoft 365 Copilot description, so it is how other systems decide to call your
   agent.

### Why the instruction box is not where the work happens

This is the single most useful thing to say out loud in this phase.

**Agent-level instructions are not passed to the DAX generation step.** For a semantic
model source, the DAX generation tool reads only the model metadata and the Prep data for
AI configuration. Anything you write in the agent instruction box about which measure
means what is ignored when the query is built.

So the two boxes have different jobs:

| Put it here | What belongs there |
| --- | --- |
| Prep data for AI, on the model | Business definitions, terminology, which measure to use, closed value lists, refusal rules. Everything that changes the DAX. |
| Data agent instructions | Objective, scope, tone, response formatting, abbreviations, and how to handle out-of-scope questions. Everything that shapes the reply after the DAX has run. |

Repeating your business definitions in the agent box feels productive and does nothing.
Phase 4 is doing the work.

The other thing that surprises people: for a semantic model source, only **Read**
permission is required. Build permission is not needed for agent-driven queries.

### How it answers

The agent picks a source, then generates a query with the matching translator. With a
single semantic model source, that is always NL2DAX over the XMLA endpoint:

| Source | Translator |
| --- | --- |
| Power BI semantic model | NL2DAX, over the XMLA endpoint |
| Lakehouse or warehouse | NL2SQL |
| KQL database | NL2KQL |

It validates the query, executes it **read only** under the calling user's permissions,
and formats the result.

Beyond Prep for AI, the DAX generation tool also reads **report visual metadata**: visual
titles, the columns and measures each visual uses, and the filters applied. The report
built in phase 5 is therefore part of the grounding, which is why its visuals have
descriptive titles rather than the Copilot defaults.

### Consuming it

In-product chat is GA. These paths are preview:

| Path | How |
| --- | --- |
| Copilot in Power BI | Copilot pane, `Add items for better results`, `Data agents` |
| MCP endpoint | `https://api.fabric.microsoft.com/v1/mcp/workspaces/{workspaceId}/dataagents/{dataAgentId}/agent`, scope `https://api.fabric.microsoft.com/.default` |
| Microsoft Foundry | `Add`, `Knowledge`, `Microsoft Fabric`, then `FabricTool` in `azure-ai-projects` |
| Copilot Studio | `Agents`, `Add`, `Microsoft Fabric`, validated for the Teams channel |
| Microsoft 365 Copilot | `Publish to Agent Store`, then `@` mention it |

Data agent responses are capped at 25 rows and 25 columns. Some responses are not
returned through the SDK, Microsoft 365 Copilot, Teams, or Foundry. Check the limitations
section of the concepts page for the current list.

For new code prefer the MCP endpoint. The older Python client path builds on the OpenAI
Assistants API, which has an announced shutdown date of 26 August 2026.

### Verify

Ask the same 15 questions. Record them as pass D. Two AI surfaces over one governed model
is a far more interesting comparison than either alone, and because both read the same
Prep for AI configuration, a disagreement between them is a real finding rather than
noise.

For each answer, expand the generated DAX. If a number is wrong, the fix is almost always
in one of four places, in this order: the model itself, the AI data schema, the verified
answers, then the AI instructions. It is very rarely the agent instruction box.

Docs:
- https://learn.microsoft.com/fabric/data-science/concept-data-agent
- https://learn.microsoft.com/fabric/data-science/how-to-create-data-agent
- https://learn.microsoft.com/fabric/data-science/data-agent-tenant-settings
- https://learn.microsoft.com/fabric/data-science/semantic-model-best-practices
- https://learn.microsoft.com/fabric/data-science/data-agent-configurations
- https://learn.microsoft.com/fabric/data-science/data-agent-semantic-model

---

## Part B. Fabric IQ ontology, optional, preview

Skip this if the preview is not enabled on your tenant. The demo is complete without it.

### What to say first

Fabric IQ is the business context layer, alongside Work IQ, Foundry IQ, and Web IQ in
Microsoft IQ. It has three layers: unified data in OneLake, business intelligence in
Power BI semantic models, and operational intelligence in the ontology item.

The point for this demo: a semantic model answers "what is revenue by region". An
ontology answers "what is a Store, what is a Product, and how do they connect", once,
for every agent and every workload, instead of once per report.

| Concept | Plain meaning | Contoso Coffee |
| --- | --- | --- |
| Entity type | The reusable definition of a real world thing | `Store`, `Product`, `Sale` |
| Entity instance | One concrete occurrence | The Midtown store |
| Property | A named fact with a type | `Store.Region` |
| Relationship | A typed, directional link with cardinality | `Sale occurred at Store` |
| Data binding | Link from definition to real OneLake data | `Store` bound to `dim_store` |
| Ontology graph | The queryable instance graph | Store to Sale to Product paths |

Ontology also has **NL2Ontology**, which turns a business question into a structured
query across the bound sources.

### Prerequisites

A Fabric administrator enables, in tenant settings:

- `Enable Ontology item (preview)`
- `Users can use Copilot and other features powered by Azure OpenAI`
- `Data sent to Azure OpenAI can be processed outside your capacity's geographic region,
  compliance boundary, or national cloud instance`

### Generate it from the semantic model

This is the fast path, and it is the one worth showing, because it proves the phase 3
work was not throwaway.

1. Open the `ContosoCoffee` semantic model in Fabric, or its overview page.
2. Select `Generate Ontology` on the ribbon.
3. Pick the workspace, name it `ContosoCoffeeOntology`. Letters, numbers and underscores
   only. No spaces, no dashes.
4. Select `Create`.

If no entity types appear: the model is not published, its tables are hidden, or its
relationships are missing. All three are phase 3 problems.

### Then clean it up

Generated entity types are named after the **model** tables, so you get `Sales`, `Store`,
`Product` and `Date`. Because phase 3 already renamed everything to business names, this
is now a light touch rather than a rescue: singularise `Sales` to `Sale`, and drop `Date`
if you do not want a calendar entity in the graph.

That is the lesson, and it is a better one than it looks. Had the model still carried
`fact_sales` and `dim_store`, those names would have propagated straight into the
ontology and from there into every agent that consumes it. Naming debt compounds
downstream. The ontology is where table names would otherwise leak into the business.

Verify the properties and bindings, then the relationship types and their cardinality.
Note that upstream changes such as new rows need a manual refresh of the graph model
before they appear.

### Use it

Add the ontology as a second source to `Contoso Coffee Analyst`, then ask a
relationship-shaped question and compare against the pure semantic model answer. This is
the one case where a second source earns its place, because it answers a different shape
of question rather than duplicating the first. Ontology sources support agent instructions
and a data source description, but not schema selection, data source instructions, or
example queries.

Docs:
- https://learn.microsoft.com/fabric/iq/overview
- https://learn.microsoft.com/fabric/iq/ontology/overview
- https://learn.microsoft.com/fabric/iq/ontology/tutorial-0-introduction
- https://learn.microsoft.com/fabric/iq/ontology/tutorial-1-create-ontology
- https://learn.microsoft.com/fabric/iq/ontology/overview-tenant-settings

Next: [phase 8, validate](08-validate.md)
