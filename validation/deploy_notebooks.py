"""Deploy the loop's notebooks to a Fabric workspace.

Every other artifact in this repo has a deployment script. Notebooks did not,
so the committed copy and the running copy were kept in step by hand, and the
docs said "import the notebook". That works exactly until somebody regenerates
a notebook and forgets, at which point the workspace runs code that no longer
exists in source control and no test can see the difference. That happened to
`agent_eval`.

Two things make this more than an upload.

**Parameters.** The committed notebooks carry empty tenant values on purpose,
and `test_notebook_drift.py` enforces it, so the real workspace, agent and
eventhouse ids are injected here rather than committed. Only the names in
`VALUES` are filled: `QUESTION_ID`, `APPROVED_BY`, `APPROVAL_IDS` and
`DRY_RUN` are how a person drives a run and must keep their committed
defaults, or a deployment would hardcode somebody's approval into the notebook.

**The default lakehouse.** A notebook's lakehouse binding lives inside the
notebook content's metadata, and the committed copies deliberately have none,
because it would bake a workspace and lakehouse id into source control.
`agent_eval` and `agent_remediate` both write Delta tables with `saveAsTable`,
which needs somewhere to save them, so the binding is attached here.

Usage:

    python validation/deploy_notebooks.py            # say what would change
    python validation/deploy_notebooks.py --deploy   # do it
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (  # noqa: E402
    DATA_AGENT_ID,
    DATA_AGENT_NAME,
    FABRIC_API,
    KUSTO_DATABASE_NAME,
    KUSTO_URI,
    LAKEHOUSE_ID,
    LAKEHOUSE_NAME,
    SEMANTIC_MODEL_NAME,
    SQL_CONNECTION_STRING,
    SQL_DATABASE_NAME,
    WORKSPACE_ID,
    require,
)

REPO = Path(__file__).resolve().parent.parent

NOTEBOOKS = {
    "agent_eval": "fabric/agent_eval.ipynb",
    "agent_remediate": "fabric/agent_remediate.ipynb",
    "agent_remediate_agent": "fabric/agent_remediate_agent.ipynb",
    "mirror_approvals": "fabric/mirror_approvals.ipynb",
}

# Which notebooks need a default lakehouse, and it is not a matter of taste.
# `agent_eval` writes eval_runs, eval_results and eval_defects and
# `agent_remediate` writes eval_remediations, all with saveAsTable. The other
# two never touch Spark storage: the agent path talks to the Fabric REST API
# and the eventhouse over HTTP, and the mirror is a Python notebook using
# notebookutils.data.
NEEDS_LAKEHOUSE = {"agent_eval", "agent_remediate"}


def values() -> dict[str, str]:
    """The parameters to inject, by name.

    A whitelist rather than "every empty string in the cell". The run
    parameters are empty in source control too, and filling those would ship a
    notebook that always remediates one question as one person.
    """
    return {
        "WORKSPACE_ID": WORKSPACE_ID,
        "DATA_AGENT_ID": DATA_AGENT_ID,
        "DATA_AGENT_NAME": DATA_AGENT_NAME,
        "KUSTO_URI": KUSTO_URI,
        "KUSTO_DB": KUSTO_DATABASE_NAME,
        "SQL_DATABASE": SQL_DATABASE_NAME,
        "SQL_CONNECTION_STRING": SQL_CONNECTION_STRING,
        "SEMANTIC_MODEL_NAME": SEMANTIC_MODEL_NAME,
        "LAKEHOUSE_NAME": LAKEHOUSE_NAME,
    }


def token() -> str:
    result = subprocess.run(
        ["az", "account", "get-access-token", "--resource", FABRIC_API,
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, shell=True, check=True,
    )
    return result.stdout.strip()


BEARER = ""


def call(method: str, url: str, body: dict | None = None) -> tuple[int, dict, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {BEARER}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw.strip() else {}), dict(
                response.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw) if raw.strip().startswith("{") else {"raw": raw}
        return exc.code, parsed, dict(exc.headers)


def wait(headers: dict) -> dict:
    location = headers.get("Location", "")
    if not location:
        return {}
    for _ in range(80):
        time.sleep(3)
        _, body, head = call("GET", location)
        state = body.get("status")
        if state == "Failed":
            raise DeployFailed(json.dumps(body)[:800])
        if state == "Succeeded":
            result = head.get("Location")
            if result:
                _, body, _ = call("GET", result)
            return body
    raise DeployFailed("the operation did not finish")


class DeployFailed(Exception):
    """The platform rejected the update."""


class CouldNotRead(Exception):
    """The deployed notebook could not be read.

    Its own exception because the caller must not treat it as "that notebook
    has no lakehouse binding". Those two look identical and mean opposite
    things: one is a notebook that never had one, the other is about to have a
    working one taken away.

    This is not hypothetical. `getDefinition` returns 403
    `ItemHasProtectedLabel` for every notebook in a workspace with a
    sensitivity label, so on a labelled tenant the read fails *every time* and
    a script that shrugged would unbind the lakehouse on every deploy.
    """


def deployed_notebook(item_id: str) -> dict:
    status, body, headers = call(
        "POST", f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/items/{item_id}/getDefinition")
    if status == 202:
        try:
            body = wait(headers)
        except DeployFailed as exc:
            raise CouldNotRead(str(exc)) from None
    elif status not in (200, 201):
        code = body.get("errorCode") or body.get("raw", "")
        raise CouldNotRead(f"getDefinition returned {status} {code}".strip())

    for part in (body or {}).get("definition", {}).get("parts", []):
        if part["path"].endswith(".ipynb"):
            return json.loads(base64.b64decode(part["payload"]).decode("utf-8"))
    raise CouldNotRead("getDefinition returned no notebook content")


def inject(source: list[str], fill: dict[str, str]) -> list[str]:
    """Fill in the tenant values the committed copy leaves empty."""
    out = []
    for line in source:
        match = re.match(r'^(\w+) = ""', line)
        if match and fill.get(match.group(1)):
            name = match.group(1)
            rest = line.split('""', 1)[1]
            out.append(f'{name} = "{fill[name]}"{rest}')
        else:
            out.append(line)
    return out


def find_existing() -> dict[str, str]:
    """Every notebook in the workspace, by display name.

    Raises rather than returning empty when the listing fails. "The API did
    not answer" and "there are no notebooks" are the same value and opposite
    facts, and a caller that confuses them creates a second copy of every
    notebook alongside the originals.
    """
    status, body, _ = call("GET", f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/notebooks")
    if status != 200:
        # The typed route 404s intermittently. The generic item route serves
        # the same objects and does not.
        print(f"  /notebooks returned {status}, falling back to /items")
        status, body, _ = call("GET", f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/items")
        if status != 200:
            raise CouldNotRead(f"could not list the workspace: {status}")
        body = {"value": [i for i in body.get("value", []) if i.get("type") == "Notebook"]}
    return {i["displayName"]: i["id"] for i in body.get("value", [])}


def prepare(name: str, existing: dict[str, str]) -> dict:
    """The notebook as it should be deployed: parameters in, lakehouse bound."""
    notebook = json.loads((REPO / NOTEBOOKS[name]).read_text(encoding="utf-8"))
    fill = values()

    for cell in notebook["cells"]:
        if cell.get("cell_type") == "code":
            cell["source"] = inject(cell["source"], fill)

    if name in NEEDS_LAKEHOUSE:
        try:
            carried = (deployed_notebook(existing[name])
                       .get("metadata", {}).get("dependencies"))
        except CouldNotRead as exc:
            # Fall back to config rather than failing: the binding is knowable
            # without reading the item, and refusing to deploy on a labelled
            # tenant would mean this script never runs there at all.
            print(f"  {name}: could not read the deployed copy ({exc})")
            carried = None

        if carried and (carried.get("lakehouse") or {}).get("default_lakehouse"):
            notebook["metadata"]["dependencies"] = carried
            bound = carried["lakehouse"].get("default_lakehouse_name")
            print(f"  {name}: kept the existing lakehouse binding ({bound})")
        else:
            require("FABRIC_LAKEHOUSE_ID")
            notebook["metadata"]["dependencies"] = {"lakehouse": {
                "default_lakehouse": LAKEHOUSE_ID,
                "default_lakehouse_name": LAKEHOUSE_NAME,
                "default_lakehouse_workspace_id": WORKSPACE_ID,
            }}
            print(f"  {name}: bound {LAKEHOUSE_NAME} (it writes Delta tables)")

    return notebook


def deploy(name: str, item_id: str, notebook: dict) -> None:
    payload = base64.b64encode(
        json.dumps(notebook, indent=1, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    status, body, headers = call(
        "POST",
        f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/items/{item_id}/updateDefinition",
        {"definition": {"format": "ipynb", "parts": [
            {"path": "notebook-content.ipynb", "payload": payload,
             "payloadType": "InlineBase64"}]}},
    )
    if status == 202:
        wait(headers)
    elif status not in (200, 201):
        raise DeployFailed(f"{name}: HTTP {status} {json.dumps(body)[:400]}")
    print(f"  {name}: deployed")


def main() -> int:
    global BEARER

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deploy", action="store_true",
                        help="actually update the notebooks in the workspace")
    parser.add_argument("--only", action="append", choices=sorted(NOTEBOOKS),
                        help="deploy one notebook rather than all of them")
    args = parser.parse_args()

    require("FABRIC_WORKSPACE_ID")
    BEARER = token()

    wanted = args.only or sorted(NOTEBOOKS)

    print("reading the workspace")
    existing = find_existing()

    # This script updates notebooks, it does not create them. Creating on a
    # failed lookup is how a workspace ends up with two of everything and a
    # schedule pointed at the wrong one.
    missing = [name for name in wanted if name not in existing]
    if missing:
        raise SystemExit(
            f"not deploying: {', '.join(missing)} not found in the workspace.\n\n"
            "This script updates notebooks that already exist and will not "
            "create them, because a listing that failed and a workspace that "
            "is empty look identical from here. Import them once by hand, "
            "then this keeps them current.\n"
            f"Found: {', '.join(sorted(existing)) or '(nothing)'}"
        )

    for name in wanted:
        print(f"{name}:")
        notebook = prepare(name, existing)
        if args.deploy:
            deploy(name, existing[name], notebook)
        else:
            print(f"  {name}: would deploy to {existing[name]}")

    if not args.deploy:
        print("\nnothing was changed. Re-run with --deploy to apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
