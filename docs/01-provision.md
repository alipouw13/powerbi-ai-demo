# Phase 1. Provision with Fabric MCP

**Agent:** `fabric-provisioner`
**Time:** 10 minutes
**AI on show:** Fabric Core MCP Server, preview, driven from GitHub Copilot Chat

The point of this phase is not that a workspace got created. It is that it got created
from a sentence, with your identity, your permissions, and an audit trail.

---

## What the Fabric MCP servers are

Two servers, and they do different jobs.

| | Core, remote | Local |
| --- | --- | --- |
| Install | None, it is a URL | VS Code extension |
| Workspace management | Yes | No |
| Item CRUD | Yes | Create only |
| Permissions and roles | Yes | No |
| OneLake file operations | No | Yes |
| Offline API specs | No | Yes |
| Audit logged | Yes | No |
| Open source | No | Yes |

You can run both at once. This phase uses Core.

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

**4. Verify.** Do not accept "created successfully". Make it list the items back, and
then look at the workspace in the Fabric portal. This habit is what separates a demo
from a claim.

---

## Worth showing

Ask for something you are not allowed to do:

```text
List all role assignments for a workspace I do not have access to.
```

It fails, because the MCP server is calling the Fabric REST API as you. That failure is
a better security demo than any slide.

---

## Tools Core exposes

`search_catalog`, `list_workspaces`, `get_workspace`, `create_workspace`,
`update_workspace`, `delete_workspace`, workspace role add, list, get, update and
delete, `list_items`, `get_item`, `create_item`, `update_item`, `delete_item`,
`get_item_definition`, `update_item_definition`, `bulk_move_items`, folder create, list,
get, update, delete and move, `list_capacities`, `get_operation_state`,
`get_operation_result`, `get_knowledge`.

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
