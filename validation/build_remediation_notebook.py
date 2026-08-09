"""Generate fabric/agent_remediate.ipynb, the approval and apply notebook.

Separate from the eval notebook on purpose. Evaluation is read only and runs
on a schedule. Remediation writes to a governed semantic model and runs only
when a human has approved a specific line of text. Keeping them in one
notebook would mean a scheduled job holds write access to the model every
night for no reason.

Run:
    python validation/build_remediation_notebook.py
"""

from __future__ import annotations

import json

from build_eval_notebook import (  # noqa: E402
    DATA_AGENT_ID,
    KUSTO_DB,
    KUSTO_URI,
    LAKEHOUSE_ID,
    LAKEHOUSE_NAME,
    NOTEBOOK_PATH as EVAL_NOTEBOOK_PATH,
    ROOT,
    WORKSPACE_ID,
    code,
    md,
    read,
    strip_module_docstring,
)

SEMANTIC_MODEL_NAME = "ContosoCoffee"
NOTEBOOK_PATH = ROOT / "fabric" / "agent_remediate.ipynb"


def build_cells() -> list[dict]:
    harness = strip_module_docstring(read("eval_harness.py"))
    cells: list[dict] = []

    cells.append(md(
        "# Apply an approved remediation\n"
        "\n"
        "Reads a defect that a human has approved, appends the approved instruction\n"
        "to the right place, records what it did, and leaves verification to the\n"
        "next evaluation run.\n"
        "\n"
        "This notebook is **generated**. Edit `validation/eval_harness.py` or\n"
        "`validation/build_remediation_notebook.py` and regenerate.\n"
        "\n"
        "## The rule that decides where the text goes\n"
        "\n"
        "Agent-level instructions are **not passed to the DAX generation step** for a\n"
        "semantic model source. They shape the reply after the query has run. So a\n"
        "wrong number, an unrequested filter, or an invented region can only be fixed\n"
        "in the model's own AI instructions. Writing it in the agent instruction box\n"
        "feels productive and changes nothing.\n"
        "\n"
        "That is why `instruction_target` exists on every proposal, and why this\n"
        "notebook refuses to apply a model-class fix to the agent.\n"
        "\n"
        "## What it will not do\n"
        "\n"
        "- Apply anything that is not tier 1 with a literal approved instruction\n"
        "- Rewrite or delete text a human wrote. It appends under one heading\n"
        "- Write a verified answer, ever. That would let the loop raise its own score\n"
        "- Run without a named approver\n"
    ))

    cells.append(md("## 1. Parameters"))
    cells.append({
        "cell_type": "code",
        "execution_count": None,
        "metadata": {"tags": ["parameters"]},
        "outputs": [],
        "source": (
            f'WORKSPACE_ID = "{WORKSPACE_ID}"\n'
            f'DATA_AGENT_ID = "{DATA_AGENT_ID}"\n'
            f'SEMANTIC_MODEL_NAME = "{SEMANTIC_MODEL_NAME}"\n'
            f'LAKEHOUSE_NAME = "{LAKEHOUSE_NAME}"\n'
            f'KUSTO_URI = "{KUSTO_URI}"\n'
            f'KUSTO_DB = "{KUSTO_DB}"\n'
            "\n"
            "# Which defect to act on. Activator passes these when a human approves.\n"
            'QUESTION_ID = ""  # for example "Q10". Empty means every approved defect.\n'
            'APPROVED_BY = ""  # required. No anonymous changes to a governed model.\n'
            "\n"
            "# DRY_RUN prints the diff and writes nothing. Leave it true until you\n"
            "# have read the diff at least once.\n"
            "DRY_RUN = True\n"
        ).splitlines(True),
    })

    cells.append(md(
        "## 2. Embedded harness\n"
        "\n"
        "Generated from `validation/eval_harness.py`. Only `merge_instruction` and\n"
        "the target constants are used here, but embedding the whole module keeps\n"
        "one source of truth and one drift test."
    ))
    cells.append(code(harness))

    cells.append(md(
        "## 3. Find the approved work\n"
        "\n"
        "A defect becomes actionable when a row in `eval_approvals` says a human\n"
        "approved it. The approval carries the instruction text that was approved,\n"
        "so that changing the proposal afterwards cannot change what gets applied."
    ))
    cells.append(code(APPROVALS_CELL))

    cells.append(md(
        "## 4. Read the current instructions\n"
        "\n"
        "The model's AI instructions live in the semantic model at\n"
        "`model.cultures[en-US].linguisticMetadata.content.CustomInstructions`, which\n"
        "is what Prep data for AI (preview) writes. Reached over XMLA with sempy,\n"
        "because `getDefinition` is blocked for this item."
    ))
    cells.append(code(READ_CELL))

    cells.append(md(
        "## 5. Show the diff\n"
        "\n"
        "Always printed, in dry run and for real. A change to a governed model that\n"
        "nobody ever saw is not governance."
    ))
    cells.append(code(DIFF_CELL))

    cells.append(md(
        "## 6. Back up, then apply\n"
        "\n"
        "The backup is written before the change, not after, and it is the full\n"
        "model script rather than just the instructions. Restoring one property is\n"
        "not much use if the round trip damaged something else."
    ))
    cells.append(code(APPLY_CELL))

    cells.append(md(
        "## 7. Record what happened\n"
        "\n"
        "Written to Delta and to the eventhouse, so the dashboard shows remediation\n"
        "next to the alert that caused it. `verified` stays false until an\n"
        "evaluation run proves the fix worked, because merging is not verifying."
    ))
    cells.append(code(RECORD_CELL))

    cells.append(md(
        "## 8. Verify\n"
        "\n"
        "Re-run the evaluation notebook. If the affected questions reach stable pass\n"
        "the loop has closed. If they have not, the instruction was the wrong fix\n"
        "and the defect should go back to a human as tier 2."
    ))
    cells.append(code(VERIFY_CELL))

    return cells


APPROVALS_CELL = '''from pyspark.sql import functions as F

lh = f"{LAKEHOUSE_NAME}."
approvals_table = lh + "eval_approvals"

if not APPROVED_BY.strip():
    raise ValueError(
        "APPROVED_BY is required. A governed semantic model does not take "
        "anonymous changes."
    )

if not spark.catalog.tableExists(approvals_table):
    raise ValueError(
        f"{approvals_table} does not exist. Approve a defect first, either from "
        "the dashboard or by inserting a row into eval_approvals."
    )

approved = (
    spark.table(approvals_table)
         .filter(F.col("decision") == "approved")
         .filter(F.col("applied") == False)  # noqa: E712
)
if QUESTION_ID.strip():
    approved = approved.filter(F.col("question_id") == QUESTION_ID.strip())

pending = approved.collect()
print(f"{len(pending)} approved and unapplied item(s)")
for row in pending:
    print(f"  {row['question_id']}  target={row['instruction_target']}  by={row['approved_by']}")
    print(f"      {row['proposed_instruction'][:160]}")

if not pending:
    print("nothing to do")
'''


READ_CELL = '''import json

import notebookutils
import sempy.fabric as fabric

# Who is actually running this matters. A scheduled or Activator-invoked run
# executes as a different principal from the person who clicked Run, and a
# principal without write access to the semantic model produces a silent
# no-op rather than an error.
try:
    executing_identity = notebookutils.runtime.context.get("userName", "unknown")
except Exception:  # noqa: BLE001
    executing_identity = "unknown"
print(f"running as: {executing_identity}")

# Only model-targeted instructions change the DAX, so anything else is
# refused rather than quietly applied somewhere it cannot work.
targets = {row["instruction_target"] for row in pending}
unsupported = targets - {TARGET_SEMANTIC_MODEL}
if unsupported:
    raise ValueError(
        f"unsupported instruction targets {unsupported}. Agent-level instructions "
        "are not passed to the DAX generation step, so applying a model-class fix "
        "there would look like a change and do nothing."
    )

model_script = json.loads(
    fabric.get_tmsl(SEMANTIC_MODEL_NAME, workspace=WORKSPACE_ID)
)
culture = model_script["model"]["cultures"][0]
content = culture["linguisticMetadata"]["content"]
current = content.get("CustomInstructions", "")

# The persistence witness. A read back in the same session can be served from
# the local TOM copy and will happily show the value we just set even when
# nothing reached the model. lastUpdate comes from the server, so it is the
# only reliable evidence that a write landed.
last_update_before = model_script.get("lastUpdate")

print(f"culture           : {culture['name']}")
print(f"current length    : {len(current)} chars")
print(f"already remediated: {REMEDIATION_HEADING in current}")
print(f"lastUpdate before : {last_update_before}")
'''


DIFF_CELL = '''proposed = current
applied_now = []
already_present = []

for row in pending:
    merged, changed = merge_instruction(proposed, row["proposed_instruction"])
    if changed:
        proposed = merged
        applied_now.append(row)
        print(f"WILL ADD for {row['question_id']}:")
        print(f'  "{row["proposed_instruction"]}"')
    else:
        # The text is already in the model, so the approval is satisfied even
        # though this run changes nothing. Without this, an approval that was
        # applied by an earlier run, or by a person, would sit open forever
        # and nobody would ever be prompted about it again.
        already_present.append(row)
        print(f"already present, nothing to add for {row['question_id']}")

print()
print(f"length {len(current)} -> {len(proposed)}  ({len(applied_now)} line(s) to add, "
      f"{len(already_present)} already satisfied)")

if applied_now:
    print()
    print("--- new tail of the instructions ---")
    print(proposed[len(current):] if proposed.startswith(current) else proposed[-1200:])
'''


APPLY_CELL = '''import datetime
import os

changed_anything = bool(applied_now)
backup_path = ""
persisted = False

if not changed_anything:
    print("nothing to apply")
elif DRY_RUN:
    print("DRY_RUN is true, so nothing was written.")
    print("Set DRY_RUN = False to apply the diff above.")
else:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = f"/lakehouse/default/Files/model_backups/{SEMANTIC_MODEL_NAME}_{stamp}.tmsl.json"
    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
    with open(backup_path, "w", encoding="utf-8") as handle:
        json.dump(model_script, handle)
    print(f"backup written: {backup_path}")

    content["CustomInstructions"] = proposed
    script = {
        "createOrReplace": {
            "object": {"database": SEMANTIC_MODEL_NAME},
            "database": model_script,
        }
    }
    fabric.execute_tmsl(script=json.dumps(script), workspace=WORKSPACE_ID)
    print("execute_tmsl returned without error")

    # Two checks, because the first one on its own is not evidence.
    #
    # A content read back can be served from the session's own copy of the
    # model and will show the value we just set even if nothing reached the
    # server. lastUpdate is server side, so if it has not moved then the
    # write did not land, whatever the content says. That happens when the
    # executing principal can read the model but not write it, and it is
    # exactly the failure that must never be reported as success.
    verify = json.loads(fabric.get_tmsl(SEMANTIC_MODEL_NAME, workspace=WORKSPACE_ID))
    after = (
        verify["model"]["cultures"][0]["linguisticMetadata"]["content"]
        .get("CustomInstructions", "")
    )
    last_update_after = verify.get("lastUpdate")
    print(f"lastUpdate after  : {last_update_after}")

    content_matches = after == proposed
    server_moved = str(last_update_after) != str(last_update_before)
    persisted = content_matches and server_moved

    if not content_matches:
        raise RuntimeError(
            "read back does not match what was written. Restore from the backup "
            f"at {backup_path} before doing anything else."
        )
    if not server_moved:
        raise RuntimeError(
            "the write did not reach the model. lastUpdate is unchanged at "
            f"{last_update_before}, so nothing was persisted even though the "
            "content read back looks correct.\\n\\n"
            f"This run executed as: {executing_identity}\\n\\n"
            "The usual cause is that the executing principal can read the "
            "semantic model but cannot write it. Grant that principal write "
            "access, or run this notebook interactively as someone who has it. "
            "Do not treat this run as a successful remediation."
        )
    print(f"persisted: {len(after)} chars, {len(verify['model']['tables'])} tables intact")
'''


RECORD_CELL = '''import uuid

from pyspark.sql import Row
from pyspark.sql.types import (
    BooleanType, StringType, StructField, StructType, TimestampType,
)

now = datetime.datetime.now(datetime.timezone.utc)

remediations_schema = StructType([
    StructField("remediation_id", StringType()),
    StructField("applied_ts", TimestampType()),
    StructField("question_id", StringType()),
    StructField("instruction_target", StringType()),
    StructField("instruction", StringType()),
    StructField("approved_by", StringType()),
    StructField("applied_by", StringType()),
    StructField("dry_run", BooleanType()),
    StructField("backup_path", StringType()),
    StructField("persisted", BooleanType()),
    StructField("verified", BooleanType()),
])

rows = [
    Row(
        remediation_id=str(uuid.uuid4()),
        applied_ts=now,
        question_id=row["question_id"],
        instruction_target=row["instruction_target"],
        instruction=row["proposed_instruction"],
        approved_by=row["approved_by"],
        applied_by=f"{APPROVED_BY} ({executing_identity})",
        dry_run=bool(DRY_RUN),
        backup_path=backup_path,
        persisted=bool(persisted),
        verified=False,
    )
    for row in applied_now
]

if rows:
    remediations_df = spark.createDataFrame(rows, schema=remediations_schema)
    remediations_df.write.mode("append").format("delta").saveAsTable(lh + "eval_remediations")

    if not DRY_RUN and persisted:
        import notebookutils

        kusto_token = notebookutils.credentials.getToken(KUSTO_URI)
        (
            remediations_df.write.format("com.microsoft.kusto.spark.synapse.datasource")
            .option("kustoCluster", KUSTO_URI)
            .option("kustoDatabase", KUSTO_DB)
            .option("kustoTable", "eval_remediations")
            .option("accessToken", kusto_token)
            .option("tableCreateOptions", "CreateIfNotExist")
            .mode("Append")
            .save()
        )
    print(f"recorded {len(rows)} remediation(s)")
else:
    print("no new remediation rows")

# An approval is consumed when the instruction is in the model, whether this
# run put it there or an earlier one did. It is never consumed after a silent
# no-op, because that would lose the work and leave a defect nobody is
# prompted about again.
satisfied = ([r["question_id"] for r in applied_now] if (not DRY_RUN and persisted) else [])
satisfied += [r["question_id"] for r in already_present] if not DRY_RUN else []

if satisfied:
    quoted = ",".join(repr(i) for i in sorted(set(satisfied)))
    spark.sql(f"""
        UPDATE {approvals_table}
        SET applied = true, applied_ts = current_timestamp()
        WHERE question_id IN ({quoted})
          AND decision = 'approved' AND applied = false
    """)
    print(f"marked {len(set(satisfied))} approval(s) applied")
else:
    print("no approvals marked applied")
'''


VERIFY_CELL = '''print("Next step, and it is not optional:")
print()
print("  Run the agent_eval notebook again.")
print()
print("A merge is not a verification. The fix is proven when the affected")
print("questions reach stable_pass across every attempt, and eval_runs shows")
print("the score moving. If they do not, the instruction was the wrong fix and")
print("the defect belongs back with a human as tier 2.")
print()
if rows:
    print("questions to watch:", ", ".join(sorted({r["question_id"] for r in applied_now})))
'''


def build_notebook() -> dict:
    return {
        "cells": build_cells(),
        "metadata": {
            "kernelspec": {
                "display_name": "Synapse PySpark",
                "language": "Python",
                "name": "synapse_pyspark",
            },
            "language_info": {"name": "python"},
            "microsoft": {
                "language": "python",
                "language_group": "synapse_pyspark",
            },
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
    print(f"(eval notebook lives at {EVAL_NOTEBOOK_PATH.relative_to(ROOT)})")


if __name__ == "__main__":
    main()
