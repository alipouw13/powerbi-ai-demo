"""Generate fabric/agent_remediate_agent.ipynb, the agent instruction path.

A separate notebook from `agent_remediate`, and the separation is the point.

Applying an instruction to the data agent used to need `fabric-data-agent-sdk`,
which meant a `%pip install`. That is now gone, because it did exactly what
this repo had already been bitten by once: the first version of the eval
notebook installed `mcp`, which pulled new builds of pydantic, anyio,
typing-extensions and jsonschema over the ones the Spark runtime ships, and the
scheduled job died in twelve seconds.

This notebook died the same way, in ten. The first real agent-targeted approval
mirrored cleanly, `agent_remediate` handed off, and the reference run was
cancelled with `System_Cancelled_Session_Statements_Failed` before it reached a
single line of its own code. The handoff caught it, printed it, and left the
approval open, so the only visible symptom was an agent that never changed.

So there is no install any more. Everything the SDK was used for is three
plain REST calls against the public Fabric API, which is what the SDK does
underneath, and the notebook now has no dependency the Spark runtime does not
already ship:

    GET   /v1/workspaces/{ws}/dataAgents/{id}/staging/settings
    PATCH /v1/workspaces/{ws}/dataAgents/{id}/staging/settings
    POST  /v1/workspaces/{ws}/dataAgents/{id}/staging/publish
    GET   /v1/workspaces/{ws}/dataAgents/{id}/settings     (published)

The notebook stays separate from `agent_remediate` anyway. It writes to a
different governed item, it is only reached when there is agent-targeted work,
and a failure here must not fail a run whose semantic model work has landed.

## What an agent instruction can and cannot do

Agent-level instructions are applied after the query has run. They change how
an answer reads. They are not passed to the DAX generation step, so they
cannot change a number, a filter or a grouping.

That is why `eval_harness.agent_target_is_safe` exists and why this notebook
re-checks the target rather than trusting the approval. A model-class fix
applied here would be approved, recorded as persisted, and change nothing,
which is the most expensive kind of wrong because it looks like progress.

## Staging is not the agent

A data agent has two configurations. The PATCH above writes **staging**, which
is the draft nobody queries. The published configuration, which is what the
MCP endpoint answers from and what a person sees in the agent, only changes
when something calls the publish endpoint.

The first version of this notebook wrote staging and stopped, so two approved
instructions were recorded as applied and the agent never changed. It also
read back through `get_configuration`, the deprecated workload-host API, whose
`instructions` come from a different field (`additionalInstructions`) than the
one the write lands in (`aiInstructions`). The read back therefore could not
see the write it was checking, and the exception it raised was swallowed by
the caller's handoff.

So this notebook now uses one plane end to end: read staging, write staging,
read staging again, publish, and finally read **published**. Nothing is
recorded as persisted until the instruction is readable in the published
configuration.

Run:
    python validation/build_agent_remediation_notebook.py
"""

from __future__ import annotations

import json

from build_eval_notebook import (  # noqa: E402
    DATA_AGENT_ID,
    KUSTO_DB,
    KUSTO_URI,
    ROOT,
    WORKSPACE_ID,
    code,
    md,
)

NOTEBOOK_PATH = ROOT / "fabric" / "agent_remediate_agent.ipynb"

# The heading the loop writes under, matching the model path so that a person
# reading either set of instructions can see which lines were added by an
# approval and which a human wrote.
AGENT_HEADING = "## Automated remediation"


PARAMETERS_CELL = f'''WORKSPACE_ID = "{WORKSPACE_ID}"
DATA_AGENT_ID = "{DATA_AGENT_ID}"
DATA_AGENT_NAME = ""  # the item's display name, which the SDK also takes
KUSTO_URI = "{KUSTO_URI}"
KUSTO_DB = "{KUSTO_DB}"

# Which approvals to apply. agent_remediate passes these, comma separated.
APPROVAL_IDS = ""
APPROVED_BY = ""

# Coerced below rather than trusted. A parameter injected by a reference run
# arrives as the string "false", and a non-empty string is truthy in Python.
DRY_RUN = True
'''


READ_CELL = '''import json
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

import notebookutils

DRY_RUN = str(DRY_RUN).strip().lower() not in ("false", "0", "no", "")
print(f"DRY_RUN resolved to {DRY_RUN}")

if not APPROVED_BY.strip():
    raise ValueError(
        "APPROVED_BY is empty. A governed change records who approved it, so "
        "this refuses rather than guessing who you are.\\n"
        "\\n"
        "This notebook is normally reached by agent_remediate, which passes "
        "APPROVED_BY through. If you are running it directly, set it in the "
        "parameters cell above, along with the APPROVAL_IDS you mean to "
        "apply."
    )

TARGET_DATA_AGENT = "data_agent"

kusto_token = notebookutils.credentials.getToken(KUSTO_URI)


def kusto(csl, endpoint="query"):
    request = urllib.request.Request(
        f"{KUSTO_URI}/v1/rest/{endpoint}",
        data=json.dumps({"db": KUSTO_DB, "csl": csl}).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {kusto_token}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def rows(result):
    table = result["Tables"][0]
    names = [c["ColumnName"] for c in table["Columns"]]
    return [dict(zip(names, row)) for row in table["Rows"]]


wanted = [a.strip() for a in APPROVAL_IDS.split(",") if a.strip()]
if not wanted:
    print("no approval ids passed, nothing to do")
    pending = []
else:
    quoted = ", ".join(f'"{a}"' for a in wanted)
    pending = rows(kusto(f"""
        eval_approvals
        | where approval_id in ({quoted})
        | where decision == "approved"
        | join kind=leftanti (
            eval_remediations
            | where persisted == true
            | distinct approval_id
          ) on approval_id
    """))

# Re-checked rather than trusted. The caller already filtered by target, but
# this notebook writes to a governed item and a caller that got it wrong would
# otherwise apply a model-class fix somewhere it can never work.
misrouted = [r for r in pending if r["instruction_target"] != TARGET_DATA_AGENT]
if misrouted:
    raise ValueError(
        f"{len(misrouted)} approval(s) are not agent targeted: "
        + ", ".join(r["question_id"] for r in misrouted)
        + ". Agent instructions are applied after the query has run and cannot "
        "change a value, so applying these here would look like a change and "
        "do nothing."
    )

print(f"{len(pending)} agent-targeted approval(s) to apply")
for row in pending:
    print(f"  {row['question_id']} by {row['approved_by']}")
    print(f"      {row['proposed_instruction'][:160]}")
'''


APPLY_CELL = '''AGENT_HEADING = "__AGENT_HEADING__"

FABRIC_API = "https://api.fabric.microsoft.com"
AGENT_URL = f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/dataAgents/{DATA_AGENT_ID}"

# "pbi" rather than the Fabric hostname. The Fabric REST API accepts a token
# issued for the Power BI audience, and that audience is the one notebookutils
# reliably mints inside a reference run.
fabric_token = notebookutils.credentials.getToken("pbi")

# The field the public Data Agent API carries instructions in. The staging
# PATCH writes it; both settings reads return it.
AI_INSTRUCTIONS = "aiInstructions"
# What the deprecated workload-host API called the same thing. Read as a
# fallback so an agent last configured through the old plane is not mistaken
# for one that has no instructions.
LEGACY_INSTRUCTIONS = "additionalInstructions"


def agent_api(method, path, body=None):
    """One call against the data agent, returning (status, parsed body).

    Written on urllib rather than the SDK on purpose. Installing
    fabric-data-agent-sdk at run time cancelled this notebook's Spark session
    in ten seconds, every time, before any of its own code ran.
    """
    request = urllib.request.Request(
        AGENT_URL + path,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        method=method,
        headers={"Authorization": f"Bearer {fabric_token}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            text = response.read().decode("utf-8")
            return response.status, (json.loads(text) if text.strip() else {})
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": exc.read().decode("utf-8")[:600]}


def merge_instruction(existing, instruction):
    """Append one line under the loop's heading, idempotently.

    The same shape as the model path: never rewrite or delete text a human
    wrote, and adding a line that is already there is a no-op rather than a
    duplicate.
    """
    existing = existing or ""
    if instruction.strip() and instruction.strip() in existing:
        return existing, False
    if AGENT_HEADING in existing:
        return existing.rstrip() + "\\n" + instruction + "\\n", True
    separator = "\\n\\n" if existing.strip() else ""
    return (
        existing.rstrip() + separator + AGENT_HEADING + "\\n\\n"
        + "Added by the evaluation loop after a human approved each line.\\n\\n"
        + instruction + "\\n"
    ), True


def instructions_of(settings):
    """The instruction text in a settings payload, or None if unreadable.

    An agent that has never been given instructions answers with a payload
    that simply has no such key, and that is empty rather than unreadable.
    The difference decides whether this notebook writes or refuses, so it is
    made here once instead of being guessed at three call sites.
    """
    if not isinstance(settings, dict):
        return None
    for key in (AI_INSTRUCTIONS, LEGACY_INSTRUCTIONS):
        if key in settings:
            return settings[key] or ""
    return "" if settings else None


def read_stage(stage):
    """Instructions for one stage, or None when the stage cannot be read.

    A never-published agent has no published settings to return, and that is
    a fact about the agent rather than a failure of this run.
    """
    path = "/staging/settings" if stage == "staging" else "/settings"
    status, body = agent_api("GET", path)
    if status != 200:
        print(f"could not read {stage} settings: {status} {body.get('error', '')}")
        return None
    return instructions_of(body)


applied = []          # rows this run put into the published agent
already_present = []  # rows whose sentence was already published
published_after = None

if pending:
    # Read before write. The staging PATCH replaces the whole instruction
    # value, so a run that cannot establish what is there now refuses rather
    # than overwriting whatever a person wrote by hand.
    staging_current = read_stage("staging")
    if staging_current is None:
        raise ValueError(
            "Could not read the agent's staging settings, so this run will "
            "not write. The write replaces the whole value, and writing "
            "without a reliable read would delete whatever a person wrote by "
            "hand."
        )

    # Published is the one that matters. Staging is a draft that nobody
    # queries: an instruction that reached staging and was never published has
    # changed nothing, and treating it as applied is exactly how this loop
    # reported two fixes it had not made.
    published_current = read_stage("published")
    if published_current is None:
        print("no published settings yet, so this run publishes for the first time")
        published_current = ""

    proposed = staging_current
    for row in pending:
        instruction = (row["proposed_instruction"] or "").strip()
        proposed, _ = merge_instruction(proposed, instruction)
        if instruction and instruction in published_current:
            # Already live. The approval is satisfied, nothing is written, and
            # the person is told rather than left to wonder why the diff was
            # empty.
            already_present.append(row)
            print(f"already published, nothing to add for {row['question_id']}")
        else:
            applied.append(row)

    print()
    print("--- published now ---")
    print(published_current[-600:] if published_current else "(empty)")
    print("--- proposed ---")
    print(proposed[-600:])
    print()
    print(f"{len(applied)} to publish, {len(already_present)} already published")

    if not applied:
        print("nothing to write, and nothing to publish")
    elif DRY_RUN:
        print("DRY_RUN, nothing written and nothing published")
    else:
        if proposed != staging_current:
            status, body = agent_api(
                "PATCH", "/staging/settings", {AI_INSTRUCTIONS: proposed}
            )
            if status not in (200, 201, 202, 204):
                raise RuntimeError(
                    f"writing the agent's staging instructions returned {status}: "
                    f"{body.get('error', '')}. Nothing is recorded as applied."
                )
            staging_after = read_stage("staging")
            if staging_after != proposed:
                raise RuntimeError(
                    "the staging write did not land. The agent's staging "
                    "instructions read back differently from what was sent, "
                    "so nothing is recorded as applied."
                )
            print("staging updated")
        else:
            # The sentence is in staging already and not in published, which
            # is what an earlier run that wrote staging and never published
            # leaves behind. Publishing is the whole fix.
            print("staging already carries the text, so this run only publishes")

        # The step this notebook used to be missing. The PATCH touches the
        # draft; the agent people and the MCP endpoint answer from does not
        # change until the draft is published.
        #
        # publishedDescription, not description. The endpoint accepts both and
        # silently ignores the latter, which is how a publish can look
        # recorded and carry no note at all.
        status, body = agent_api("POST", "/staging/publish", {
            "publishedDescription":
                f"Evaluation loop remediation approved by {APPROVED_BY}"
        })
        if status not in (200, 201, 202, 204):
            raise RuntimeError(
                f"publishing the agent's staging configuration returned {status}: "
                f"{body.get('error', '')}. The instruction is in staging, which "
                "nobody queries, so nothing is recorded as applied."
            )

        published_after = read_stage("published")
        if published_after is None:
            raise RuntimeError(
                "published the staging configuration but could not read the "
                "published settings back, so this run cannot claim the agent "
                "changed. Nothing is recorded as applied."
            )

        missing = [
            row["question_id"] for row in applied
            if (row["proposed_instruction"] or "").strip() not in published_after
        ]
        if missing:
            raise RuntimeError(
                "the publish did not carry every approved instruction. "
                f"Missing from the published agent: {', '.join(missing)}. "
                "Nothing is recorded as applied. The usual cause is that the "
                "identity running this notebook can read the data agent but "
                "not write it, which is a silent no-op rather than an error."
            )
        print("publish verified against the published configuration")
'''


RECORD_CELL = '''# Recorded to the same table as the model path, so the dashboard and the
# report show one history rather than two. verified stays false until an
# evaluation run proves the question actually improved.
try:
    executing_identity = notebookutils.runtime.context.get("userName", "unknown")
except Exception:  # noqa: BLE001
    executing_identity = "unknown"

now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def escape(value):
    return (value or "").replace("\\\\", "\\\\\\\\").replace('"', '\\\\"')


def record(row, wrote_something):
    """One remediation row.

    `applied_ts` is null when this run wrote nothing because the sentence was
    already in the published agent. That is what the column has always meant,
    it needs no new schema anywhere, and it is what lets the report separate
    "we changed the agent" from "the agent already said this".

    `backup_path` is empty rather than absent. The model path writes that
    column, and `.set-or-append` requires the same schema as the table it is
    appending to, so a shorter row here would fail against a table the other
    notebook created.
    """
    applied_ts = f"datetime({now})" if wrote_something else "datetime(null)"
    kusto(
        ".set-or-append eval_remediations <| print "
        f'remediation_id="{uuid.uuid4()}", '
        f"recorded_ts=datetime({now}), "
        f"applied_ts={applied_ts}, "
        f'approval_id="{escape(row["approval_id"])}", '
        f'question_id="{escape(row["question_id"])}", '
        f'instruction_target="{escape(row["instruction_target"])}", '
        f'instruction="{escape(row["proposed_instruction"])}", '
        f'approved_by="{escape(row["approved_by"])}", '
        f'applied_by="{escape(executing_identity)}", '
        'dry_run=false, backup_path="", persisted=true, verified=false, '
        'verified_ts=datetime(null), verified_run_id=""',
        endpoint="mgmt",
    )


written = 0
# A sentence that was already published satisfies its approval just as much as
# one this run added. Without this the approval would sit open forever and
# nobody would be prompted about it again.
for row, wrote_something in (
    [(r, True) for r in applied] + [(r, False) for r in already_present]
):
    if DRY_RUN:
        print(f"DRY_RUN, not recording {row['question_id']}")
        continue
    record(row, wrote_something)
    written += 1

print(f"recorded {written} remediation(s)")
if already_present:
    print()
    print("Nothing was written to the agent for "
          + ", ".join(sorted({r["question_id"] for r in already_present}))
          + ". The approved sentence was already in the published agent "
          "instructions, so re-applying it would have changed nothing. Those "
          "approvals are closed rather than left open, and they are recorded "
          "with no applied time so the report can show them as already "
          "present.")
print("verified stays false until an evaluation run proves the fix worked")
'''


def build_cells() -> list[dict]:
    cells: list[dict] = []

    cells.append(md(
        "# Apply an approved agent instruction\n"
        "\n"
        "The narrow half of the remediation loop. This notebook is **generated**;\n"
        "edit `validation/build_agent_remediation_notebook.py` and regenerate.\n"
        "\n"
        "## Why this is separate from agent_remediate\n"
        "\n"
        "It writes to a different governed item, and a failure here must not\n"
        "fail a run whose semantic model work has already landed.\n"
        "\n"
        "`agent_remediate` reaches this with `notebookutils.notebook.run()`, a\n"
        "reference run in its own session, and only when there is agent-targeted\n"
        "work to do.\n"
        "\n"
        "## No install\n"
        "\n"
        "This notebook used to `%pip install fabric-data-agent-sdk`. That\n"
        "cancelled its Spark session in ten seconds on the first real\n"
        "agent-targeted approval, before a line of its own code ran, and the\n"
        "caller's handoff caught the failure and left the approval open. The\n"
        "only visible symptom was an agent that never changed.\n"
        "\n"
        "The SDK is now gone. Everything it was used for is three plain REST\n"
        "calls against the public Fabric API, which is what the SDK does\n"
        "underneath.\n"
        "\n"
        "## What an agent instruction can change\n"
        "\n"
        "How an answer reads, and nothing else. Agent instructions are applied\n"
        "after the query has run, so they cannot change a value, a filter or a\n"
        "grouping. This notebook re-checks `instruction_target` rather than\n"
        "trusting its caller, because a model-class fix applied here would be\n"
        "recorded as persisted and change nothing.\n"
        "\n"
        "## Staging is not the agent\n"
        "\n"
        "The write PATCHes the **staging** configuration, which is a draft\n"
        "nobody queries. The published configuration is what the MCP endpoint\n"
        "answers from and what a person sees in the agent, and it only changes\n"
        "when something calls the publish endpoint.\n"
        "\n"
        "An earlier version of this notebook wrote staging and stopped, and read\n"
        "back through the deprecated `get_configuration`, which reads a\n"
        "different field again. Approvals were recorded as applied and the agent\n"
        "never changed. Everything here now goes through one plane: read\n"
        "staging, write staging, publish, read published.\n"
        "\n"
        "## What it will not do\n"
        "\n"
        "- Write without a named approver\n"
        "- Replace instructions it could not first read\n"
        "- Rewrite or delete text a human wrote. It appends under one heading\n"
        "- Write a sentence the published agent already carries\n"
        "- Record anything as applied unless it reads back from the **published**\n"
        "  configuration\n"
    ))

    cells.append(md("## 1. Parameters"))
    cells.append({
        "cell_type": "code",
        "execution_count": None,
        "metadata": {"tags": ["parameters"]},
        "outputs": [],
        "source": PARAMETERS_CELL.splitlines(True),
    })

    cells.append(md(
        "## 2. Find the approved work\n"
        "\n"
        "By approval id, passed in by the caller, and re-filtered here so a\n"
        "stale or already applied id cannot be applied twice."
    ))
    cells.append(code(READ_CELL))

    cells.append(md(
        "## 3. Merge, apply and publish\n"
        "\n"
        "The staging write replaces the whole instruction value, so the current\n"
        "text is read first and appended to. A run that cannot read it refuses.\n"
        "\n"
        "The write goes to staging and is then **published**, because staging is\n"
        "a draft and the agent people query is the published one. A sentence\n"
        "already in the published configuration is not written again; it is\n"
        "reported and its approval is closed.\n"
        "\n"
        "Three plain REST calls, and no `%pip install`. The data agent SDK does\n"
        "the same three calls underneath, and installing it cancelled this\n"
        "notebook's Spark session in ten seconds before any of its own code ran."
    ))
    cells.append(code(APPLY_CELL.replace("__AGENT_HEADING__", AGENT_HEADING)))

    cells.append(md(
        "## 4. Record what happened\n"
        "\n"
        "Into `eval_remediations`, the same table the model path writes, so the\n"
        "loop has one history. The mirror pipeline carries it back to SQL for\n"
        "the report. `outcome` separates a sentence this run published from one\n"
        "the agent already carried."
    ))
    cells.append(code(RECORD_CELL))

    return cells


def build_notebook() -> dict:
    return {
        "cells": build_cells(),
        "metadata": {
            "kernelspec": {"display_name": "Synapse PySpark",
                           "language": "Python", "name": "synapse_pyspark"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def main() -> None:
    NOTEBOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
    notebook = build_notebook()
    NOTEBOOK_PATH.write_text(
        json.dumps(notebook, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {NOTEBOOK_PATH.relative_to(ROOT)} with {len(notebook['cells'])} cells")


if __name__ == "__main__":
    main()
