"""Create or update the Agent Accuracy Alerts activator.

Builds ReflexEntities.json for an EventTrigger rule over a KQL source, then
creates the Activator item through the Fabric REST API.

The rule is deliberately thin. It fires when a run publishes
alert_severity = "high" and does nothing clever with the data. All of the
judgement about what counts as a regression, a flake, or a lost guardrail
lives in validation/eval_harness.py, where it is covered by unit tests. A
threshold buried in a portal rule is a threshold nobody can test.

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

WORKSPACE_ID = "1713f459-7fcf-4704-94d6-7df5827ddcb0"
KQL_DATABASE_ID = "044af2c9-068d-4728-bf78-f83b6aa1c238"
REMEDIATION_NOTEBOOK_ID = "d3863cec-220f-4de1-beb4-0331bdd6c974"
ACTIVATOR_NAME = "Agent Accuracy Alerts"
RECIPIENTS = ["admin@MngEnvMCAP257273.onmicrosoft.com"]

TEMPLATE_VERSION = "1.2.4"
FABRIC_API = "https://api.fabric.microsoft.com"

# Return every run and let the rule decide. The skill guidance is explicit
# that the KQL query is the data source, not the rule engine.
KQL_QUERY = """declare query_parameters(startTime:datetime, endTime:datetime);
eval_runs
| where run_ts between (startTime .. endTime)
| project run_ts, run_id, surface, score, max_score, previous_score,
          flake_count, failure_count, guardrails_lost_count,
          errored_count, alert_count, alert_severity, alert_detail
| order by run_ts asc"""

# The human gate. A row lands here only when a person has read the proposed
# instruction and decided. The rule reacts to the decision, never to the
# proposal, which is what keeps a machine from approving its own work.
APPROVALS_QUERY = """declare query_parameters(startTime:datetime, endTime:datetime);
eval_approvals
| where approved_ts between (startTime .. endTime)
| where applied == false
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
                    "name": "TeamsBinding",
                    "kind": "TeamsMessage",
                    "arguments": [
                        {"name": "messageLocale", "type": "string", "value": "en-us"},
                        {
                            "name": "recipients",
                            "type": "array",
                            "values": [
                                {"type": "string", "value": r} for r in RECIPIENTS
                            ],
                        },
                        {
                            "name": "headline",
                            "type": "array",
                            "values": [
                                {
                                    "name": "string",
                                    "type": "string",
                                    "value": "Data agent accuracy regression, confirm before any fix",
                                }
                            ],
                        },
                        {
                            "name": "optionalMessage",
                            "type": "array",
                            "values": [
                                {
                                    "name": "string",
                                    "type": "string",
                                    "value": (
                                        "An evaluation run raised a high severity alert. "
                                        "Open eval_defects in LH_ContosoCoffee for the "
                                        "proposed fix, confirm the defect is real, then "
                                        "let a human apply it. Nothing has been changed "
                                        "automatically. Detail: "
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
            payload = json.loads(raw) if raw.strip() else {}
            return response.status, payload, dict(response.headers)
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
                    "Watches data agent evaluation runs and alerts a human when a "
                    "run raises a high severity regression. Never changes the model."
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
