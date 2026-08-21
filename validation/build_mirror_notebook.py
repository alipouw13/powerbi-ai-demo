"""Generate the approval mirror notebook.

Activator cannot watch a SQL database. Its sources are Power BI semantic
models, KQL querysets, Real-Time Dashboards, Eventstreams, Fabric events and
Azure events. So approvals are written to SQL, where the user data function
can reach them with a managed connection, and copied to the eventhouse, where
Activator can watch them. Nothing downstream changes.

Three copies, in two directions:

    dbo.remediations   -->  eval_remediations   (closing rows, first)
    dbo.approvals      -->  eval_approvals      (so the rule can fire)
    eval_remediations  -->  dbo.remediations    (so the report can show status)

The last is what makes `dbo.open_approvals` correct. Without it the view
never sees a remediation land, every applied approval looks open forever, and
the function refuses every second approval for a question.

The first exists for bulk approval. When somebody approves the same sentence
for several questions at once, the approval function writes the closing rows
straight into SQL, because those decisions need no write to the model at all.
They are copied out first so that a covered approval can never reach the
eventhouse ahead of the row that closes it.

## Why a notebook rather than a pipeline

A Data Factory pipeline is the obvious tool and was the first attempt. Its
definition cannot be validated offline, and the copy activity's linked service
for a Fabric SQL database rejected every shape tried against the real API. A
notebook is a worse fit on paper and a much better one in practice: this repo
already generates notebooks, tests them for drift, executes their cells in
unit tests, and schedules them.

**A Python notebook, not Spark.** It moves a handful of rows. A Spark session
takes longer to start than this takes to run, and on a one minute schedule
that is the difference between working and not.

## The mirrored_ts watermark

`dbo.approvals.mirrored_ts` is null until this copies the row. A row is picked
up because it is unmirrored, not because it arrived since some remembered
time, so a missed run catches up by itself and a failure is a query rather
than a mystery.

Run:
    python validation/build_mirror_notebook.py
"""

from __future__ import annotations

import json

from build_eval_notebook import ROOT, code, md

NOTEBOOK_PATH = ROOT / "fabric" / "mirror_approvals.ipynb"


PARAMETERS_CELL = '''# Filled in at deployment. Empty in source control, like every other
# deployment value in this repo.
WORKSPACE_ID = ""
SQL_DATABASE = "SQLDB_AgentEval"
KUSTO_URI = ""
KUSTO_DB = "EH_AgentEval"
'''


MIRROR_CELL = '''import json
import urllib.request
from datetime import datetime, timezone

import notebookutils

# The SQL side. connect_to_artifact is a Python notebook API and is the reason
# this is not a Spark notebook.
sql = notebookutils.data.connect_to_artifact(SQL_DATABASE, WORKSPACE_ID, "SQLDatabase")

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


def kusto_rows(result):
    table = result["Tables"][0]
    names = [c["ColumnName"] for c in table["Columns"]]
    return [dict(zip(names, row)) for row in table["Rows"]]


def sql_rows(result):
    """Rows from a SQL query, as a list of dicts.

    connect_to_artifact returns None rather than an empty frame when a SELECT
    matches nothing, so `list(result)` raises TypeError on the ordinary case
    of there being nothing to mirror.

    That case is the steady state, not an edge case. This notebook runs every
    minute and almost every run has no new approvals, so a version that only
    worked when there was something to copy failed on every scheduled run and
    succeeded whenever anybody tested it by hand right after approving
    something. It looked like a scheduling problem for a day.
    """
    if result is None:
        return []
    if hasattr(result, "to_dict"):
        return result.to_dict("records")
    return list(result)


def escape(value):
    """Escape a value for a Kusto double quoted string literal.

    Backslash first. Escaping the quotes before the backslashes turns `a\\\\`
    into `a\\\\"` and ends the literal early, which is both a broken command
    and the shape of an injection.

    Newlines matter as much as quotes and are easier to forget. A Kusto
    double quoted literal cannot contain a raw line break, so a decision note
    with one produces a command that ends mid-string. The row never reaches
    the eventhouse, the rule never fires, and because the mirror only marks a
    row after the copy succeeds it will retry the same broken command every
    minute forever. A person typing Enter in a note field would stop the loop.

    A null arrives as None from some drivers and as a pandas NaN or NaT from
    the one this notebook uses, and `str(nan)` is the string "nan", which
    would be copied into the eventhouse as though somebody had written it.
    """
    if value is None or value != value:
        return ""
    return (
        str(value)
        .replace("\\\\", "\\\\\\\\")
        .replace('"', '\\\\"')
        .replace("\\r", "\\\\r")
        .replace("\\n", "\\\\n")
        .replace("\\t", "\\\\t")
    )
'''


COVERED_CELL = '''# The third leg, and the reason it runs first.
#
# dbo.remediations is normally written by the remediation notebook, in the
# eventhouse, and pulled back here. Bulk approval is the exception: when
# somebody approves the same sentence for four questions at once, the approval
# function writes three closing rows straight into SQL, because those
# decisions need no write to the model at all.
#
# Those rows have to reach the eventhouse, or the leftanti join the remediation
# notebook uses to find open work would treat all four as outstanding and
# queue four identical writes.
#
# First, because the approval leg below is what makes the Activator rule fire.
# Copying the closing row after the approval would leave a window in which the
# rule sees an approval with nothing closing it.
def kusto_datetime(value):
    """A Kusto datetime literal from whatever SQL handed back.

    A null datetime arrives as None from some drivers and as pandas NaT from
    the one this notebook uses. NaT is not None, is not equal to itself, and
    formats as the string "NaT", so a naive check produces `datetime(NaT)`
    and a Kusto syntax error on exactly the rows this leg exists to copy.
    """
    if value is None or value != value or str(value) in ("", "NaT", "None"):
        return "datetime(null)"
    if not isinstance(value, str):
        value = value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return f"datetime({value})"


def kusto_bool(value):
    return "true" if value else "false"


in_eventhouse = {
    row["remediation_id"]
    for row in kusto_rows(kusto("eval_remediations | distinct remediation_id"))
}

unpushed = [
    row for row in sql_rows(sql.query("""
        SELECT remediation_id, recorded_ts, applied_ts, approval_id,
               question_id, instruction_target, instruction, approved_by,
               applied_by, dry_run, persisted, verified, verified_ts,
               verified_run_id
        FROM dbo.remediations
        ORDER BY recorded_ts
    """))
    if str(row["remediation_id"]) not in in_eventhouse
]

print(f"{len(unpushed)} SQL remediation(s) not yet in the eventhouse")

for row in unpushed:
    kusto(
        ".set-or-append eval_remediations <| print "
        f'remediation_id="{escape(row["remediation_id"])}", '
        f'recorded_ts={kusto_datetime(row["recorded_ts"])}, '
        f'applied_ts={kusto_datetime(row["applied_ts"])}, '
        f'approval_id="{escape(row["approval_id"])}", '
        f'question_id="{escape(row["question_id"])}", '
        f'instruction_target="{escape(row["instruction_target"])}", '
        f'instruction="{escape(row["instruction"])}", '
        f'approved_by="{escape(row["approved_by"])}", '
        f'applied_by="{escape(row["applied_by"])}", '
        f'dry_run={kusto_bool(row["dry_run"])}, backup_path="", '
        f'persisted={kusto_bool(row["persisted"])}, '
        f'verified={kusto_bool(row["verified"])}, '
        f'verified_ts={kusto_datetime(row["verified_ts"])}, '
        f'verified_run_id="{escape(row["verified_run_id"])}"',
        endpoint="mgmt",
    )
    print(f"  pushed {row['question_id']} ({row['applied_by']})")
'''


APPROVALS_CELL = '''# Approvals that have not reached the eventhouse yet.
pending = sql.query("""
    SELECT approval_id, approved_ts, question_id, instruction_target,
           proposed_instruction, decision, approved_by, approver_oid,
           source, note
    FROM dbo.approvals
    WHERE mirrored_ts IS NULL
    ORDER BY approved_ts
""")

rows = sql_rows(pending)
print(f"{len(rows)} approval(s) to mirror")

mirrored = []
for row in rows:
    stamp = row["approved_ts"]
    if not isinstance(stamp, str):
        stamp = stamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    # One command per row rather than a batch. A batch that fails halfway
    # would leave some rows copied and none marked, and the retry would copy
    # them again.
    kusto(
        ".set-or-append eval_approvals <| print "
        f'approval_id="{escape(row["approval_id"])}", '
        f"approved_ts=datetime({stamp}), "
        f'question_id="{escape(row["question_id"])}", '
        f'instruction_target="{escape(row["instruction_target"])}", '
        f'proposed_instruction="{escape(row["proposed_instruction"])}", '
        f'decision="{escape(row["decision"])}", '
        f'approved_by="{escape(row["approved_by"])}", '
        f'note="{escape(row["note"])}"',
        endpoint="mgmt",
    )
    mirrored.append(row["approval_id"])
    print(f"  mirrored {row['question_id']} ({row['decision']})")

# Marked only after the copy succeeds. Marking first would lose an approval on
# any failure, and a lost approval is a change a person authorised that never
# happened and that nothing reports.
for approval_id in mirrored:
    sql.query(
        "UPDATE dbo.approvals SET mirrored_ts = SYSUTCDATETIME() "
        f"WHERE approval_id = '{approval_id}'"
    )

print(f"marked {len(mirrored)} as mirrored")
'''


REMEDIATIONS_CELL = '''# The return leg. Without it dbo.open_approvals never sees a remediation
# land, every applied approval looks open forever, and the function refuses
# every second approval for a question.
applied = kusto_rows(kusto("""
    eval_remediations
    | summarize arg_max(recorded_ts, *) by remediation_id
    | project remediation_id, recorded_ts, applied_ts, approval_id, question_id,
              instruction_target, instruction, approved_by, applied_by,
              dry_run, persisted, verified, verified_ts, verified_run_id
"""))

print(f"{len(applied)} remediation(s) in the eventhouse")


def sql_literal(value):
    if value is None or value == "":
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    return "N'" + str(value).replace("'", "''") + "'"


written = 0
for row in applied:
    # Upsert on the key, because the eventhouse is append only and a
    # remediation gains a corrected row when it becomes verified. An insert
    # would give the report two rows for one remediation, one permanently
    # stale.
    values = ", ".join(sql_literal(row[c]) for c in (
        "remediation_id", "recorded_ts", "applied_ts", "approval_id",
        "question_id", "instruction_target", "instruction", "approved_by",
        "applied_by", "dry_run", "persisted", "verified", "verified_ts",
        "verified_run_id",
    ))
    sql.query(f"""
        MERGE dbo.remediations AS t
        USING (SELECT {sql_literal(row['remediation_id'])} AS remediation_id) AS s
        ON t.remediation_id = s.remediation_id
        WHEN MATCHED THEN UPDATE SET
            recorded_ts = {sql_literal(row['recorded_ts'])},
            verified    = {sql_literal(row['verified'])},
            verified_ts = {sql_literal(row['verified_ts'])},
            verified_run_id = {sql_literal(row['verified_run_id'])}
        WHEN NOT MATCHED BY TARGET THEN
            INSERT (remediation_id, recorded_ts, applied_ts, approval_id,
                    question_id, instruction_target, instruction, approved_by,
                    applied_by, dry_run, persisted, verified, verified_ts,
                    verified_run_id)
            VALUES ({values});
    """)
    written += 1

print(f"upserted {written} remediation(s) into SQL")
'''


CHECK_CELL = '''# What a person should see if this is healthy. An approval with an old
# approved_ts and a null mirrored_ts never reached the eventhouse, so the rule
# never fired, and that is a query rather than a mystery.
print(sql.query("""
    SELECT
        (SELECT COUNT(*) FROM dbo.approvals)                       AS approvals,
        (SELECT COUNT(*) FROM dbo.approvals WHERE mirrored_ts IS NULL) AS unmirrored,
        (SELECT COUNT(*) FROM dbo.open_approvals)                  AS open_approvals,
        (SELECT COUNT(*) FROM dbo.remediations)                    AS remediations
"""))
'''


def build_cells() -> list[dict]:
    cells: list[dict] = []

    cells.append(md(
        "# Mirror approvals\n"
        "\n"
        "Copies approvals to the eventhouse so Activator can see them, and\n"
        "remediations back so the report can show status.\n"
        "\n"
        "This notebook is **generated**. Edit\n"
        "`validation/build_mirror_notebook.py` and regenerate.\n"
        "\n"
        "## Why this exists\n"
        "\n"
        "Activator cannot watch a SQL database. Its sources are Power BI\n"
        "semantic models, KQL querysets, Real-Time Dashboards, Eventstreams,\n"
        "Fabric events and Azure events. So the approval is written where the\n"
        "user data function can reach it with a managed connection, and copied\n"
        "to where the rule can see it.\n"
        "\n"
        "## Why a notebook and not a pipeline\n"
        "\n"
        "A pipeline was the first attempt and its definition cannot be validated\n"
        "outside the tenant. This is generated, drift tested, and its cells are\n"
        "executed by unit tests.\n"
        "\n"
        "**Python, not Spark.** It moves a handful of rows, and a Spark session\n"
        "takes longer to start than this takes to run. On a one minute schedule\n"
        "that is the difference between working and not.\n"
        "\n"
        "## Run it every minute\n"
        "\n"
        "That interval is the approval latency: about a minute here, plus about\n"
        "a minute for the Activator rule to poll."
    ))

    cells.append(md("## 1. Parameters"))
    cells.append({
        "cell_type": "code",
        "execution_count": None,
        "metadata": {"tags": ["parameters"]},
        "outputs": [],
        "source": PARAMETERS_CELL.splitlines(True),
    })

    cells.append(md("## 2. Connect to both stores"))
    cells.append(code(MIRROR_CELL))

    cells.append(md(
        "## 3. Closing rows to the eventhouse\n"
        "\n"
        "Bulk approvals close themselves in SQL. Those rows have to reach the\n"
        "eventhouse before the approvals they close, or the rule fires on an\n"
        "approval that nothing appears to close and the notebook queues a\n"
        "duplicate write."
    ))
    cells.append(code(COVERED_CELL))

    cells.append(md(
        "## 4. Approvals to the eventhouse\n"
        "\n"
        "Unmirrored rows only, marked as mirrored after the copy succeeds."
    ))
    cells.append(code(APPROVALS_CELL))

    cells.append(md(
        "## 5. Remediations back to SQL\n"
        "\n"
        "So `dbo.open_approvals` closes and the report shows applied and\n"
        "verified states."
    ))
    cells.append(code(REMEDIATIONS_CELL))

    cells.append(md("## 6. What healthy looks like"))
    cells.append(code(CHECK_CELL))

    return cells


def build_notebook() -> dict:
    return {
        "cells": build_cells(),
        # A Python notebook, not Spark, and the metadata is what decides that.
        # Fabric reads `kernel_info` and `microsoft.language_group`; a
        # kernelspec alone is not enough, and getting it wrong silently starts
        # a Spark session where `notebookutils.data` does not exist.
        "metadata": {
            "kernel_info": {"name": "jupyter"},
            "kernelspec": {"display_name": "Python (Jupyter)",
                           "language": "python", "name": "jupyter"},
            "language_info": {"name": "python"},
            "microsoft": {"language": "python", "language_group": "jupyter_python"},
            "dependencies": {},
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
