# Phase 1. Provision with Fabric MCP

**Agent:** `fabric-provisioner`
**Time:** 10 minutes
**AI on show:** Fabric Core MCP Server (preview), driven from GitHub Copilot Chat

The point of this phase is not that a workspace got created. It is that it got created
from a sentence, with your identity, your permissions, and an audit trail.

Start here after [phase 0](00-setup.md), when the Fabric Core MCP Server (preview) is
connected in VS Code and `List all my Fabric workspaces` returns a real workspace list.

---

## What the Fabric MCP servers are

Two servers, and they do different jobs.

| | Core (preview, remote) | Local (preview) |
| --- | --- | --- |
| Install | None, it is a URL | VS Code extension |
| Workspace management | Yes | No |
| Item CRUD | Yes | Create only |
| Permissions and roles | Yes | No |
| OneLake file operations | No | Yes |
| Offline API specs | No | Yes |
| Audit logged | Yes | No |
| Open source | No | Yes |

You can run both at once. This phase uses Core (preview, remote).

Both enforce your existing Fabric RBAC. Neither grants any permission you do not already
have. Core actions appear in Fabric audit logs against your user identity. Say this out
loud when you demo it, because it is the first question every security-minded person in
the room will ask.

---

## Steps

Open GitHub Copilot Chat in VS Code.

**1. Prove the connection.**

```text
List all my Fabric workspaces.
```

If this returns nothing useful, fix it before going further. Remove and re-add the MCP
server, and confirm you have at least Viewer on one workspace.

**2. Check your capacity.**

```text
Which of my capacities support Copilot in Power BI? Copilot needs a paid F2 or higher,
or P1 or higher. Trial capacities do not qualify.
```

**3. Create the workspace and lakehouse.**

```text
Create a Fabric workspace called "Contoso Coffee AI Demo" and assign it to a capacity
that supports Copilot. Then create a lakehouse called "LH_ContosoCoffee" inside it.
When you are done, list the items in the workspace so I can verify.
```

**4. Verify.** Do not accept "created successfully". Make it list the items back, then
open the workspace in the Fabric portal and confirm you can see:

- Workspace: `Contoso Coffee AI Demo`
- Lakehouse: `LH_ContosoCoffee`

---

## Worth showing

Ask for something you are not allowed to do:

```text
List all role assignments for a workspace I do not have access to.
```

It fails, because the MCP server is calling the Fabric REST API as you. That failure is
a better security demo than any slide.

---

## Tool reference

If someone asks what Core can do, show the Microsoft Learn tool reference rather than
reciting a stale list. For this phase, the important tools are workspace, capacity,
lakehouse item, role assignment, and operation-status tools.

---

## If it does not work

| Symptom | Fix |
| --- | --- |
| No tools appear | Remove and re-add the MCP server, then reload VS Code |
| Auth loop | Sign out of the browser profile VS Code opened and try again |
| Empty workspace list | You have no workspace access, ask for at least Viewer |
| Creation succeeds, item not visible | Refresh the portal, and check you looked in the right workspace |

---

Docs:
- https://learn.microsoft.com/rest/api/fabric/articles/mcp-servers/what-is-fabric-mcp-server
- https://learn.microsoft.com/rest/api/fabric/articles/mcp-servers/core-remote/get-started-core
- https://learn.microsoft.com/rest/api/fabric/articles/mcp-servers/core-remote/tools-core-mcp-server

Next: [phase 2, load](02-load.md)
