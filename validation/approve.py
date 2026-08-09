"""Approve or reject a proposed remediation.

This is the human gate, made durable. Approving writes a row that carries its
own copy of the instruction text, so that editing the proposal afterwards
cannot change what gets applied. You approve a sentence, not a pointer.

The row is written twice on purpose:

* Delta `eval_approvals` is the state of record, because it needs an `applied`
  flag that gets updated, and Kusto tables are append only.
* Kusto `eval_approvals` is what Activator watches and what the dashboard
  reads.

Usage:
    python validation/approve.py --list
    python validation/approve.py --question Q10 --by alison@example.com
    python validation/approve.py --question Q12 --by alison@example.com --reject \\
        --note "wrong diagnosis, the measure is at fault"
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

CLUSTER_URI = "https://trd-391auppsxutg30p2va.z9.kusto.fabric.microsoft.com"
KUSTO_DB = "EH_AgentEval"


def token(resource: str) -> str:
    result = subprocess.run(
        ["az", "account", "get-access-token", "--resource", resource,
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, shell=True, check=True,
    )
    return result.stdout.strip()


def kusto(csl: str, endpoint: str = "query") -> dict:
    body = json.dumps({"db": KUSTO_DB, "csl": csl}).encode("utf-8")
    request = urllib.request.Request(
        f"{CLUSTER_URI}/v1/rest/{endpoint}", data=body, method="POST",
        headers={
            "Authorization": f"Bearer {token(CLUSTER_URI)}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise SystemExit(f"Kusto HTTP {exc.code}: {detail}") from None


def rows(result: dict) -> list[list]:
    return result["Tables"][0]["Rows"]


def list_pending() -> int:
    result = kusto(
        "eval_defects "
        "| summarize arg_max(run_ts, *) by question_id "
        "| join kind=leftouter (eval_approvals "
        "  | summarize arg_max(approved_ts, decision, approved_by) by question_id) "
        "  on question_id "
        "| project question_id, tier, auto_appliable, decision, approved_by, "
        "          proposed_instruction, rationale "
        "| order by question_id asc"
    )
    data = rows(result)
    if not data:
        print("no defects")
        return 0

    for qid, tier, auto, decision, by, instruction, rationale in data:
        status = decision or "awaiting approval"
        flag = "AUTO" if auto else "HUMAN"
        print(f"\n{qid}  tier {tier}  [{flag}]  {status}"
              + (f"  ({by})" if by else ""))
        print(f"  why : {rationale}")
        if instruction:
            print(f"  add : \"{instruction}\"")
        else:
            print("  add : nothing safe to apply automatically, a person writes this fix")
    print()
    return 0


def escape(value: str) -> str:
    return (value or "").replace("\\", "\\\\").replace('"', '\\"')


def decide(question_id: str, approved_by: str, reject: bool, note: str) -> int:
    result = kusto(
        f"eval_defects | where question_id == '{question_id}' "
        "| summarize arg_max(run_ts, *) by question_id "
        "| project proposed_instruction, instruction_target, tier, auto_appliable"
    )
    data = rows(result)
    if not data:
        raise SystemExit(f"no defect found for {question_id}")

    instruction, target, tier, auto = data[0]
    decision = "rejected" if reject else "approved"

    if decision == "approved" and not auto:
        raise SystemExit(
            f"{question_id} is tier {tier} and carries no automatically appliable "
            "instruction. It needs a person to open the model, so there is "
            "nothing to approve here. Reject it or fix it by hand."
        )

    approval_id = str(uuid.uuid4())
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    kusto(
        f'.set-or-append eval_approvals <| print '
        f'approval_id="{approval_id}", '
        f'approved_ts=datetime({stamp}), '
        f'question_id="{escape(question_id)}", '
        f'instruction_target="{escape(target)}", '
        f'proposed_instruction="{escape(instruction)}", '
        f'decision="{decision}", '
        f'approved_by="{escape(approved_by)}", '
        f'note="{escape(note)}", '
        f"applied=bool(false)",
        endpoint="mgmt",
    )

    print(f"{decision} {question_id} by {approved_by}")
    print(f"approval_id {approval_id}")
    if decision == "approved":
        print()
        print("The approvals rule in the activator polls every 60 seconds and will")
        print("run the agent_remediate notebook. Nothing else is needed.")
        print()
        print("Also insert the same row into the Delta eval_approvals table if you")
        print("want the notebook to see it when run by hand:")
        print(f"  python validation/approve.py --emit-delta --question {question_id}")
    return 0


def emit_delta(question_id: str) -> int:
    """Print the Spark snippet that mirrors a Kusto approval into Delta."""
    result = kusto(
        "eval_approvals "
        f"| where question_id == '{question_id}' and applied == false "
        "| top 1 by approved_ts desc "
        "| project approval_id, approved_ts, question_id, instruction_target, "
        "          proposed_instruction, decision, approved_by, note"
    )
    data = rows(result)
    if not data:
        raise SystemExit(f"no unapplied approval for {question_id}")

    aid, ts, qid, target, instruction, decision, by, note = data[0]
    print(f"""from datetime import datetime, timezone
from pyspark.sql import Row

row = Row(
    approval_id={aid!r},
    approved_ts=datetime.fromisoformat({ts!r}.replace('Z', '+00:00')),
    question_id={qid!r},
    instruction_target={target!r},
    proposed_instruction={instruction!r},
    decision={decision!r},
    approved_by={by!r},
    note={note!r},
    applied=False,
    applied_ts=None,
)
spark.createDataFrame([row], schema=spark.table('LH_ContosoCoffee.eval_approvals').schema) \\
     .write.mode('append').format('delta').saveAsTable('LH_ContosoCoffee.eval_approvals')
print('approval mirrored to Delta')""")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="show the queue")
    parser.add_argument("--question", help="question id, for example Q10")
    parser.add_argument("--by", help="who is approving. Required to approve")
    parser.add_argument("--reject", action="store_true")
    parser.add_argument("--note", default="")
    parser.add_argument("--emit-delta", action="store_true",
                        help="print the Spark snippet to mirror into Delta")
    args = parser.parse_args()

    if args.list or not args.question:
        return list_pending()
    if args.emit_delta:
        return emit_delta(args.question)
    if not args.by:
        raise SystemExit("--by is required. A governed model does not take "
                         "anonymous changes.")
    return decide(args.question, args.by, args.reject, args.note)


if __name__ == "__main__":
    sys.exit(main())
