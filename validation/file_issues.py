"""File GitHub issues for defects that cannot be fixed automatically.

Tier 2 defects need a person to open the model and think. This does not try to
fix them. It writes down what was observed, so that the thinking starts from
evidence rather than from "the agent seems wrong sometimes".

Each issue carries the grades across every attempt, the answers the agent
actually gave, and the expected value. That is the difference between a
diagnosis and a complaint.

Deliberately not automatic. It runs when somebody asks it to, because an
evaluation loop that opens issues on a schedule produces a backlog nobody
reads, and the point of tier 2 is that a human is already involved.

Usage:
    python validation/file_issues.py --dry-run
    python validation/file_issues.py
    python validation/file_issues.py --question Q10
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

CLUSTER_URI = "https://trd-391auppsxutg30p2va.z9.kusto.fabric.microsoft.com"
KUSTO_DB = "EH_AgentEval"
REPO = "alipouw13/powerbi-ai-demo"
LABEL = "agent-accuracy"

# Only defects a person has to handle. Tier 1 has an approvable sentence and
# belongs in the approval queue, not in a backlog.
TIER_TWO_KQL = """eval_defects
| summarize arg_max(run_ts, *) by question_id
| where tier >= 2
| project question_id, run_id, run_ts, classification, tier, fix_target, rationale
| order by question_id asc"""


def token(resource: str) -> str:
    result = subprocess.run(
        ["az", "account", "get-access-token", "--resource", resource,
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def kusto(csl: str) -> list[dict]:
    body = json.dumps({"db": KUSTO_DB, "csl": csl}).encode("utf-8")
    request = urllib.request.Request(
        f"{CLUSTER_URI}/v1/rest/query", data=body, method="POST",
        headers={"Authorization": f"Bearer {token(CLUSTER_URI)}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise SystemExit(f"Kusto HTTP {exc.code}: {detail}") from None

    table = payload["Tables"][0]
    columns = [c["ColumnName"] for c in table["Columns"]]
    return [dict(zip(columns, row)) for row in table["Rows"]]


def gh(args: list[str]) -> str:
    # No shell=True. The issue body contains the agent's own answers verbatim,
    # and on Windows a list plus shell=True is joined and handed to cmd.exe,
    # where an embedded quote followed by & or | escapes the argument and runs
    # whatever comes next.
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"gh {' '.join(args[:3])} failed:\n{result.stderr[:800]}")
    return result.stdout.strip()


def existing_issue(question_id: str) -> str | None:
    """Never file the same defect twice. A duplicate backlog is not evidence."""
    raw = gh([
        "issue", "list", "--repo", REPO, "--state", "open",
        "--label", LABEL, "--search", question_id,
        "--json", "number,title",
    ])
    for issue in json.loads(raw or "[]"):
        if question_id in issue["title"]:
            return str(issue["number"])
    return None


def evidence(question_id: str, run_id: str) -> str:
    try:
        attempts = kusto(
            f"eval_results | where run_id == '{run_id}' and question_id == '{question_id}' "
            "| project attempt, grade, detail, answer | order by attempt asc"
        )
    except SystemExit:
        # Runs from before per-attempt results were published to the
        # eventhouse. Worth filing the issue anyway, with less to go on.
        return ("_Per-attempt detail is not in the eventhouse for this run. "
                "Query `eval_results` in the lakehouse for run "
                f"`{run_id}`._")

    if not attempts:
        return "_No per-attempt detail recorded for this run._"

    lines = ["| Attempt | Grade | Why |", "| --- | --- | --- |"]
    for row in attempts:
        detail = (row["detail"] or "").replace("|", "\\|")[:160]
        lines.append(f"| {row['attempt']} | {row['grade']} | {detail} |")

    lines.append("")
    lines.append("### What the agent actually said")
    lines.append("")
    for row in attempts:
        answer = (row["answer"] or "").strip() or "_empty response_"
        lines.append(f"**Attempt {row['attempt']}, graded {row['grade']}**")
        lines.append("")
        lines.append("> " + answer.replace("\n", "\n> ")[:1200])
        lines.append("")
    return "\n".join(lines)


def build_body(defect: dict) -> str:
    return f"""Filed by the agent accuracy loop. This defect has no safe automatic fix,
so it needs a person.

| | |
| --- | --- |
| Question | `{defect['question_id']}` |
| Classification | {defect['classification']} |
| Tier | {defect['tier']} |
| Likely area | {defect['fix_target']} |
| First seen in run | `{defect['run_id']}` |
| Run timestamp | {defect['run_ts']} |

## Why this is not automatic

{defect['rationale']}

## Evidence

{evidence(defect['question_id'], defect['run_id'])}

## Before you change anything

- The question is asked exactly as written in
  [`validation/question-bank.md`](validation/question-bank.md). Rewording it
  until it passes hides the failure rather than fixing it.
- Expected values come from `python validation/ground_truth.py`. Never write
  one by hand.
- Fixes belong in the semantic model, not the data agent instruction box.
  Agent-level instructions are not passed to the DAX generation step, so a
  fix written there looks like a change and does nothing.
- A verified answer is a patch, not a fix. It solves one phrasing. If you use
  one, say so, because it does not improve the model.

## Done when

The question reaches stable pass across every attempt of a full evaluation
run, and `eval_runs` shows the score moving. Closing this because the next
single run happened to pass is how a flake gets declared fixed.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be filed and file nothing")
    parser.add_argument("--question", help="limit to one question id")
    args = parser.parse_args()

    defects = kusto(TIER_TWO_KQL)
    if args.question:
        defects = [d for d in defects if d["question_id"] == args.question.upper()]

    if not defects:
        print("no tier 2 defects, nothing to file")
        return 0

    print(f"{len(defects)} tier 2 defect(s)\n")
    filed = skipped = 0

    for defect in defects:
        question_id = defect["question_id"]
        title = f"Agent accuracy: {question_id} needs a human ({defect['classification']})"

        if not args.dry_run:
            duplicate = existing_issue(question_id)
            if duplicate:
                print(f"  {question_id}: already open as #{duplicate}, skipping")
                skipped += 1
                continue

        body = build_body(defect)

        if args.dry_run:
            print("=" * 70)
            print(title)
            print("=" * 70)
            print(body)
            print()
            filed += 1
            continue

        # Create the label on first use rather than assuming it exists.
        subprocess.run(
            ["gh", "label", "create", LABEL, "--repo", REPO,
             "--description", "Raised by the data agent accuracy loop",
             "--color", "B60205"],
            capture_output=True, text=True,
        )
        # Body via a file, not an argument. It contains untrusted agent output
        # and can be long enough to hit command line length limits.
        with tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(body)
            body_path = handle.name
        try:
            url = gh(["issue", "create", "--repo", REPO, "--title", title,
                      "--body-file", body_path, "--label", LABEL])
        finally:
            os.unlink(body_path)
        print(f"  {question_id}: {url}")
        filed += 1

    print()
    verb = "would file" if args.dry_run else "filed"
    print(f"{verb} {filed}, skipped {skipped} already open")
    return 0


if __name__ == "__main__":
    sys.exit(main())
