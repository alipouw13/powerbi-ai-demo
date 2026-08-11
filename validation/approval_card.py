"""The approval contract: one Adaptive Card, one Kusto append command.

An approval is one row in `eval_approvals`. Everything downstream keys off
that row and nothing downstream cares who wrote it, so any surface that can
write the row can approve: the command line, a Power Automate card in
Outlook, a Teams card, a Logic App.

That is exactly why the row has to be built in one place. Three surfaces each
hand-writing their own `.set-or-append` is three chances to forget the
escaping, to reference the defect instead of copying the sentence, or to
quietly drop `approved_by`.

Two rules are enforced here rather than trusted:

* **The instruction text is copied into the approval.** A person approves a
  specific sentence. The proposal can change on the next run, so an approval
  that pointed at the defect would mean something different tomorrow.
* **The approver is named.** A governed model does not take anonymous
  changes, and a blank `approved_by` is refused rather than defaulted.

Fabric Activator cannot render a button. Its email action is a notification,
not a form, so the card below is posted by Power Automate or Logic Apps
("Post an adaptive card to a user and wait for a response"), and the response
is turned into the command below. See `approval-by-email.md` for the flow.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

APPROVED = "approved"
REJECTED = "rejected"

# Power Automate binding expressions, so the card can be pasted into a flow
# unchanged. Rendering the card locally instead substitutes literal values.
FLOW_BINDINGS = {
    "question_id": "@{items('Apply_to_each')?['question_id']}",
    "classification": "@{items('Apply_to_each')?['classification']}",
    "proposed_instruction": "@{items('Apply_to_each')?['proposed_instruction']}",
    "rationale": "@{items('Apply_to_each')?['rationale']}",
}


def escape(value: str) -> str:
    """Escape a value for a Kusto double quoted string literal.

    Backslash first. Escaping the quotes before the backslashes turns
    `a\\` into `a\\"` and ends the literal early, which is both a broken
    command and the shape of an injection.
    """
    return (value or "").replace("\\", "\\\\").replace('"', '\\"')


def approval_command(
    *,
    question_id: str,
    instruction_target: str,
    proposed_instruction: str,
    approved_by: str,
    decision: str = APPROVED,
    note: str = "",
    approval_id: str | None = None,
    approved_ts: datetime | None = None,
) -> str:
    """Build the `.set-or-append` that records one human decision.

    Returned as text rather than executed, because the caller decides where it
    runs: `approve.py` posts it to the Kusto mgmt endpoint, a flow posts it
    through the Azure Data Explorer connector.
    """
    if decision not in (APPROVED, REJECTED):
        raise ValueError(f"decision must be {APPROVED!r} or {REJECTED!r}, got {decision!r}")
    if not (question_id or "").strip():
        raise ValueError("question_id is required")
    if not (approved_by or "").strip():
        raise ValueError(
            "approved_by is required. A governed model does not take anonymous changes."
        )
    if decision == APPROVED and not (proposed_instruction or "").strip():
        raise ValueError(
            "an approval carries the sentence that was approved. Approving an empty "
            "instruction would apply nothing and still consume the defect."
        )

    stamp = (approved_ts or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    return (
        ".set-or-append eval_approvals <| print "
        f'approval_id="{approval_id or uuid.uuid4()}", '
        f"approved_ts=datetime({stamp}), "
        f'question_id="{escape(question_id)}", '
        f'instruction_target="{escape(instruction_target)}", '
        f'proposed_instruction="{escape(proposed_instruction)}", '
        f'decision="{decision}", '
        f'approved_by="{escape(approved_by)}", '
        f'note="{escape(note)}"'
    )


def adaptive_card(
    *,
    question_id: str | None = None,
    classification: str | None = None,
    proposed_instruction: str | None = None,
    rationale: str | None = None,
) -> dict:
    """The card a person clicks.

    Called with no arguments it returns the flow template, with Power Automate
    bindings in place of values, ready to paste into the Outlook action.
    Called with a defect it renders that defect, which is what makes the card
    reviewable before anyone wires up a flow.

    The sentence itself is shown, never a summary of it. Somebody approving a
    change to a governed model should be reading the words that will be added.
    """
    values = {
        "question_id": question_id or FLOW_BINDINGS["question_id"],
        "classification": classification or FLOW_BINDINGS["classification"],
        "proposed_instruction": proposed_instruction
        or FLOW_BINDINGS["proposed_instruction"],
        "rationale": rationale or FLOW_BINDINGS["rationale"],
    }

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "size": "Medium",
                "weight": "Bolder",
                "text": "Data agent accuracy: approval needed",
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Question", "value": values["question_id"]},
                    {"title": "Problem", "value": values["classification"]},
                ],
            },
            {
                "type": "TextBlock",
                "wrap": True,
                "weight": "Bolder",
                "text": "Add this to the model AI instructions:",
            },
            {
                "type": "TextBlock",
                "wrap": True,
                "separator": True,
                "text": values["proposed_instruction"],
            },
            {
                "type": "TextBlock",
                "wrap": True,
                "isSubtle": True,
                "text": f"Why: {values['rationale']}",
            },
            {
                "type": "Input.Text",
                "id": "note",
                "isMultiline": True,
                "placeholder": "Optional note, recorded with the decision",
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Approve",
                "style": "positive",
                "data": {"decision": APPROVED, "question_id": values["question_id"]},
            },
            {
                "type": "Action.Submit",
                "title": "Reject",
                "style": "destructive",
                "data": {"decision": REJECTED, "question_id": values["question_id"]},
            },
        ],
    }


def card_json(**kwargs) -> str:
    return json.dumps(adaptive_card(**kwargs), indent=2)
