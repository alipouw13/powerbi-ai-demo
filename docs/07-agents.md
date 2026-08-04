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

### Build it

1. In the workspace, `+ New item`, search `Fabric data agent`, select it.
2. Name it `Contoso Coffee Analyst`.
3. The OneLake catalog opens. Add two sources: the `ContosoCoffee` semantic model, and
   the `LH_ContosoCoffee` lakehouse. An agent supports up to five sources in any
   combination.
4. In the Explorer pane, tick the tables the agent may use. Only tables are selectable,
   not files. This is why phase 2 insisted on loading to tables.
5. `Data agent instructions`. Route the questions. The text to paste is in
   [`.github/prompts/README.md`](../.github/prompts/README.md), phase 7.
6. `Example queries`. Add pairs for the **lakehouse** source. Example pairs are **not
   supported for Power BI semantic model sources**. For the model, verified answers in
   Prep data for AI are the equivalent, which is another reason phase 4 comes first.
7. Test in the chat canvas.
8. `Publish`. Write a real description. It becomes the MCP tool description and the
   Microsoft 365 Copilot description, so it is how other systems decide to call your
   agent.

### How it answers

The agent picks a source, then generates a query with the matching translator:

| Source | Translator |
| --- | --- |
| Power BI semantic model | NL2DAX, over the XMLA endpoint |
| Lakehouse or warehouse | NL2SQL |
| KQL database | NL2KQL |

It validates the query, executes it **read only** under the calling user's permissions,
and formats the result.

### Two things that surprise people

1. For a semantic model source, only **Read** permission is required. Build permission is
   not needed for agent-driven queries.
2. **Agent-level instructions are not passed to the DAX generation step.** For semantic
   model questions, what shapes the answer is the Prep data for AI configuration on the
   model. Phase 4 is doing the work, not the instruction box.

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
is a far more interesting comparison than either alone.

Docs:
- https://learn.microsoft.com/fabric/data-science/concept-data-agent
- https://learn.microsoft.com/fabric/data-science/how-to-create-data-agent
- https://learn.microsoft.com/fabric/data-science/data-agent-tenant-settings
- https://learn.microsoft.com/fabric/data-science/semantic-model-best-practices

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
| Property | A named fact with a type | `Store.region` |
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

Generated entity types are named after the tables, so you get `fact_sales`, `dim_store`,
`dim_product`. Rename them to `Sale`, `Store`, `Product`.

That rename is the whole lesson. The ontology is where table names stop leaking into the
business.

Verify the properties and bindings, then the relationship types and their cardinality.
Note that upstream changes such as new rows need a manual refresh of the graph model
before they appear.

### Use it

Add the ontology as a source to `Contoso Coffee Analyst`, then ask a relationship-shaped
question and compare against the pure semantic model answer. Ontology sources support
agent instructions and a data source description, but not schema selection, data source
instructions, or example queries.

Docs:
- https://learn.microsoft.com/fabric/iq/overview
- https://learn.microsoft.com/fabric/iq/ontology/overview
- https://learn.microsoft.com/fabric/iq/ontology/tutorial-0-introduction
- https://learn.microsoft.com/fabric/iq/ontology/tutorial-1-create-ontology
- https://learn.microsoft.com/fabric/iq/ontology/overview-tenant-settings

Next: [phase 8, validate](08-validate.md)
