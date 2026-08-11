"""Generate fabric/agent_remediate_agent.ipynb, the agent instruction path.

A separate notebook from `agent_remediate`, and the separation is the point.

Applying an instruction to the data agent needs `fabric-data-agent-sdk`, which
means a `%pip install`. This repo has already been bitten by that once: the
first version of the eval notebook installed `mcp`, which pulled new builds of
pydantic, anyio, typing-extensions and jsonschema over the ones the Spark
runtime ships, and the scheduled job died in twelve seconds.

So the install is confined here. `agent_remediate` calls this notebook with
`notebookutils.notebook.run()`, which is a reference run as a separate batch
job rather than `%run`, which would share the execution context and take the
dependency risk with it. And it only calls it when there is agent-targeted
work, which for most runs there is not.

## What an agent instruction can and cannot do

Agent-level instructions are applied after the query has run. They change how
an answer reads. They are not passed to the DAX generation step, so they
cannot change a number, a filter or a grouping.

That is why `eval_harness.agent_target_is_safe` exists and why this notebook
re-checks the target rather than trusting the approval. A model-class fix
applied here would be approved, recorded as persisted, and change nothing,
which is the most expensive kind of wrong because it looks like progress.

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
DATA_AGENT_NAME = ""  # the item's display name, which the SDK takes
KUSTO_URI = "{KUSTO_URI}"
KUSTO_DB = "{KUSTO_DB}"

# Which approvals to apply. agent_remediate passes these, comma separated.
APPROVAL_IDS = ""
APPROVED_BY = ""

# Coerced below rather than trusted. A parameter injected by a reference run
# arrives as the string "false", and a non-empty string is truthy in Python.
DRY_RUN = True
'''


INSTALL_CELL = '''%pip install -q -U fabric-data-agent-sdk
'''


READ_CELL = '''import json
import urllib.request
import uuid
from datetime import datetime, timezone

import notebookutils

DRY_RUN = str(DRY_RUN).strip().lower() not in ("false", "0", "no", "")
print(f"DRY_RUN resolved to {DRY_RUN}")

if not APPROVED_BY.strip():
    raise ValueError(
        "APPROVED_BY is empty. A governed change records who approved it."
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


APPLY_CELL = '''from fabric.dataagent.client import FabricDataAgentManagement

AGENT_HEADING = "__AGENT_HEADING__"


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


applied = []
if pending:
    agent = FabricDataAgentManagement(DATA_AGENT_NAME or DATA_AGENT_ID)

    # Read before write. If the current instructions cannot be established,
    # this refuses rather than replacing them: update_settings sets the whole
    # value, so a wrong read here would silently delete whatever a person had
    # written by hand.
    configuration = agent.get_configuration()
    current = getattr(configuration, "instructions", None)
    if current is None:
        current = getattr(configuration, "ai_instructions", None)
    if current is None and isinstance(getattr(configuration, "value", None), dict):
        current = configuration.value.get("instructions")
    if current is None:
        raise ValueError(
            "Could not read the agent's current instructions, so this run will "
            "not write. update_settings replaces the whole value, and writing "
            "without a reliable read would delete whatever a person wrote by "
            "hand. Inspect get_configuration() and update this cell."
        )

    proposed = current
    for row in pending:
        proposed, changed = merge_instruction(proposed, row["proposed_instruction"])
        if not changed:
            print(f"already present, nothing to add for {row['question_id']}")
        applied.append(row)

    print("--- current ---")
    print(current[-600:] if current else "(empty)")
    print("--- proposed ---")
    print(proposed[-600:])

    if DRY_RUN:
        print("\\nDRY_RUN, nothing written")
    elif proposed == current:
        print("\\nno change to write")
    else:
        agent.update_settings(ai_instructions=proposed)

        # Read back. execute-and-hope is not evidence, and the identity this
        # runs as may not have write access to the agent, which produces a
        # silent no-op rather than an error.
        after = agent.get_configuration()
        landed = getattr(after, "instructions", None) or getattr(
            after, "ai_instructions", None
        )
        if landed != proposed:
            raise RuntimeError(
                "the write did not land. The agent instructions read back "
                "differently from what was sent, so nothing is recorded as "
                "applied."
            )
        print("\\nwrite verified")
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


written = 0
for row in applied:
    if DRY_RUN:
        print(f"DRY_RUN, not recording {row['question_id']}")
        continue
    kusto(
        ".set-or-append eval_remediations <| print "
        f'remediation_id="{uuid.uuid4()}", '
        f"recorded_ts=datetime({now}), "
        f"applied_ts=datetime({now}), "
        f'approval_id="{escape(row["approval_id"])}", '
        f'question_id="{escape(row["question_id"])}", '
        f'instruction_target="{escape(row["instruction_target"])}", '
        f'instruction="{escape(row["proposed_instruction"])}", '
        f'approved_by="{escape(row["approved_by"])}", '
        f'applied_by="{escape(executing_identity)}", '
        "dry_run=false, persisted=true, verified=false, "
        "verified_ts=datetime(null), verified_run_id=\\"\\"",
        endpoint="mgmt",
    )
    written += 1

print(f"recorded {written} remediation(s)")
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
        "It installs `fabric-data-agent-sdk` at run time. The repo has already\n"
        "lost a scheduled job to a `%pip install` pulling new builds of pydantic\n"
        "and anyio over the ones the Spark runtime ships, so that risk is kept\n"
        "away from the path that writes to the semantic model.\n"
        "\n"
        "`agent_remediate` reaches this with `notebookutils.notebook.run()`, a\n"
        "reference run in its own session, and only when there is agent-targeted\n"
        "work to do.\n"
        "\n"
        "## What an agent instruction can change\n"
        "\n"
        "How an answer reads, and nothing else. Agent instructions are applied\n"
        "after the query has run, so they cannot change a value, a filter or a\n"
        "grouping. This notebook re-checks `instruction_target` rather than\n"
        "trusting its caller, because a model-class fix applied here would be\n"
        "recorded as persisted and change nothing.\n"
        "\n"
        "## What it will not do\n"
        "\n"
        "- Write without a named approver\n"
        "- Replace instructions it could not first read\n"
        "- Rewrite or delete text a human wrote. It appends under one heading\n"
        "- Record anything as applied unless the write read back identically\n"
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
        "## 2. The SDK\n"
        "\n"
        "The one place in this repo that installs anything at run time. It is\n"
        "here rather than in `agent_remediate` because a dependency that breaks\n"
        "the Spark runtime must not be able to break the path that writes to the\n"
        "semantic model, and this notebook is reached by a reference run rather\n"
        "than `%run`, so it gets its own session."
    ))
    cells.append(code(INSTALL_CELL))

    cells.append(md(
        "## 3. Find the approved work\n"
        "\n"
        "By approval id, passed in by the caller, and re-filtered here so a\n"
        "stale or already applied id cannot be applied twice."
    ))
    cells.append(code(READ_CELL))

    cells.append(md(
        "## 4. Merge and apply\n"
        "\n"
        "`update_settings` replaces the whole instruction value, so the current\n"
        "text is read first and appended to. A run that cannot read it refuses."
    ))
    cells.append(code(APPLY_CELL.replace("__AGENT_HEADING__", AGENT_HEADING)))

    cells.append(md(
        "## 5. Record what happened\n"
        "\n"
        "Into `eval_remediations`, the same table the model path writes, so the\n"
        "loop has one history. The mirror pipeline carries it back to SQL for\n"
        "the report."
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
