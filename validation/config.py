"""Deployment configuration, read from the environment.

Nothing in this repo carries a workspace id, a Kusto hostname, a notebook id
or a recipient address. Those are tenant facts, they differ per deployment,
and a repo that hardcodes them is a repo that leaks its own topology into
every fork and pull request.

Every value is read from an environment variable and every consumer fails
fast with the names it needs, so a missing value produces one clear error
before anything is created rather than a confusing failure halfway through.

Required, per script, with the names the deployment scripts expect:

| Variable | Needed by |
| --- | --- |
| `FABRIC_WORKSPACE_ID` | every deployment script |
| `FABRIC_KUSTO_URI` | dashboard, approve, file_issues, notebooks |
| `FABRIC_KQL_DATABASE_ID` | activator, dashboard |
| `FABRIC_EVAL_NOTEBOOK_ID` | schedule |
| `FABRIC_REMEDIATION_NOTEBOOK_ID` | activator |
| `FABRIC_DATA_AGENT_ID` | eval notebook parameters |
| `FABRIC_LAKEHOUSE_ID` | notebook lakehouse binding |
| `AGENT_ACCURACY_RECIPIENTS` | activator, comma separated |
| `GITHUB_REPOSITORY` | file_issues, as owner/repo |
| `FABRIC_SQL_CONNECTION_STRING` | apply_schema, from the item's connectionString |

Optional, with defaults, because these are demo object names rather than
tenant identifiers:

| Variable | Default |
| --- | --- |
| `FABRIC_KUSTO_DATABASE_NAME` | `EH_AgentEval` |
| `FABRIC_SQL_DATABASE_NAME` | `SQLDB_AgentEval` |
| `FABRIC_LAKEHOUSE_NAME` | `LH_ContosoCoffee` |
| `FABRIC_SEMANTIC_MODEL_NAME` | `ContosoCoffee` |

Set them once per shell:

    $env:FABRIC_WORKSPACE_ID = "..."
    $env:FABRIC_KUSTO_URI = "https://<cluster>.kusto.fabric.microsoft.com"
"""

from __future__ import annotations

import os

# Not tenant specific: the public API host, and demo object names that a fork
# is expected to keep.
FABRIC_API = "https://api.fabric.microsoft.com"

WORKSPACE_ID = os.environ.get("FABRIC_WORKSPACE_ID", "").strip()
KUSTO_URI = os.environ.get("FABRIC_KUSTO_URI", "").strip()
KQL_DATABASE_ID = os.environ.get("FABRIC_KQL_DATABASE_ID", "").strip()
EVAL_NOTEBOOK_ID = os.environ.get("FABRIC_EVAL_NOTEBOOK_ID", "").strip()
REMEDIATION_NOTEBOOK_ID = os.environ.get("FABRIC_REMEDIATION_NOTEBOOK_ID", "").strip()
DATA_AGENT_ID = os.environ.get("FABRIC_DATA_AGENT_ID", "").strip()
LAKEHOUSE_ID = os.environ.get("FABRIC_LAKEHOUSE_ID", "").strip()

KUSTO_DATABASE_NAME = os.environ.get(
    "FABRIC_KUSTO_DATABASE_NAME", "EH_AgentEval"
).strip()
LAKEHOUSE_NAME = os.environ.get("FABRIC_LAKEHOUSE_NAME", "LH_ContosoCoffee").strip()
SQL_DATABASE_NAME = os.environ.get(
    "FABRIC_SQL_DATABASE_NAME", "SQLDB_AgentEval"
).strip()
SEMANTIC_MODEL_NAME = os.environ.get(
    "FABRIC_SEMANTIC_MODEL_NAME", "ContosoCoffee"
).strip()

RECIPIENTS = [
    recipient.strip()
    for recipient in os.environ.get("AGENT_ACCURACY_RECIPIENTS", "").split(",")
    if recipient.strip()
]

GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "").strip()

# The SQL database's TDS endpoint. A Fabric SQL database takes DDL over TDS
# rather than over the item API, so applying the schema needs this even though
# creating the database does not. Read it from the item's connectionString
# property, or from Settings > Connection strings in the portal.
SQL_CONNECTION_STRING = os.environ.get("FABRIC_SQL_CONNECTION_STRING", "").strip()

_VALUES = {
    "FABRIC_WORKSPACE_ID": WORKSPACE_ID,
    "FABRIC_KUSTO_URI": KUSTO_URI,
    "FABRIC_KQL_DATABASE_ID": KQL_DATABASE_ID,
    "FABRIC_EVAL_NOTEBOOK_ID": EVAL_NOTEBOOK_ID,
    "FABRIC_REMEDIATION_NOTEBOOK_ID": REMEDIATION_NOTEBOOK_ID,
    "FABRIC_DATA_AGENT_ID": DATA_AGENT_ID,
    "FABRIC_LAKEHOUSE_ID": LAKEHOUSE_ID,
    "AGENT_ACCURACY_RECIPIENTS": ",".join(RECIPIENTS),
    "GITHUB_REPOSITORY": GITHUB_REPOSITORY,
    "FABRIC_SQL_CONNECTION_STRING": SQL_CONNECTION_STRING,
}


def require(*names: str) -> None:
    """Fail before doing anything, naming every variable that is missing.

    All of them at once rather than one per run, because discovering three
    missing values across three failed deployments is three times the
    annoyance for no extra information.
    """
    missing = [name for name in names if not _VALUES.get(name, "")]
    if missing:
        raise SystemExit(
            "missing required environment variable(s): "
            + ", ".join(missing)
            + "\n\nThese are tenant specific and are deliberately not committed. "
            "See the table in validation/config.py for what each one is."
        )
