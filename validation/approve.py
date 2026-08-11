"""Approve or reject a proposed remediation.

This is the human gate. Approving writes a row that carries its own copy of
the instruction text, so that editing the proposal afterwards cannot change
what gets applied. You approve a sentence, not a pointer.

The eventhouse is the only approval store. Both tables are append only and
nothing is ever mutated, which matters because Kusto cannot update a row and
a design that pretends otherwise ends up being reconciled by hand.

"Still open" is therefore derived rather than stored:

    an approval is open when it is approved and no persisted remediation
    references its approval_id

That one rule is used identically by this script, by the remediation
notebook, by the Activator rule and by the dashboard, so none of them can
disagree about what is outstanding.

Usage:
    python validation/approve.py --list
    python validation/approve.py --open
    python validation/approve.py --question Q10 --by you@example.com
    python validation/approve.py --question Q12 --by you@example.com --reject \\
        --note "wrong diagnosis, the measure is at fault"
    python validation/approve.py --question Q10 --card
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from approval_card import (  # noqa: E402
    approval_command,
    card_json,
)
from config import (  # noqa: E402
    KUSTO_DATABASE_NAME as KUSTO_DB,
    KUSTO_URI as CLUSTER_URI,
    require,
)

# The one definition of outstanding work. Everything that needs to know what
# is still open uses this, so nothing can drift.
OPEN_APPROVALS_KQL = """eval_approvals
| where decision == "approved"
| join kind=leftanti (
    eval_remediations
    | where persisted == true
    | distinct approval_id
  ) on approval_id"""

# The queue as a person should read it: one row per defect, its current state,
# and the exact sentence they are being asked to approve.
QUEUE_KQL = """eval_defects
| summarize arg_max(run_ts, *) by question_id
| join kind=leftouter (
    eval_approvals
    | summarize arg_max(approved_ts, decision, approved_by, approval_id) by question_id
  ) on question_id
| join kind=leftouter (
    eval_remediations
    | where persisted == true
    | summarize arg_max(recorded_ts, applied_ts, verified) by approval_id
  ) on approval_id
| extend state = case(
    isempty(decision), "awaiting approval",
    decision == "rejected", "rejected",
    isnull(applied_ts), "approved, not yet applied",
    verified, "applied and verified",
    "applied, not yet verified")
| project question_id, tier, auto_appliable, state, approved_by,
          proposed_instruction, rationale
| order by question_id asc"""


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


def list_queue() -> int:
    data = rows(kusto(QUEUE_KQL))
    if not data:
        print("no defects")
        return 0

    for qid, tier, auto, state, by, instruction, rationale in data:
        flag = "AUTO " if auto else "HUMAN"
        print(f"\n{qid}  tier {tier}  [{flag}]  {state}" + (f"  ({by})" if by else ""))
        print(f"  why : {rationale}")
        if instruction:
            print(f'  add : "{instruction}"')
        else:
            print("  add : nothing safe to apply automatically, a person writes this fix")
    print()
    return 0


def show_open() -> int:
    data = rows(kusto(
        f"{OPEN_APPROVALS_KQL}\n"
        "| project approved_ts, question_id, approved_by, proposed_instruction "
        "| order by approved_ts asc"
    ))
    if not data:
        print("no open approvals")
        return 0
    print(f"{len(data)} open approval(s), waiting to be applied:")
    for ts, qid, by, instruction in data:
        print(f"  {qid}  approved {ts} by {by}")
        print(f'    "{instruction[:120]}"')
    return 0


def defect(question_id: str) -> tuple[str, str, int, bool, str, str]:
    """The latest defect for a question, or exit."""
    data = rows(kusto(
        f"eval_defects | where question_id == '{question_id}' "
        "| summarize arg_max(run_ts, *) by question_id "
        "| project proposed_instruction, instruction_target, tier, auto_appliable, "
        "classification, rationale"
    ))
    if not data:
        raise SystemExit(f"no defect found for {question_id}")
    return tuple(data[0])  # type: ignore[return-value]


def show_card(question_id: str) -> int:
    """Print the Adaptive Card for one defect.

    The same card a flow posts to Outlook or Teams, rendered with this
    defect's values, so it can be read before anyone builds the flow. Run it
    without --question to get the flow template with its bindings intact.
    """
    if not question_id:
        print(card_json())
        return 0

    instruction, _target, _tier, _auto, classification, rationale = defect(question_id)
    print(card_json(
        question_id=question_id,
        classification=classification,
        proposed_instruction=instruction,
        rationale=rationale,
    ))
    return 0


def decide(question_id: str, approved_by: str, reject: bool, note: str) -> int:
    instruction, target, tier, auto, _classification, _rationale = defect(question_id)
    decision = "rejected" if reject else "approved"

    if decision == "approved" and not auto:
        raise SystemExit(
            f"{question_id} is tier {tier} and carries no automatically appliable "
            "instruction. It needs a person to open the model, so there is "
            "nothing to approve here. Reject it or fix it by hand."
        )

    if decision == "approved":
        already = rows(kusto(
            f"{OPEN_APPROVALS_KQL}\n| where question_id == '{question_id}' | count"
        ))
        if already and already[0][0]:
            raise SystemExit(
                f"{question_id} already has an open approval waiting to be applied. "
                "Approving twice would queue the same change again."
            )

    approval_id = str(uuid.uuid4())

    # Built by approval_card.approval_command so that this command and the one
    # a Power Automate card writes are the same command.
    kusto(
        approval_command(
            question_id=question_id,
            instruction_target=target,
            proposed_instruction=instruction,
            approved_by=approved_by,
            decision=decision,
            note=note,
            approval_id=approval_id,
        ),
        endpoint="mgmt",
    )

    print(f"{decision} {question_id} by {approved_by}")
    print(f"approval_id {approval_id}")
    if decision == "approved":
        print()
        print("The approvals rule in the activator polls every 60 seconds and will")
        print("run the agent_remediate notebook. Nothing else is needed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="show the whole queue")
    parser.add_argument("--open", action="store_true",
                        help="show only approvals waiting to be applied")
    parser.add_argument("--question", help="question id, for example Q10")
    parser.add_argument("--by", help="who is approving. Required to approve")
    parser.add_argument("--reject", action="store_true")
    parser.add_argument("--note", default="")
    parser.add_argument("--card", action="store_true",
                        help="print the Adaptive Card a flow would post, and exit")
    args = parser.parse_args()

    if args.card and not args.question:
        # No question means the flow template, which needs no cluster at all.
        return show_card("")

    require("FABRIC_KUSTO_URI")

    if args.card:
        return show_card(args.question)
    if args.open:
        return show_open()
    if args.list or not args.question:
        return list_queue()
    if not args.by:
        raise SystemExit("--by is required. A governed model does not take "
                         "anonymous changes.")
    return decide(args.question, args.by, args.reject, args.note)


if __name__ == "__main__":
    sys.exit(main())
