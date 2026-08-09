"""Generate fabric/agent_eval.ipynb from the tested modules.

The notebook has to be self-contained, because a Fabric notebook cannot
import from this repo. Copying code into a notebook by hand is how notebooks
and their source drift apart, so the copy is generated instead, and
test_notebook_drift.py fails the build if the committed notebook no longer
matches the modules.

Run:
    python validation/build_eval_notebook.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VALIDATION = ROOT / "validation"
NOTEBOOK_PATH = ROOT / "fabric" / "agent_eval.ipynb"

KUSTO_URI = ""
KUSTO_DB = "EH_AgentEval"

WORKSPACE_ID = ""
DATA_AGENT_ID = ""
LAKEHOUSE_ID = ""
LAKEHOUSE_NAME = "LH_ContosoCoffee"


def strip_module_docstring(source: str) -> str:
    """Drop the module docstring and __future__ import from an embedded copy."""
    source = re.sub(r'\A\s*""".*?"""\s*', "", source, flags=re.DOTALL)
    source = source.replace("from __future__ import annotations\n", "")
    return source.strip()


def read(name: str) -> str:
    return (VALIDATION / name).read_text(encoding="utf-8")


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(True)}


def code(text: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": text.splitlines(True),
    }


def build_cells() -> list[dict]:
    harness = strip_module_docstring(read("eval_harness.py"))
    client = strip_module_docstring(read("agent_client.py"))
    question_bank = read("question-bank.md")

    cells: list[dict] = []

    cells.append(md(
        "# Data agent evaluation\n"
        "\n"
        "Runs the question bank against the published Contoso Coffee data agent,\n"
        "grades every answer against ground truth, repeats each question so that\n"
        "nondeterminism is visible, and writes the results to Delta tables that\n"
        "Activator watches.\n"
        "\n"
        "This notebook is **generated**. Edit `validation/eval_harness.py` or\n"
        "`validation/agent_client.py` and run `python validation/build_eval_notebook.py`.\n"
        "Editing the notebook directly will be overwritten.\n"
        "\n"
        "## What it does not do\n"
        "\n"
        "It never changes the model or the agent. It proposes fixes and records\n"
        "them. A human decides. Two rules make that non negotiable:\n"
        "\n"
        "1. Agent instructions are not passed to the DAX generation step for a\n"
        "   semantic model source, so editing the agent cannot fix a wrong number.\n"
        "2. A loop allowed to write verified answers would pin its way to a\n"
        "   perfect score over a model that is still wrong.\n"
    ))

    cells.append(md(
        "## 1. Parameters\n"
        "\n"
        "No `%pip install` anywhere in this notebook, which is deliberate. The\n"
        "agent is reached over plain JSON-RPC with the standard library. Adding\n"
        "the `mcp` package to a Spark session upgrades pydantic, anyio,\n"
        "typing-extensions and jsonschema over the builds the runtime ships,\n"
        "and a scheduled job cannot afford that kind of instability.\n"
        "\n"
        "This cell is tagged as the parameters cell, so a pipeline or a\n"
        "scheduled run can override any of it."
    ))
    cells.append({
        "cell_type": "code",
        "execution_count": None,
        "metadata": {"tags": ["parameters"]},
        "outputs": [],
        "source": (
            f'WORKSPACE_ID = "{WORKSPACE_ID}"\n'
            f'DATA_AGENT_ID = "{DATA_AGENT_ID}"\n'
            f'LAKEHOUSE_NAME = "{LAKEHOUSE_NAME}"\n'
            "\n"
            "# Repetitions per question. This is the single most valuable knob in\n"
            "# the notebook. At 1 you cannot tell a model that is wrong from a\n"
            "# model that is ambiguous, and the second is worse in front of an\n"
            "# audience because you cannot predict it or brief around it.\n"
            "REPEAT = 3\n"
            "\n"
            "# Questions in flight at once. The agent is a shared capacity\n"
            "# resource and throttling looks exactly like a flake, which would\n"
            "# poison the one signal this notebook exists to produce.\n"
            "CONCURRENCY = 3\n"
            "\n"
            "TABLE_PREFIX = \"eval\"\n"
            "SURFACE = \"D\"  # pass D in validation/scorecard.md, the data agent\n"
                        "\n"
                        "# Eventhouse that Activator watches. Delta holds the history and is\n"
                        "# what you query. Kusto is the event spine that makes alerting\n"
                        "# possible, because Activator cannot watch a Delta table directly.\n"
                        f'KUSTO_URI = "{KUSTO_URI}"\n'
                        f'KUSTO_DB = "{KUSTO_DB}"\n'
        ).splitlines(True),
    })

    cells.append(md(
        "## 2. Embedded harness\n"
        "\n"
        "Generated from `validation/eval_harness.py`. Pure logic, no Fabric\n"
        "imports, covered by unit tests that run on a laptop with no capacity."
    ))
    cells.append(code(harness))

    cells.append(md(
        "## 3. Embedded agent client\n"
        "\n"
        "Generated from `validation/agent_client.py`. Standard library only.\n"
        "Opens a fresh MCP session per question so no context leaks between\n"
        "questions."
    ))
    cells.append(code(client))

    cells.append(md(
        "## 4. Question bank\n"
        "\n"
        "Embedded verbatim from `validation/question-bank.md`, and parsed rather\n"
        "than retyped. A question asked by the harness that has drifted from the\n"
        "question printed in the docs is a silent and very confusing failure."
    ))
    cells.append(code(
        "QUESTION_BANK_MD = r'''\n" + question_bank + "\n'''\n"
        "\n"
        "questions = parse_question_bank(QUESTION_BANK_MD)\n"
        "print(f\"parsed {len(questions)} questions\")\n"
        "for q in questions:\n"
        "    print(f\"  {q.id} [{q.kind}] {q.text}\")\n"
    ))

    cells.append(md(
        "## 5. Ground truth from the lakehouse\n"
        "\n"
        "Computed with Spark straight off the Delta tables, independently of the\n"
        "semantic model. That is the point: if the oracle came from the same\n"
        "semantic model the agent queries, a modelling error would move the\n"
        "answer and the expected value together and the test would pass while\n"
        "being wrong.\n"
        "\n"
        "The mirror of `ground_truth.compute_raw()`, which does the same sums\n"
        "over the committed CSVs."
    ))
    cells.append(code(GROUND_TRUTH_CELL))

    cells.append(md(
        "## 6. Run the evaluation\n"
        "\n"
        "Every question, `REPEAT` times, each in a fresh session."
    ))
    cells.append(code(RUN_CELL))

    cells.append(md(
        "## 7. Score, classify and propose\n"
        "\n"
        "Proposals are proposals. Nothing here edits the model."
    ))
    cells.append(code(SCORE_CELL))

    cells.append(md(
        "## 8. Write the Delta tables\n"
        "\n"
        "Three append only tables. History is the whole point: correlating a\n"
        "score drop with a model change is what turns an alert into a diagnosis.\n"
        "\n"
        "| Table | Grain |\n"
        "| --- | --- |\n"
        "| `eval_runs` | one row per run, and the row Activator watches |\n"
        "| `eval_results` | one row per question per attempt |\n"
        "| `eval_defects` | one open defect per failing question, with its proposal |\n"
    ))
    cells.append(code(WRITE_CELL))

    cells.append(md(
        "## 9. Publish to the Eventhouse for Activator\n"
        "\n"
        "Activator cannot watch a Delta table. It watches a KQL query, so the\n"
        "run summary is published to the Eventhouse as well. Delta stays the\n"
        "system of record and the thing you query; Kusto is the event spine\n"
        "that makes alerting possible.\n"
        "\n"
        "One row per run, carrying the alert verdict the tested Python already\n"
        "reached. The rule in Activator only has to read `alert_severity`,\n"
        "which keeps the thresholds in code that has unit tests rather than in\n"
        "a rule definition nobody can test."
    ))
    cells.append(code(KUSTO_CELL))

    cells.append(md(
        "## 10. Alert payload\n"
        "\n"
        "The thresholds live in tested Python rather than being buried in a rule\n"
        "definition in the portal. Activator reads `alert_severity` and\n"
        "`alert_count` off `eval_runs` and decides whether to notify."
    ))
    cells.append(code(ALERT_CELL))

    return cells


GROUND_TRUTH_CELL = '''from pyspark.sql import functions as F

lh = f"{LAKEHOUSE_NAME}."

sales = spark.table(lh + "fact_sales")
dim_date = spark.table(lh + "dim_date")
dim_store = spark.table(lh + "dim_store")
dim_product = spark.table(lh + "dim_product")

joined = (
    sales.join(dim_date, "date_key")
         .join(dim_store, "store_key")
         .join(dim_product, "product_key")
)

totals = joined.agg(
    F.sum("net_amount").alias("total_net"),
    F.sum("cost_amount").alias("total_cost"),
    F.sum("quantity").alias("total_units"),
    F.count(F.lit(1)).alias("line_count"),
).collect()[0]

total_net = float(totals["total_net"])
total_margin = total_net - float(totals["total_cost"])


def as_map(df, key_col, order_desc=True):
    rows = (
        df.groupBy(key_col)
          .agg(F.sum("net_amount").alias("net"))
          .orderBy(F.col("net").desc() if order_desc else F.col("net"))
          .collect()
    )
    return {str(r[key_col]): float(r["net"]) for r in rows}


by_year = as_map(joined, "year")
by_region = as_map(joined, "region")
by_store = as_map(joined, "store_name")
by_category = as_map(joined, "category")
by_product = as_map(joined, "product_name")
by_channel = as_map(joined, "channel")
by_month_2025 = as_map(joined.filter(F.col("year") == 2025), "year_month")

weekend_rows = (
    joined.groupBy("is_weekend").agg(F.sum("net_amount").alias("net")).collect()
)
weekend_net = next(
    (float(r["net"]) for r in weekend_rows if str(r["is_weekend"]).lower() in ("true", "1")),
    0.0,
)
weekday_net = next(
    (float(r["net"]) for r in weekend_rows if str(r["is_weekend"]).lower() not in ("true", "1")),
    0.0,
)

net_2024 = by_year.get("2024", 0.0)
net_2025 = by_year.get("2025", 0.0)


def top(mapping):
    key = max(mapping, key=mapping.get)
    return (key, mapping[key])


raw = {
    "total_net": total_net,
    "total_margin": total_margin,
    "margin_pct": total_margin / total_net,
    "total_units": int(totals["total_units"]),
    "net_2024": net_2024,
    "net_2025": net_2025,
    "yoy_pct": (net_2025 - net_2024) / net_2024,
    "top_store": top(by_store),
    "top_product": top(by_product),
    "by_region": by_region,
    "by_category": by_category,
    "by_channel": by_channel,
    "best_month_2025": top(by_month_2025),
    "weekend_net": weekend_net,
    "weekday_net": weekday_net,
    "avg_order_line": total_net / int(totals["line_count"]),
}

expectations = build_expectations(raw)

print(f"total net revenue : ${raw['total_net']:,.2f}")
print(f"gross margin      : ${raw['total_margin']:,.2f} ({raw['margin_pct']:.2%})")
print(f"units             : {raw['total_units']:,}")
print(f"top store         : {raw['top_store'][0]} (${raw['top_store'][1]:,.2f})")
print(f"regions           : {list(raw['by_region'])}")
print(f"\\nbuilt {len(expectations)} expectations")
'''


RUN_CELL = '''import uuid
from datetime import datetime, timezone

run_id = str(uuid.uuid4())
run_ts = datetime.now(timezone.utc)

client = DataAgentClient(WORKSPACE_ID, DATA_AGENT_ID, concurrency=CONCURRENCY)
results = {q.id: QuestionResult(q.id, q.kind) for q in questions}

for attempt in range(1, REPEAT + 1):
    print(f"--- attempt {attempt} of {REPEAT} ---", flush=True)
    replies = client.ask([q.text for q in questions])

    for question, reply in zip(questions, replies):
        if reply.error:
            grade, detail = ERRORED, f"transport error: {reply.error[:200]}"
        else:
            grade, detail = grade_answer(expectations[question.id], reply.answer)

        results[question.id].attempts.append(
            Attempt(
                question_id=question.id,
                attempt=attempt,
                answer=reply.answer,
                grade=grade,
                detail=detail,
                latency_ms=reply.latency_ms,
            )
        )
        flag = "ok  " if grade == CORRECT else "FAIL"
        print(f"  {flag} {question.id} {grade:<15} {detail[:80]}", flush=True)

ordered = [results[q.id] for q in questions]
print(f"\\nrun_id {run_id}")
'''


SCORE_CELL = '''summary = score_run(ordered)

# Instructions already sitting in the model. A defect whose only proposal is
# one of these has already had that fix tried, so it is escalated to a human
# rather than offered again.
applied_instructions = frozenset()
if spark.catalog.tableExists(lh + "eval_remediations"):
    applied_instructions = frozenset(
        r["instruction"]
        for r in spark.table(lh + "eval_remediations")
                      .filter("dry_run = false AND persisted = true")
                      .select("instruction").distinct().collect()
    )
print(f"{len(applied_instructions)} instruction(s) already applied to the model")

proposals = propose_fixes(ordered, expectations, applied_instructions)

print(f"score             : {summary['score']} / {summary['max_score']}")
print(f"flakes            : {summary['flake_questions'] or 'none'}")
print(f"stable failures   : {summary['failure_questions'] or 'none'}")
print(f"errored questions : {summary['errored_questions'] or 'none'}")
print(f"guardrails lost   : {summary['guardrails_lost'] or 'none'}")
print(f"agent errors      : {summary['error_attempts']} / {summary['attempt_count']}")
print(f"median latency ms : {summary['median_latency_ms']}")

if proposals:
    print("\\nproposed fixes, none of which are applied automatically:")
    for p in proposals:
        print(f"  {p.question_id}  tier {p.tier}  {TIER_ACTION[p.tier]}")
        print(f"      target   : {p.fix_target}")
        print(f"      rationale: {p.rationale}")
        if p.proposed_instruction:
            print(f"      approve  : add this to the {p.instruction_target} instructions")
            print(f"                 \\"{p.proposed_instruction}\\"")
else:
    print("\\nno defects, so nothing to propose")
'''


WRITE_CELL = '''from pyspark.sql import Row
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, TimestampType, BooleanType,
)

runs_table = f"{TABLE_PREFIX}_runs"
results_table = f"{TABLE_PREFIX}_results"
defects_table = f"{TABLE_PREFIX}_defects"

# Previous score, so a regression can be detected rather than just a low score.
previous_score = None
if spark.catalog.tableExists(lh + runs_table):
    prior = (
        spark.table(lh + runs_table)
             .filter(F.col("surface") == SURFACE)
             .orderBy(F.col("run_ts").desc())
             .limit(1)
             .collect()
    )
    if prior:
        previous_score = int(prior[0]["score"])

alerts = alert_conditions(summary, previous_score)
alert_severity = "high" if any(a["severity"] == "high" for a in alerts) else (
    "medium" if alerts else "none"
)

runs_schema = StructType([
    StructField("run_id", StringType()),
    StructField("run_ts", TimestampType()),
    StructField("surface", StringType()),
    StructField("workspace_id", StringType()),
    StructField("data_agent_id", StringType()),
    StructField("repeat_count", IntegerType()),
    StructField("score", IntegerType()),
    StructField("max_score", IntegerType()),
    StructField("previous_score", IntegerType()),
    StructField("flake_count", IntegerType()),
    StructField("failure_count", IntegerType()),
    StructField("guardrails_lost_count", IntegerType()),
    StructField("errored_count", IntegerType()),
    StructField("error_attempts", IntegerType()),
    StructField("attempt_count", IntegerType()),
    StructField("median_latency_ms", IntegerType()),
    StructField("alert_count", IntegerType()),
    StructField("alert_severity", StringType()),
    StructField("alert_detail", StringType()),
])

runs_row = Row(
    run_id=run_id,
    run_ts=run_ts,
    surface=SURFACE,
    workspace_id=WORKSPACE_ID,
    data_agent_id=DATA_AGENT_ID,
    repeat_count=int(REPEAT),
    score=int(summary["score"]),
    max_score=int(summary["max_score"]),
    previous_score=previous_score,
    flake_count=int(summary["flake_count"]),
    failure_count=len(summary["failure_questions"]),
    guardrails_lost_count=len(summary["guardrails_lost"]),
    errored_count=len(summary["errored_questions"]),
    error_attempts=int(summary["error_attempts"]),
    attempt_count=int(summary["attempt_count"]),
    median_latency_ms=int(summary["median_latency_ms"]),
    alert_count=len(alerts),
    alert_severity=alert_severity,
    alert_detail=" | ".join(f"[{a['severity']}] {a['condition']}: {a['detail']}" for a in alerts),
)

runs_df = spark.createDataFrame([runs_row], schema=runs_schema)
runs_df.write.mode("append").format("delta").saveAsTable(lh + runs_table)

results_schema = StructType([
    StructField("run_id", StringType()),
    StructField("run_ts", TimestampType()),
    StructField("question_id", StringType()),
    StructField("kind", StringType()),
    StructField("attempt", IntegerType()),
    StructField("grade", StringType()),
    StructField("detail", StringType()),
    StructField("classification", StringType()),
    StructField("latency_ms", IntegerType()),
    StructField("answer", StringType()),
])

result_rows = [
    Row(
        run_id=run_id, run_ts=run_ts, question_id=r.question_id, kind=r.kind,
        attempt=int(a.attempt), grade=a.grade, detail=a.detail,
        classification=r.classification, latency_ms=int(a.latency_ms), answer=a.answer,
    )
    for r in ordered for a in r.attempts
]

spark.createDataFrame(result_rows, schema=results_schema) \\
     .write.mode("append").format("delta").saveAsTable(lh + results_table)

defects_schema = StructType([
    StructField("run_id", StringType()),
    StructField("run_ts", TimestampType()),
    StructField("question_id", StringType()),
    StructField("classification", StringType()),
    StructField("tier", IntegerType()),
    StructField("fix_target", StringType()),
    StructField("rationale", StringType()),
    StructField("proposed_instruction", StringType()),
    StructField("instruction_target", StringType()),
    StructField("auto_appliable", BooleanType()),
    StructField("automatable", BooleanType()),
    StructField("action", StringType()),
    StructField("status", StringType()),
])

defect_rows = [
    Row(
        run_id=run_id, run_ts=run_ts, question_id=p.question_id,
        classification=p.classification, tier=int(p.tier),
        fix_target=p.fix_target, rationale=p.rationale,
        proposed_instruction=p.proposed_instruction,
        instruction_target=p.instruction_target,
        auto_appliable=bool(p.auto_appliable),
        automatable=bool(p.automatable), action=TIER_ACTION[p.tier],
        status="awaiting_human_approval",
    )
    for p in proposals
]

# Create the table even on a clean run so downstream items have something to
# bind to. An empty dashboard is better than a broken one.
defects_df = spark.createDataFrame(defect_rows, schema=defects_schema)
defects_df.write.mode("append").format("delta").saveAsTable(lh + defects_table)

print(f"wrote {runs_table}, {results_table}, {defects_table}")
print(f"previous score {previous_score} -> {summary['score']}")
'''


KUSTO_CELL = '''import notebookutils

kusto_token = notebookutils.credentials.getToken(KUSTO_URI)


def to_kusto(df, table):
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
    print(f"published {df.count()} row(s) to {KUSTO_DB}.{table}")


to_kusto(runs_df, "eval_runs")

# Defects carry the literal instruction a human is asked to approve, so the
# dashboard can show the exact text rather than a description of it.
if defect_rows:
    to_kusto(defects_df, "eval_defects")
else:
    print("no defects to publish")

print(f"alert_severity={alert_severity} alert_count={len(alerts)}")
'''


ALERT_CELL = '''if alerts:
    print(f"{len(alerts)} alert(s), highest severity {alert_severity}\\n")
    for a in alerts:
        print(f"[{a['severity']}] {a['condition']}")
        print(f"    {a['detail']}\\n")
    print(
        "Activator watches eval_runs. A human confirms the defect before any "
        "fix is written, and no proposal may ever add a verified answer."
    )
else:
    print("no alerts, nothing to confirm")

display(
    spark.table(lh + runs_table)
         .orderBy(F.col("run_ts").desc())
         .select(
             "run_ts", "surface", "score", "previous_score", "flake_count",
             "failure_count", "guardrails_lost_count", "alert_severity",
         )
         .limit(10)
)
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


if __name__ == "__main__":
    main()
