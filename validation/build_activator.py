"""Create or update the Agent Accuracy Alerts activator.

Builds ReflexEntities.json for EventTrigger rules over KQL sources, then
creates the Activator item through the Fabric REST API.

Three rules, and the split between them matters:

1. "High severity accuracy alert" fires when a run publishes
   alert_severity = "high". It is about a run getting worse.
2. "Remediation queue waiting for approval" fires when a run leaves defects
   nobody has decided on yet. It is about work sitting still, which the
   severity rule cannot see: a run whose severity is medium, or a queue that
   nobody emptied after the one email it did send, both look silent.
3. "Approved remediation, apply it" fires on a human decision and runs the
   remediation notebook.

Every rule is deliberately thin. All of the judgement about what counts as a
regression, a flake, or a lost guardrail lives in validation/eval_harness.py,
where it is covered by unit tests. A threshold buried in a portal rule is a
threshold nobody can test.

Usage:
    python validation/build_activator.py [--print-only]
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (  # noqa: E402
    FABRIC_API,
    KQL_DATABASE_ID,
    RECIPIENTS,
    REMEDIATION_NOTEBOOK_ID,
    WORKSPACE_ID,
    require,
)

ACTIVATOR_NAME = "Agent Accuracy Alerts"
TEMPLATE_VERSION = "1.2.4"

# One digest per run rather than one email per defect. Seven emails that each
# say "one question needs a decision" is how a person learns to filter the
# whole rule out.
#
# run_ts is the event time, and it is the reason this works at all. An
# Activator KQL source only sees rows whose event time falls inside the window
# it is currently polling, so a query that stamped the digest with the time the
# queue was last emptied, or with an aggregate over all history, would sit
# permanently outside the window and never fire. Defect rows are appended with
# the run's own timestamp, so they arrive in the same window as the run
# summary that the severity rule reacts to.
PENDING_APPROVALS_QUERY = """declare query_parameters(startTime:datetime, endTime:datetime);
eval_defects
| where run_ts between (startTime .. endTime)
| join kind=leftanti (
    eval_approvals
    | distinct question_id
  ) on question_id
| extend route = iff(auto_appliable == true and isnotempty(proposed_instruction),
                     "approve", "human")
| summarize pending_count = count(),
            approvable_count = countif(route == "approve"),
            needs_human_count = countif(route == "human"),
            questions = strcat_array(make_list(question_id), ", ")
    by run_ts
| where pending_count > 0
| extend queue_state = "pending"
| project run_ts, queue_state, pending_count, approvable_count,
          needs_human_count, questions
| order by run_ts asc"""

# Return every run and let the rule decide. The skill guidance is explicit
# that the KQL query is the data source, not the rule engine.
KQL_QUERY = """declare query_parameters(startTime:datetime, endTime:datetime);
eval_runs
| where run_ts between (startTime .. endTime)
| project run_ts, run_id, surface, score, max_score, previous_score,
          flake_count, failure_count, guardrails_lost_count,
          errored_count, alert_count, alert_severity, alert_detail
| order by run_ts asc"""

# Open approvals, derived rather than stored. An approval is outstanding when
# it is approved and no persisted remediation references its approval_id.
# Kusto is append only, so "applied" cannot be a mutable flag. The same
# expression lives in approve.py and in the remediation notebook, and it is
# the reason none of them can disagree about what is still outstanding.
APPROVALS_QUERY = """declare query_parameters(startTime:datetime, endTime:datetime);
eval_approvals
| where approved_ts between (startTime .. endTime)
| where decision == "approved"
| join kind=leftanti (
    eval_remediations
    | where persisted == true
    | distinct approval_id
  ) on approval_id
| project approved_ts, approval_id, question_id, decision, approved_by,
          instruction_target, proposed_instruction
| order by approved_ts asc"""


def stringify(template: dict) -> str:
    return json.dumps(template, separators=(",", ":"))


def build_entities() -> list[dict]:
    container_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    source_event_id = str(uuid.uuid4())
    rule_id = str(uuid.uuid4())

    container = {
        "uniqueIdentifier": container_id,
        "payload": {"name": "Agent accuracy", "type": "kqlQueries"},
        "type": "container-v1",
    }

    source = {
        "uniqueIdentifier": source_id,
        "payload": {
            "name": "Agent evaluation runs",
            "runSettings": {"executionIntervalInSeconds": 300},
            "query": {"queryString": KQL_QUERY},
            "eventhouseItem": {
                "itemId": KQL_DATABASE_ID,
                "workspaceId": WORKSPACE_ID,
                "itemType": "KustoDatabase",
            },
            "queryParameters": [
                {
                    "name": "startTime",
                    "type": "DURATION_START",
                    "value": "2026-01-01T00:00:00Z",
                },
                {
                    "name": "endTime",
                    "type": "DURATION_END",
                    "value": "2026-01-01T00:05:00Z",
                },
            ],
            "eventTimeSettings": {
                "timeFieldName": "run_ts",
                "ingestionDelayInSeconds": 120,
                "timeZone": "UTC",
            },
            "metadata": {
                "workspaceId": WORKSPACE_ID,
                "measureName": "",
                "querySetId": "",
                "queryId": "",
            },
            "parentContainer": {"targetUniqueIdentifier": container_id},
        },
        "type": "kqlSource-v1",
    }

    source_event = {
        "uniqueIdentifier": source_event_id,
        "payload": {
            "name": "Evaluation run",
            "parentContainer": {"targetUniqueIdentifier": container_id},
            "definition": {
                "type": "Event",
                "instance": stringify({
                    "templateId": "SourceEvent",
                    "templateVersion": TEMPLATE_VERSION,
                    "steps": [{
                        "name": "SourceEventStep",
                        "id": str(uuid.uuid4()),
                        "rows": [{
                            "name": "SourceSelector",
                            "kind": "SourceReference",
                            "arguments": [
                                {"name": "entityId", "type": "string", "value": source_id}
                            ],
                        }],
                    }],
                }),
            },
        },
        "type": "timeSeriesView-v1",
    }

    def event_field(field: str) -> dict:
        return {
            "kind": "EventFieldReference",
            "type": "complex",
            "arguments": [{"name": "fieldName", "type": "string", "value": field}],
        }

    rule_template = {
        "templateId": "EventTrigger",
        "templateVersion": TEMPLATE_VERSION,
        "steps": [
            {
                "name": "FieldsDefaultsStep",
                "id": str(uuid.uuid4()),
                "rows": [{
                    "name": "EventSelector",
                    "kind": "Event",
                    "arguments": [{
                        "kind": "EventReference",
                        "type": "complex",
                        "name": "event",
                        "arguments": [
                            {"name": "entityId", "type": "string", "value": source_event_id}
                        ],
                    }],
                }],
            },
            {
                "name": "EventDetectStep",
                "id": str(uuid.uuid4()),
                "rows": [
                    {
                        "name": "EventFieldSelector",
                        "kind": "EventField",
                        "arguments": [
                            {"name": "fieldName", "type": "string", "value": "alert_severity"}
                        ],
                    },
                    {
                        "name": "TextValueCondition",
                        "kind": "TextValueCondition",
                        "arguments": [
                            {"name": "op", "type": "string", "value": "IsEqualTo"},
                            {"name": "value", "type": "string", "value": "high"},
                        ],
                    },
                ],
            },
            {
                "name": "ActStep",
                "id": str(uuid.uuid4()),
                "rows": [{
                    # Email rather than Teams, because this tenant has no
                    # Teams. To switch to a Teams message instead, replace
                    # this whole row with:
                    #
                    #   {"name": "TeamsBinding", "kind": "TeamsMessage",
                    #    "arguments": [
                    #        {"name": "messageLocale", "type": "string",
                    #         "value": "en-us"},
                    #        {"name": "recipients", "type": "array",
                    #         "values": [{"type": "string", "value": addr}
                    #                    for addr in RECIPIENTS]},
                    #        {"name": "headline", ...},          # same as below
                    #        {"name": "optionalMessage", ...},   # same as below
                    #        {"name": "additionalInformation", ...},
                    #    ]}
                    #
                    # Teams takes `recipients` and has no `subject`. Email
                    # takes `sentTo` / `copyTo` / `bCCTo` and requires
                    # `subject`. Every other field is identical, and the
                    # rule around it does not change at all.
                    "name": "EmailBinding",
                    "kind": "EmailMessage",
                    "arguments": [
                        {"name": "messageLocale", "type": "string", "value": "en-us"},
                        {
                            "name": "sentTo",
                            "type": "array",
                            "values": [
                                {"type": "string", "value": r} for r in RECIPIENTS
                            ],
                        },
                        {"name": "copyTo", "type": "array", "values": []},
                        {"name": "bCCTo", "type": "array", "values": []},
                        {
                            "name": "subject",
                            "type": "array",
                            "values": [{
                                "type": "string",
                                "value": "Data agent accuracy regression",
                            }],
                        },
                        {
                            "name": "headline",
                            "type": "array",
                            "values": [{
                                "type": "string",
                                "value": (
                                    "An evaluation run raised a high severity alert. "
                                    "Confirm before any fix."
                                ),
                            }],
                        },
                        {
                            "name": "optionalMessage",
                            "type": "array",
                            "values": [
                                {
                                    "type": "string",
                                    "value": (
                                        "Open the Agent Accuracy dashboard and read "
                                        "the remediation queue. Each failing question "
                                        "carries the exact sentence that would fix it. "
                                        "Approve one with: python validation/approve.py "
                                        "--question <id> --by <you>. Nothing has been "
                                        "changed automatically. Detail: "
                                    ),
                                },
                                event_field("alert_detail"),
                            ],
                        },
                        {
                            "name": "additionalInformation",
                            "type": "array",
                            "values": [
                                {
                                    "kind": "NameReferencePair",
                                    "type": "complex",
                                    "arguments": [
                                        {"name": "name", "type": "string", "value": name},
                                        {
                                            "kind": "EventFieldReference",
                                            "type": "complexReference",
                                            "name": "reference",
                                            "arguments": [
                                                {
                                                    "name": "fieldName",
                                                    "type": "string",
                                                    "value": name,
                                                }
                                            ],
                                        },
                                    ],
                                }
                                for name in (
                                    "score",
                                    "previous_score",
                                    "flake_count",
                                    "failure_count",
                                    "guardrails_lost_count",
                                    "run_id",
                                )
                            ],
                        },
                    ],
                }],
            },
        ],
    }

    rule = {
        "uniqueIdentifier": rule_id,
        "payload": {
            "name": "High severity accuracy alert",
            "description": "Created by: skills-for-fabric",
            "parentContainer": {"targetUniqueIdentifier": container_id},
            "definition": {
                "type": "Rule",
                "instance": stringify(rule_template),
                "settings": {"shouldRun": True, "shouldApplyRuleOnUpdate": False},
            },
        },
        "type": "timeSeriesView-v1",
    }

    # ----------------------------------------------------------------------
    # The queue rule: work that is sitting still
    # ----------------------------------------------------------------------
    #
    # The severity rule answers "did this run get worse". It cannot answer
    # "is anything waiting for me", and those are different questions. A run
    # can be steady at medium severity, or high severity can have alerted
    # once a week ago, while seven defects sit in the queue with nobody
    # deciding on them. This rule is the one that says so.

    pending_source_id = str(uuid.uuid4())
    pending_event_id = str(uuid.uuid4())
    pending_rule_id = str(uuid.uuid4())

    pending_source = {
        "uniqueIdentifier": pending_source_id,
        "payload": {
            "name": "Remediation queue",
            "runSettings": {"executionIntervalInSeconds": 300},
            "query": {"queryString": PENDING_APPROVALS_QUERY},
            "eventhouseItem": {
                "itemId": KQL_DATABASE_ID,
                "workspaceId": WORKSPACE_ID,
                "itemType": "KustoDatabase",
            },
            "queryParameters": [
                {"name": "startTime", "type": "DURATION_START",
                 "value": "2026-01-01T00:00:00Z"},
                {"name": "endTime", "type": "DURATION_END",
                 "value": "2026-01-01T00:05:00Z"},
            ],
            "eventTimeSettings": {
                "timeFieldName": "run_ts",
                "ingestionDelayInSeconds": 120,
                "timeZone": "UTC",
            },
            "metadata": {
                "workspaceId": WORKSPACE_ID,
                "measureName": "",
                "querySetId": "",
                "queryId": "",
            },
            "parentContainer": {"targetUniqueIdentifier": container_id},
        },
        "type": "kqlSource-v1",
    }

    pending_event = {
        "uniqueIdentifier": pending_event_id,
        "payload": {
            "name": "Approval queue",
            "parentContainer": {"targetUniqueIdentifier": container_id},
            "definition": {
                "type": "Event",
                "instance": stringify({
                    "templateId": "SourceEvent",
                    "templateVersion": TEMPLATE_VERSION,
                    "steps": [{
                        "name": "SourceEventStep",
                        "id": str(uuid.uuid4()),
                        "rows": [{
                            "name": "SourceSelector",
                            "kind": "SourceReference",
                            "arguments": [{
                                "name": "entityId", "type": "string",
                                "value": pending_source_id,
                            }],
                        }],
                    }],
                }),
            },
        },
        "type": "timeSeriesView-v1",
    }

    pending_rule_template = {
        "templateId": "EventTrigger",
        "templateVersion": TEMPLATE_VERSION,
        "steps": [
            {
                "name": "FieldsDefaultsStep",
                "id": str(uuid.uuid4()),
                "rows": [{
                    "name": "EventSelector",
                    "kind": "Event",
                    "arguments": [{
                        "kind": "EventReference",
                        "type": "complex",
                        "name": "event",
                        "arguments": [{
                            "name": "entityId", "type": "string",
                            "value": pending_event_id,
                        }],
                    }],
                }],
            },
            {
                # The count test is in the query, not here. queue_state only
                # exists on rows the query already decided are worth sending,
                # so the portal rule stays a string comparison and the logic
                # stays somewhere a test can reach it.
                "name": "EventDetectStep",
                "id": str(uuid.uuid4()),
                "rows": [
                    {
                        "name": "EventFieldSelector",
                        "kind": "EventField",
                        "arguments": [{
                            "name": "fieldName", "type": "string",
                            "value": "queue_state",
                        }],
                    },
                    {
                        "name": "TextValueCondition",
                        "kind": "TextValueCondition",
                        "arguments": [
                            {"name": "op", "type": "string", "value": "IsEqualTo"},
                            {"name": "value", "type": "string", "value": "pending"},
                        ],
                    },
                ],
            },
            {
                "name": "ActStep",
                "id": str(uuid.uuid4()),
                "rows": [{
                    "name": "EmailBinding",
                    "kind": "EmailMessage",
                    "arguments": [
                        {"name": "messageLocale", "type": "string", "value": "en-us"},
                        {
                            "name": "sentTo",
                            "type": "array",
                            "values": [
                                {"type": "string", "value": r} for r in RECIPIENTS
                            ],
                        },
                        {"name": "copyTo", "type": "array", "values": []},
                        {"name": "bCCTo", "type": "array", "values": []},
                        {
                            "name": "subject",
                            "type": "array",
                            "values": [{
                                "type": "string",
                                "value": "Data agent accuracy: remediations waiting for approval",
                            }],
                        },
                        {
                            "name": "headline",
                            "type": "array",
                            "values": [{
                                "type": "string",
                                "value": (
                                    "An evaluation run left defects that nobody has "
                                    "approved or rejected yet."
                                ),
                            }],
                        },
                        {
                            "name": "optionalMessage",
                            "type": "array",
                            "values": [
                                {
                                    "type": "string",
                                    "value": (
                                        "Nothing has been changed automatically, and "
                                        "nothing will be until a person approves a "
                                        "specific sentence. Open the Agent Accuracy "
                                        "dashboard, read the remediation queue, then "
                                        "approve or reject each line with: python "
                                        "validation/approve.py --question <id> --by "
                                        "<you>. Questions waiting: "
                                    ),
                                },
                                event_field("questions"),
                            ],
                        },
                        {
                            "name": "additionalInformation",
                            "type": "array",
                            "values": [
                                {
                                    "kind": "NameReferencePair",
                                    "type": "complex",
                                    "arguments": [
                                        {"name": "name", "type": "string", "value": name},
                                        {
                                            "kind": "EventFieldReference",
                                            "type": "complexReference",
                                            "name": "reference",
                                            "arguments": [
                                                {
                                                    "name": "fieldName",
                                                    "type": "string",
                                                    "value": name,
                                                }
                                            ],
                                        },
                                    ],
                                }
                                for name in (
                                    "pending_count",
                                    "approvable_count",
                                    "needs_human_count",
                                    "questions",
                                )
                            ],
                        },
                    ],
                }],
            },
        ],
    }

    pending_rule = {
        "uniqueIdentifier": pending_rule_id,
        "payload": {
            "name": "Remediation queue waiting for approval",
            "description": "Created by: skills-for-fabric",
            "parentContainer": {"targetUniqueIdentifier": container_id},
            "definition": {
                "type": "Rule",
                "instance": stringify(pending_rule_template),
                "settings": {"shouldRun": True, "shouldApplyRuleOnUpdate": False},
            },
        },
        "type": "timeSeriesView-v1",
    }

    # ----------------------------------------------------------------------
    # The approval half of the loop
    # ----------------------------------------------------------------------
    #
    # A row in eval_approvals is a human saying "yes, add exactly this
    # sentence". The rule reacts to that decision, never to the proposal that
    # produced it. That separation is what stops the loop approving its own
    # work, and it is why the approval carries its own copy of the instruction
    # text rather than a pointer to a row that could change underneath it.

    approvals_source_id = str(uuid.uuid4())
    approvals_event_id = str(uuid.uuid4())
    notebook_action_id = str(uuid.uuid4())
    approval_rule_id = str(uuid.uuid4())

    approvals_source = {
        "uniqueIdentifier": approvals_source_id,
        "payload": {
            "name": "Remediation approvals",
            "runSettings": {"executionIntervalInSeconds": 60},
            "query": {"queryString": APPROVALS_QUERY},
            "eventhouseItem": {
                "itemId": KQL_DATABASE_ID,
                "workspaceId": WORKSPACE_ID,
                "itemType": "KustoDatabase",
            },
            "queryParameters": [
                {"name": "startTime", "type": "DURATION_START",
                 "value": "2026-01-01T00:00:00Z"},
                {"name": "endTime", "type": "DURATION_END",
                 "value": "2026-01-01T00:05:00Z"},
            ],
            "eventTimeSettings": {
                "timeFieldName": "approved_ts",
                "ingestionDelayInSeconds": 60,
                "timeZone": "UTC",
            },
            "metadata": {
                "workspaceId": WORKSPACE_ID,
                "measureName": "",
                "querySetId": "",
                "queryId": "",
            },
            "parentContainer": {"targetUniqueIdentifier": container_id},
        },
        "type": "kqlSource-v1",
    }

    approvals_event = {
        "uniqueIdentifier": approvals_event_id,
        "payload": {
            "name": "Approval decision",
            "parentContainer": {"targetUniqueIdentifier": container_id},
            "definition": {
                "type": "Event",
                "instance": stringify({
                    "templateId": "SourceEvent",
                    "templateVersion": TEMPLATE_VERSION,
                    "steps": [{
                        "name": "SourceEventStep",
                        "id": str(uuid.uuid4()),
                        "rows": [{
                            "name": "SourceSelector",
                            "kind": "SourceReference",
                            "arguments": [{
                                "name": "entityId", "type": "string",
                                "value": approvals_source_id,
                            }],
                        }],
                    }],
                }),
            },
        },
        "type": "timeSeriesView-v1",
    }

    notebook_action = {
        "uniqueIdentifier": notebook_action_id,
        "payload": {
            "name": "Run agent_remediate",
            "fabricItem": {
                "itemId": REMEDIATION_NOTEBOOK_ID,
                "workspaceId": WORKSPACE_ID,
                "itemType": "SynapseNotebook",
            },
            "jobType": "RunNotebook",
            "parentContainer": {"targetUniqueIdentifier": container_id},
        },
        "type": "fabricItemAction-v1",
    }

    def parameter(name: str, kind: str, value) -> dict:
        return {
            "kind": "FabricItemParameter",
            "type": "complex",
            "arguments": [
                {"name": "parameterName", "type": "string", "value": name},
                {"name": "parameterType", "type": "string", "value": kind},
                {"name": "parameterValue", "type": "complexArray",
                 "values": [{"type": "string", "value": value}]},
            ],
        }

    approval_rule_template = {
        "templateId": "EventTrigger",
        "templateVersion": TEMPLATE_VERSION,
        "steps": [
            {
                "name": "FieldsDefaultsStep",
                "id": str(uuid.uuid4()),
                "rows": [{
                    "name": "EventSelector",
                    "kind": "Event",
                    "arguments": [{
                        "kind": "EventReference",
                        "type": "complex",
                        "name": "event",
                        "arguments": [{
                            "name": "entityId", "type": "string",
                            "value": approvals_event_id,
                        }],
                    }],
                }],
            },
            {
                "name": "EventDetectStep",
                "id": str(uuid.uuid4()),
                "rows": [
                    {
                        "name": "EventFieldSelector",
                        "kind": "EventField",
                        "arguments": [{
                            "name": "fieldName", "type": "string",
                            "value": "decision",
                        }],
                    },
                    {
                        "name": "TextValueCondition",
                        "kind": "TextValueCondition",
                        "arguments": [
                            {"name": "op", "type": "string", "value": "IsEqualTo"},
                            {"name": "value", "type": "string", "value": "approved"},
                        ],
                    },
                ],
            },
            {
                "name": "ActStep",
                "id": str(uuid.uuid4()),
                "rows": [{
                    "name": "FabricItemBinding",
                    "kind": "FabricItemInvocation",
                    "arguments": [
                        {"name": "workspaceId", "type": "string", "value": WORKSPACE_ID},
                        {"name": "itemId", "type": "string",
                         "value": REMEDIATION_NOTEBOOK_ID},
                        {"name": "itemType", "type": "string",
                         "value": "SynapseNotebook"},
                        {"name": "jobType", "type": "string", "value": "RunNotebook"},
                        {"name": "fabricJobConnectionDocumentId", "type": "string",
                         "value": notebook_action_id},
                        {"name": "additionalInformation", "type": "array", "values": []},
                        {"name": "parameters", "type": "array", "values": [
                            # Empty question id means "every approved and
                            # unapplied row", so a burst of approvals is one
                            # run rather than a race between several.
                            parameter("QUESTION_ID", "String", ""),
                            parameter("APPROVED_BY", "String", "activator-auto-apply"),
                            parameter("DRY_RUN", "Boolean", "false"),
                        ]},
                    ],
                }],
            },
        ],
    }

    approval_rule = {
        "uniqueIdentifier": approval_rule_id,
        "payload": {
            "name": "Approved remediation, apply it",
            "description": "Created by: skills-for-fabric",
            "parentContainer": {"targetUniqueIdentifier": container_id},
            "definition": {
                "type": "Rule",
                "instance": stringify(approval_rule_template),
                "settings": {"shouldRun": True, "shouldApplyRuleOnUpdate": False},
            },
        },
        "type": "timeSeriesView-v1",
    }

    return [
        container,
        source, source_event, rule,
        pending_source, pending_event, pending_rule,
        approvals_source, approvals_event, notebook_action, approval_rule,
    ]


# --------------------------------------------------------------------------
# Fabric REST
# --------------------------------------------------------------------------

def token() -> str:
    result = subprocess.run(
        ["az", "account", "get-access-token", "--resource", FABRIC_API,
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, shell=True, check=True,
    )
    return result.stdout.strip()


def call(method: str, url: str, body: dict | None = None) -> tuple[int, dict, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"Bearer {token()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8")
            # A 202 can carry a literal "null" body, which json.loads turns
            # into None rather than a dict, so every caller that reads an id
            # off it would raise AttributeError instead of polling.
            payload = json.loads(raw) if raw.strip() else {}
            return response.status, (payload or {}), dict(response.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} {method} {url}\n{raw[:1500]}") from None


def wait(operation_id: str) -> None:
    for _ in range(60):
        _, payload, _ = call("GET", f"{FABRIC_API}/v1/operations/{operation_id}")
        status = payload.get("status")
        if status == "Succeeded":
            return
        if status in {"Failed", "Undetermined"}:
            raise SystemExit(f"operation {operation_id} {status}: {payload}")
        time.sleep(5)
    raise SystemExit(f"operation {operation_id} did not finish")


def find_existing() -> str | None:
    _, payload, _ = call("GET", f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/reflexes")
    for item in payload.get("value", []):
        if item.get("displayName") == ACTIVATOR_NAME:
            return item["id"]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-only", action="store_true")
    args = parser.parse_args()

    require(
        "FABRIC_WORKSPACE_ID",
        "FABRIC_KQL_DATABASE_ID",
        "FABRIC_REMEDIATION_NOTEBOOK_ID",
        "AGENT_ACCURACY_RECIPIENTS",
    )

    entities = build_entities()
    encoded = base64.b64encode(
        json.dumps(entities, indent=2).encode("utf-8")
    ).decode("utf-8")

    if args.print_only:
        print(json.dumps(entities, indent=2))
        return 0

    definition = {
        "parts": [{
            "path": "ReflexEntities.json",
            "payload": encoded,
            "payloadType": "InlineBase64",
        }]
    }

    existing = find_existing()
    if existing:
        print(f"updating existing activator {existing}")
        status, payload, headers = call(
            "POST",
            f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/reflexes/{existing}/updateDefinition",
            {"definition": definition},
        )
        reflex_id = existing
    else:
        print("creating activator")
        status, payload, headers = call(
            "POST",
            f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/reflexes",
            {
                "displayName": ACTIVATOR_NAME,
                "description": (
                    "Watches data agent evaluation runs. Alerts a human when a run "
                    "raises a high severity regression, and again when approved "
                    "remediations are left waiting. Never changes the model without "
                    "an approval row written by a person."
                ),
                "definition": definition,
            },
        )
        reflex_id = payload.get("id")

    if status == 202:
        operation_id = headers.get("x-ms-operation-id")
        print(f"long running operation {operation_id}")
        wait(operation_id)
        if not reflex_id:
            reflex_id = find_existing()

    print(f"activator ready: {reflex_id}")
    print(f"https://app.powerbi.com/groups/{WORKSPACE_ID}/reflexes/{reflex_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
