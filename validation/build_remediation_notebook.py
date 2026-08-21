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
            'DATA_AGENT_NAME = ""  # the item\'s display name, passed to the agent path\n'
            f'SEMANTIC_MODEL_NAME = "{SEMANTIC_MODEL_NAME}"\n'
            f'LAKEHOUSE_NAME = "{LAKEHOUSE_NAME}"\n'
            f'KUSTO_URI = "{KUSTO_URI}"\n'
            f'KUSTO_DB = "{KUSTO_DB}"\n'
            "\n"
            "# Which defect to act on. Activator passes these when a human approves.\n"
            'QUESTION_ID = ""  # for example "Q10". Empty means every approved defect.\n'
            "\n"
            "# Required, and the run refuses without it: a governed model does not\n"
            "# take anonymous changes. Activator passes it. Running this by hand,\n"
            "# put your own sign-in here, for example \"you@contoso.com\".\n"
            'APPROVED_BY = ""\n'
            "\n"
            "# DRY_RUN prints the diff and writes nothing. Leave it true until you\n"
            "# have read the diff at least once.\n"
            "#\n"
            "# Coerced below rather than trusted. A parameter injected by Activator\n"
            "# arrives as the string \"false\", and a non-empty string is truthy in\n"
            "# Python, so an unguarded DRY_RUN silently turns every automated\n"
            "# remediation into a no-op that reports success.\n"
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
        "## 8. Hand off the agent-targeted work\n"
        "\n"
        "A reference run rather than `%run`, so `agent_remediate_agent` gets its\n"
        "own session and a failure there cannot take this one down. Skipped\n"
        "entirely when there is no agent-targeted work, which is most runs.\n"
        "\n"
        "A failure here does not fail this run, because the semantic model work\n"
        "above has already landed. It is printed loudly instead: a quiet\n"
        "handoff failure is indistinguishable from a working one, which is how\n"
        "approved agent instructions once went unapplied for days while the\n"
        "report showed the loop as healthy."
    ))
    cells.append(code(HANDOFF_CELL))

    cells.append(md(
        "## 9. Verify\n"
        "\n"
        "Re-run the evaluation notebook. If the affected questions reach stable pass\n"
        "the loop has closed. If they have not, the instruction was the wrong fix\n"
        "and the defect should go back to a human as tier 2."
    ))
    cells.append(code(VERIFY_CELL))

    return cells


HANDOFF_CELL = '''agent_handoff_failed = ""

if not agent_pending:
    print("no agent-targeted approvals, nothing to hand off")
else:
    approval_ids = ",".join(r["approval_id"] for r in agent_pending)
    print(f"handing {len(agent_pending)} approval(s) to agent_remediate_agent")

    # A failure here must not fail this run. The model-targeted work above has
    # already been applied and recorded, and reporting the whole run as failed
    # would send somebody looking for a semantic model change that did land.
    #
    # It must not be quiet either. This used to print one line among fifty and
    # carry on, so an agent path that raised on every run looked exactly like
    # an agent path that worked, and two approved instructions sat unapplied
    # for days while the report said the loop was healthy.
    try:
        result = notebookutils.notebook.run(
            "agent_remediate_agent",
            600,
            {
                "APPROVAL_IDS": approval_ids,
                "APPROVED_BY": APPROVED_BY,
                "DATA_AGENT_NAME": DATA_AGENT_NAME,
                "DRY_RUN": str(DRY_RUN).lower(),
            },
        )
        print(f"agent_remediate_agent returned: {result}")
    except Exception as exc:  # noqa: BLE001
        agent_handoff_failed = str(exc)
        print("=" * 72)
        print("AGENT REMEDIATION FAILED. The semantic model work above is")
        print("unaffected and is recorded. Nothing reached the data agent.")
        print(f"  {agent_handoff_failed}")
        print()
        print("The approvals stay open, so the next run picks them up again.")
        print("Open agent_remediate_agent and run it by hand to see the error")
        print("in full. Until it succeeds, the agent-targeted questions will")
        print("keep failing the evaluation however many times they are")
        print("approved.")
        print("=" * 72)
'''


APPROVALS_CELL = '''import notebookutils

lh = f"{LAKEHOUSE_NAME}."
kusto_token = notebookutils.credentials.getToken(KUSTO_URI)

# Parameters injected by Activator arrive as strings. "false" is a non-empty
# string and therefore truthy, so without this every automated remediation
# would quietly do nothing and report success.
DRY_RUN = str(DRY_RUN).strip().lower() not in ("false", "0", "no", "")
print(f"DRY_RUN resolved to {DRY_RUN}")


def read_kusto(query):
    return (
        spark.read.format("com.microsoft.kusto.spark.synapse.datasource")
        .option("kustoCluster", KUSTO_URI)
        .option("kustoDatabase", KUSTO_DB)
        .option("kustoQuery", query)
        .option("accessToken", kusto_token)
        .load()
    )


def write_kusto(df, table):
    (
        df.write.format("com.microsoft.kusto.spark.synapse.datasource")
        .option("kustoCluster", KUSTO_URI)
        .option("kustoDatabase", KUSTO_DB)
        .option("kustoTable", table)
        .option("accessToken", kusto_token)
        .option("tableCreateOptions", "CreateIfNotExist")
        .mode("Append")
        .save()
    )


if not APPROVED_BY.strip():
    raise ValueError(
        "APPROVED_BY is required. A governed semantic model does not take "
        "anonymous changes, so this refuses rather than guessing who you "
        "are.\\n"
        "\\n"
        "Running this by hand: set APPROVED_BY in the parameters cell above "
        "to your own sign-in, for example \\"you@contoso.com\\", and run "
        "again. While you are there, DRY_RUN is True by default and prints "
        "the diff without writing anything. Read the diff once, then set it "
        "to False to apply.\\n"
        "\\n"
        "Seeing this from an automated run: the Activator rule passes "
        "APPROVED_BY itself, so an empty one means the rule has lost its "
        "parameter. That is the bug, not this."
    )

# The eventhouse is the only approval store, and nothing in it is mutated.
# Open work is derived: approved, with no persisted remediation against the
# same approval_id. The same expression is used by approve.py, the Activator
# rule and the dashboard, so none of them can disagree about what is
# outstanding.
#
# A bulk approval closes itself. When somebody approves the same sentence for
# four questions at once, the approval function writes one remediation row per
# covered approval and the mirror pushes those to the eventhouse, so this join
# has already excluded them and no second identical write is ever queued.
open_approvals_kql = """
eval_approvals
| where decision == "approved"
| join kind=leftanti (
    eval_remediations
    | where persisted == true
    | distinct approval_id
  ) on approval_id
"""
if QUESTION_ID.strip():
    open_approvals_kql += f'| where question_id == "{QUESTION_ID.strip()}"\\n'

pending = read_kusto(open_approvals_kql).collect()

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

# Split by target rather than refusing everything.
#
# Only model-targeted instructions change the DAX. Agent-targeted ones change
# how an answer reads, which is a real fix for a real defect class, but it
# writes to a different governed item. That is confined to
# agent_remediate_agent, reached below with a reference run so it gets its own
# session and cannot take this path down with it.
agent_pending = [r for r in pending if r["instruction_target"] == TARGET_DATA_AGENT]
pending = [r for r in pending if r["instruction_target"] == TARGET_SEMANTIC_MODEL]

unsupported = {
    row["instruction_target"] for row in agent_pending + pending
} - {TARGET_SEMANTIC_MODEL, TARGET_DATA_AGENT}
if unsupported:
    raise ValueError(
        f"unsupported instruction targets {unsupported}. An instruction has to "
        "land somewhere that can act on it, and anything else would look like "
        "a change and do nothing."
    )

print(f"{len(pending)} model-targeted, {len(agent_pending)} agent-targeted")

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

    # Optimistic concurrency. This is a read-modify-write of the whole model,
    # so two remediation runs overlapping would both read the same starting
    # point and the second would silently drop the first one's instruction,
    # while both reported success and both closed their approvals. Re-read
    # immediately before writing and refuse if anything moved underneath us.
    guard = json.loads(fabric.get_tmsl(SEMANTIC_MODEL_NAME, workspace=WORKSPACE_ID))
    if str(guard.get("lastUpdate")) != str(last_update_before):
        raise RuntimeError(
            "the model changed while this run was preparing its edit.\\n\\n"
            f"read at   {last_update_before}\\n"
            f"now at    {guard.get('lastUpdate')}\\n\\n"
            "Writing now would replace the whole model from a stale snapshot "
            "and discard whatever the other change added. Nothing was written. "
            "Re-run this notebook; the approval is still open."
        )

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
    StructField("recorded_ts", TimestampType()),
    StructField("applied_ts", TimestampType()),
    StructField("approval_id", StringType()),
    StructField("question_id", StringType()),
    StructField("instruction_target", StringType()),
    StructField("instruction", StringType()),
    StructField("approved_by", StringType()),
    StructField("applied_by", StringType()),
    StructField("dry_run", BooleanType()),
    StructField("backup_path", StringType()),
    StructField("persisted", BooleanType()),
    StructField("verified", BooleanType()),
    StructField("verified_ts", TimestampType()),
    StructField("verified_run_id", StringType()),
])


def remediation_row(row, was_persisted, wrote_something=True):
    return Row(
        remediation_id=str(uuid.uuid4()),
        # recorded_ts, not applied_ts, is the ordering key. A later
        # verification appends a corrected row for the same remediation_id,
        # and if both rows carried the same applied_ts then arg_max would pick
        # between them arbitrarily and `verified` would flicker.
        recorded_ts=now,
        # Null when this run wrote nothing because the sentence was already in
        # the model. That is what the column has always meant, and it is what
        # lets the report separate "we changed the model" from "the model
        # already said this" without a new column anywhere.
        applied_ts=now if wrote_something else None,
        approval_id=row["approval_id"],
        question_id=row["question_id"],
        instruction_target=row["instruction_target"],
        instruction=row["proposed_instruction"],
        approved_by=row["approved_by"],
        applied_by=f"{APPROVED_BY} ({executing_identity})",
        dry_run=bool(DRY_RUN),
        backup_path=backup_path,
        # An approval is consumed by a persisted remediation, so this flag is
        # the only thing that closes it. It is never set after a silent no-op.
        persisted=bool(was_persisted),
        verified=False,
        verified_ts=None,
        verified_run_id=None,
    )


# An instruction that is already in the model satisfies its approval just as
# much as one this run added. Otherwise an approval applied by an earlier run,
# or by a person editing the model directly, stays open forever.
rows = [remediation_row(r, persisted) for r in applied_now]
rows += [remediation_row(r, True, wrote_something=False) for r in already_present]

if rows and not DRY_RUN:
    remediations_df = spark.createDataFrame(rows, schema=remediations_schema)
    remediations_df.write.mode("append").format("delta").saveAsTable(lh + "eval_remediations")
    write_kusto(remediations_df, "eval_remediations")

    closed = sum(1 for r in rows if r["persisted"])
    print(f"recorded {len(rows)} remediation(s), {closed} of which close an approval")
elif rows:
    print(f"DRY_RUN, so {len(rows)} remediation(s) were not recorded")
else:
    print("nothing recorded")

if already_present:
    print()
    print("Nothing was written to the model for "
          + ", ".join(sorted({r["question_id"] for r in already_present}))
          + ". The approved sentence was already in the model's AI "
          "instructions, so applying it again would have changed nothing and "
          "would have added a duplicate line. Those approvals are closed "
          "rather than left open, and they are recorded with no applied time "
          "so the report shows them as already present rather than as a "
          "change this run made.")
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

if agent_handoff_failed:
    print()
    print("Note that the agent-targeted approvals in this run did NOT reach the")
    print("data agent. Re-running the evaluation will not improve them, because")
    print("nothing was applied. Fix the handoff first.")
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
            # No `dependencies` block, for the same reason as the eval
            # notebook: it would commit a workspace and lakehouse id.
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
