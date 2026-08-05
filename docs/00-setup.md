# Phase 0. Setup

You are here if you have just cloned the repo and have not created any Fabric items yet.
Do this once. If you get setup wrong, the Copilot buttons will not appear and you will
not know why.

Budget 20 minutes, plus however long your admin takes.

---

## 1. Capacity

Copilot in Power BI needs a **paid F2 or higher** Fabric capacity, or **Power BI Premium
P1 or higher** with Fabric enabled.

Two things trip people up:

- **Trial capacities do not qualify.** A Fabric trial will let you build the lakehouse,
  the model, the report, and the data agent, but the Copilot button will not be there.
- After you buy or scale a capacity, it can take **up to 24 hours** for Copilot to
  appear.

A Power BI Pro or Premium Per User licence on its own is not enough. Capacity is what
matters.

Docs: https://learn.microsoft.com/power-bi/create-reports/copilot-enable-power-bi

---

## 2. Tenant settings

A Fabric administrator sets these in the admin portal, under tenant settings.

| Setting | Needed for | Default |
| --- | --- | --- |
| Users can use Copilot and other features powered by Azure OpenAI | Everything | On |
| Data sent to Azure OpenAI can be processed outside your capacity's geographic region, compliance boundary, or national cloud instance | Regions without local Azure OpenAI, and the data agent | Off |
| Data sent to Azure OpenAI can be stored outside your capacity's geographic region, compliance boundary, or national cloud instance | The data agent, outside the EU data boundary and the US | Off |
| Users can access a standalone, cross-item Power BI Copilot experience (preview) | Phase 6 standalone Copilot, and using a data agent from Copilot | On |
| Only show approved items in the standalone Copilot in Power BI experience (preview) | Optional, phase 4 | Off |
| Enable Ontology item (preview) | Phase 7 ontology, optional | Off |

Sovereign clouds are not supported. Private Link and closed network environments are not
supported.

Docs:
- https://learn.microsoft.com/power-bi/create-reports/copilot-enable-power-bi
- https://learn.microsoft.com/fabric/data-science/data-agent-tenant-settings

---

## 3. Local tools

| Tool | Why | Where |
| --- | --- | --- |
| Power BI Desktop, current release | Phases 3, 4, 5 | https://aka.ms/pbidesktopstore |
| VS Code | Phases 1, 2, 3, 8 | https://code.visualstudio.com |
| GitHub Copilot Chat extension | Phases 1, 2, 3, 8 | VS Code marketplace |
| Python 3.10 or later | The data generator and the ground truth script | https://python.org |

No pip installs. Both Python scripts in this repo use the standard library only.

---

## 4. MCP servers

Add these in VS Code. Each one takes about a minute.

### Fabric Core MCP Server (preview, remote)

Command Palette, `MCP: Add Server`, choose `HTTP`, paste:

```text
https://api.fabric.microsoft.com/v1/mcp/core
```

Name it `fabric`. A browser opens for Microsoft Entra ID sign in.

Or add it manually to `.vscode/mcp.json`:

```json
{
  "servers": {
    "fabric": {
      "type": "http",
      "url": "https://api.fabric.microsoft.com/v1/mcp/core"
    }
  }
}
```

Verify with this prompt in Copilot Chat:

```text
List all my Fabric workspaces
```

If it fails, remove and re-add the server, and confirm you have at least Viewer on one
workspace.

### Fabric MCP Server (preview, local)

Install the **Fabric MCP Server** extension from the VS Code marketplace
(`fabric.vscode-fabric-mcp-server`). It registers itself, there is nothing else to
configure. Alternatively run
`npx -y @microsoft/fabric-mcp@latest server start --mode all`.

Use it for OneLake file operations and offline Fabric API specs.

### Microsoft Learn MCP Server

Recommended. It is how you keep this demo honest, because preview features move and the
menus change. If your VS Code build supports it, add the Microsoft Learn MCP server so
Copilot can check current documentation rather than answer from memory.

### Power BI MCP server (preview, local), recommended for phase 3

Install the `analysis-services.powerbi-modeling-mcp` VS Code extension. It lets Copilot
edit a semantic model in natural language: measures, columns, relationships, data
categories, summarisation, plus DAX query validation. It works against Power BI Desktop,
a Fabric workspace model, or a PBIP/TMDL folder.

This is the fastest way to do [phase 3](03-model.md), and Learn lists "apply modeling
best practices in bulk" as a first-class use case. It writes, so it needs Write
permission on the model, it has a `--readonly` flag, and it is best pointed at a PBIP
folder in source control so every edit is a reviewable diff.

There is also a **remote** Power BI MCP server, for chatting with a published model
rather than authoring one. It needs a tenant setting enabled by an admin and its query
generation consumes Copilot capacity. Not required for this demo.

Source: https://github.com/microsoft/powerbi-modeling-mcp

Docs:
- https://learn.microsoft.com/power-bi/developer/mcp/mcp-servers-overview
- https://learn.microsoft.com/power-bi/developer/mcp/remote-mcp-server-get-started
- https://learn.microsoft.com/rest/api/fabric/articles/mcp-servers/what-is-fabric-mcp-server
- https://learn.microsoft.com/rest/api/fabric/articles/mcp-servers/core-remote/get-started-core
- https://learn.microsoft.com/rest/api/fabric/articles/mcp-servers/pro-dev-local/get-started-local

---

## 5. The data

```bash
python data/generate_data.py
```

Expected output:

```text
dim_date.csv     rows=    731
dim_product.csv  rows=     12
dim_store.csv    rows=      8
fact_sales.csv   rows=  64335
total net revenue = 412,918.50
total gross margin = 283,482.20 (68.65%)
```

The CSVs are already committed, so you can skip this and upload them directly. Running
the generator proves the data is synthetic and reproducible, which is worth doing once.

---

## Checklist before phase 1

- [ ] Paid F2 or higher, or P1 or higher. Not a trial.
- [ ] Copilot tenant setting on
- [ ] Cross-geo settings on, if your region needs them
- [ ] Standalone Copilot tenant setting on
- [ ] Power BI Desktop installed and up to date
- [ ] VS Code with GitHub Copilot Chat
- [ ] Fabric Core MCP connected, and `List all my Fabric workspaces` works
- [ ] `python data/generate_data.py` runs and prints the numbers above

Next: [phase 1, provision](01-provision.md)
