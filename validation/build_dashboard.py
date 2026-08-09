"""Generate and deploy the Agent Accuracy real-time dashboard.

A KQL dashboard over the EH_AgentEval eventhouse. It exists so that the alert
and the thing you are supposed to do about it are on the same screen. An alert
that says "score dropped" and makes you go and find the reason is an alert
people learn to close.

The remediation tile is the point: it shows the literal instruction text a
human is being asked to approve, next to the question that failed and the
evidence for it.

Run:
    python validation/build_dashboard.py
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

WORKSPACE_ID = os.environ.get("FABRIC_WORKSPACE_ID", "").strip()
KQL_DATABASE_ID = os.environ.get("FABRIC_KQL_DATABASE_ID", "").strip()
KQL_DATABASE_NAME = "EH_AgentEval"
CLUSTER_URI = os.environ.get("FABRIC_KUSTO_URI", "").strip()
DASHBOARD_NAME = "Agent Accuracy"
FABRIC_API = "https://api.fabric.microsoft.com"

DATA_SOURCE_ID = "ds-agent-eval"
PAGE_ID = "page-overview"


def require_configuration() -> None:
    missing = [
        name
        for name, value in (
            ("FABRIC_WORKSPACE_ID", WORKSPACE_ID),
            ("FABRIC_KQL_DATABASE_ID", KQL_DATABASE_ID),
            ("FABRIC_KUSTO_URI", CLUSTER_URI),
        )
        if not value
    ]
    if missing:
        raise SystemExit(
            "missing required environment variable(s): " + ", ".join(missing)
        )


def tile(title: str, query: str, x: int, y: int, w: int, h: int, viz: dict) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "title": title,
        "query": {
            "dataSource": {"kind": "inline", "dataSourceId": DATA_SOURCE_ID},
            "text": query,
            "kind": "kql",
        },
        "layout": {"x": x, "y": y, "width": w, "height": h},
        "pageId": PAGE_ID,
        "visualType": viz["visualType"],
        "visualOptions": viz.get("visualOptions", {}),
    }


SCORE_TREND = """eval_runs
| order by run_ts asc
| project run_ts, score, max_score"""

LATEST_STATE = """eval_runs
| top 1 by run_ts desc
| project ['Score']=strcat(tostring(score), " / ", tostring(max_score)),
          ['Previous']=previous_score,
          ['Flakes']=flake_count,
          ['Stable failures']=failure_count,
          ['Guardrails lost']=guardrails_lost_count,
          ['Agent errors']=strcat(tostring(error_attempts), " / ", tostring(attempt_count)),
          ['Severity']=alert_severity"""

OPEN_ALERTS = """eval_runs
| where alert_count > 0
| order by run_ts desc
| take 20
| project run_ts, alert_severity, score, flake_count, failure_count, alert_detail"""

# The tile this dashboard is really for. Anyone approving a change can read
# the exact sentence that will be added, next to the question that failed.
REMEDIATION_QUEUE = """eval_defects
| where isnotempty(proposed_instruction)
| summarize arg_max(run_ts, *) by question_id
| join kind=leftouter (
    eval_approvals
    | summarize arg_max(approved_ts, decision, approved_by, applied) by question_id
  ) on question_id
| extend ['Status'] = case(
      isempty(decision), "awaiting approval",
      decision == "approved" and applied, "applied",
      decision == "approved", "approved, not yet applied",
      "rejected")
| project ['Question']=question_id,
          ['Problem']=classification,
          ['Tier']=tier,
          ['Add this to the model AI instructions']=proposed_instruction,
          ['Where']=instruction_target,
          ['Why']=rationale,
          ['Status'],
          ['Approved by']=approved_by
| order by ['Question'] asc"""

NEEDS_A_HUMAN = """eval_defects
| summarize arg_max(run_ts, *) by question_id
| where tier != 1 or isempty(proposed_instruction)
| project ['Question']=question_id, ['Tier']=tier, ['Problem']=classification,
          ['Fix target']=fix_target, ['Why']=rationale, ['Who acts']=action
| order by ['Tier'] asc, ['Question'] asc"""

APPLIED = """eval_remediations
| order by applied_ts desc
| take 20
| project applied_ts, question_id, instruction_target, approved_by, applied_by,
          dry_run, verified, instruction"""

FLAKE_HISTORY = """eval_runs
| order by run_ts asc
| project run_ts, flake_count, failure_count, guardrails_lost_count"""


def build_definition() -> dict:
    tiles = [
        tile("Score over time", SCORE_TREND, 0, 0, 9, 5,
             {"visualType": "line",
              "visualOptions": {"xColumn": {"type": "datetime", "name": "run_ts"},
                                "yColumns": ["score", "max_score"],
                                "yAxisMaximumValue": 15, "yAxisMinimumValue": 0}}),
        tile("Latest run", LATEST_STATE, 9, 0, 9, 5,
             {"visualType": "table"}),
        tile("Instability over time", FLAKE_HISTORY, 0, 5, 9, 5,
             {"visualType": "line",
              "visualOptions": {"xColumn": {"type": "datetime", "name": "run_ts"},
                                "yColumns": ["flake_count", "failure_count",
                                             "guardrails_lost_count"]}}),
        tile("Alerts raised", OPEN_ALERTS, 9, 5, 9, 5,
             {"visualType": "table"}),
        tile("Remediation queue, approve or reject each line",
             REMEDIATION_QUEUE, 0, 10, 18, 7, {"visualType": "table"}),
        tile("Needs a human, no safe automatic fix",
             NEEDS_A_HUMAN, 0, 17, 9, 5, {"visualType": "table"}),
        tile("Applied remediations", APPLIED, 9, 17, 9, 5,
             {"visualType": "table"}),
    ]

    return {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/kqlDashboard/definition/1.0.0/schema.json",
        "schema_version": "62",
        "title": DASHBOARD_NAME,
        "autoRefresh": {"enabled": True, "defaultDuration": "5m", "minimumDuration": "1m"},
        "dataSources": [{
            "id": DATA_SOURCE_ID,
            "name": KQL_DATABASE_NAME,
            "clusterUri": CLUSTER_URI,
            "database": KQL_DATABASE_NAME,
            "kind": "manual-kusto",
            "scopeId": "kusto",
        }],
        "pages": [{"id": PAGE_ID, "name": "Overview"}],
        "tiles": tiles,
        "baseQueries": [],
        "parameters": [],
    }


def token() -> str:
    result = subprocess.run(
        ["az", "account", "get-access-token", "--resource", FABRIC_API,
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, shell=True, check=True,
    )
    return result.stdout.strip()


def call(method: str, url: str, body: dict | None = None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {token()}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw.strip() else {}), dict(response.headers)
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
    raise SystemExit("operation did not finish")


def find_existing() -> str | None:
    _, payload, _ = call("GET", f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/items?type=KQLDashboard")
    for item in payload.get("value", []):
        if item.get("displayName") == DASHBOARD_NAME:
            return item["id"]
    return None


def main() -> int:
    require_configuration()
    if "--print-only" in sys.argv:
        print(json.dumps(build_definition(), indent=2))
        return 0

    encoded = base64.b64encode(
        json.dumps(build_definition(), indent=2).encode("utf-8")
    ).decode("utf-8")
    definition = {"parts": [{
        "path": "RealTimeDashboard.json",
        "payload": encoded,
        "payloadType": "InlineBase64",
    }]}

    existing = find_existing()
    if existing:
        print(f"updating dashboard {existing}")
        status, _, headers = call(
            "POST",
            f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/items/{existing}/updateDefinition",
            {"definition": definition},
        )
        dashboard_id = existing
    else:
        print("creating dashboard")
        status, payload, headers = call(
            "POST", f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/items",
            {
                "displayName": DASHBOARD_NAME,
                "description": (
                    "Data agent accuracy: score, instability, alerts, and the "
                    "remediation queue with the exact instruction text awaiting approval."
                ),
                "type": "KQLDashboard",
                "definition": definition,
            },
        )
        dashboard_id = payload.get("id")

    if status == 202:
        wait(headers.get("x-ms-operation-id"))
        dashboard_id = dashboard_id or find_existing()

    print(f"dashboard ready: {dashboard_id}")
    print(f"https://app.powerbi.com/groups/{WORKSPACE_ID}/kustodashboards/{dashboard_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
