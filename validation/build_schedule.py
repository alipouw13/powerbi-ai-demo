"""Schedule the evaluation notebook.

A regression detector that only runs when somebody remembers to run it is not
a regression detector. Every finding so far came from a run triggered by hand,
which means drift detection was not actually operating.

This creates a daily schedule on the eval notebook. Daily rather than hourly
on purpose: each run asks 18 questions three times, which costs real capacity
and real agent calls, and nothing in this model changes fast enough to need
more. Raise the frequency when the model starts changing daily, not before.

The remediation notebook is deliberately left unscheduled. It runs only when
an approval arrives, and a scheduled job holding write access to a governed
semantic model every night, for no reason, is exactly the kind of standing
permission that turns into an incident.

Usage:
    python validation/build_schedule.py            # create or update
    python validation/build_schedule.py --list     # show what exists
    python validation/build_schedule.py --disable  # stop it without deleting
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

WORKSPACE_ID = "1713f459-7fcf-4704-94d6-7df5827ddcb0"
EVAL_NOTEBOOK_ID = "6d20bf31-33ca-4de4-8e47-40594276251c"
FABRIC_API = "https://api.fabric.microsoft.com"

JOB_TYPE = "RunNotebook"

# 06:00 local, so a regression is waiting when somebody starts work rather
# than arriving in the middle of the day on top of everything else.
START_TIME = "06:00:00"
TIME_ZONE = "Eastern Standard Time"
INTERVAL_MINUTES = 24 * 60


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
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        raise SystemExit(f"HTTP {exc.code} {method} {url}\n{detail}") from None


def schedules_url(item_id: str) -> str:
    return (f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/items/{item_id}"
            f"/jobs/{JOB_TYPE}/schedules")


def build_configuration() -> dict:
    today = datetime.now(timezone.utc).date()
    return {
        "startDateTime": f"{today}T{START_TIME}",
        # Fabric requires an end date. Ten years is effectively "until
        # somebody decides otherwise", and it still expires rather than
        # running forever after everyone who set it up has moved on.
        "endDateTime": f"{today + timedelta(days=3650)}T23:59:00",
        "localTimeZoneId": TIME_ZONE,
        "type": "Cron",
        "interval": INTERVAL_MINUTES,
    }


def list_schedules(item_id: str) -> list[dict]:
    _, payload = call("GET", schedules_url(item_id))
    return payload.get("value", [])


def show() -> int:
    existing = list_schedules(EVAL_NOTEBOOK_ID)
    if not existing:
        print("no schedule on the eval notebook, so nothing runs on its own")
        return 0
    for schedule in existing:
        config = schedule.get("configuration", {})
        print(f"id       : {schedule.get('id')}")
        print(f"enabled  : {schedule.get('enabled')}")
        print(f"type     : {config.get('type')}")
        print(f"every    : {config.get('interval')} minutes")
        print(f"from     : {config.get('startDateTime')} {config.get('localTimeZoneId')}")
        print(f"created  : {schedule.get('createdDateTime')}")
    return 0


def apply(enabled: bool = True) -> int:
    body = {"enabled": enabled, "configuration": build_configuration()}
    existing = list_schedules(EVAL_NOTEBOOK_ID)

    if existing:
        schedule_id = existing[0]["id"]
        print(f"updating schedule {schedule_id}")
        call("PATCH", f"{schedules_url(EVAL_NOTEBOOK_ID)}/{schedule_id}", body)
    else:
        print("creating schedule")
        _, payload = call("POST", schedules_url(EVAL_NOTEBOOK_ID), body)
        print(f"created {payload.get('id')}")

    print()
    return show()


def main() -> int:
    if "--list" in sys.argv:
        return show()
    if "--disable" in sys.argv:
        print("disabling the schedule, definition kept")
        return apply(enabled=False)
    return apply(enabled=True)


if __name__ == "__main__":
    sys.exit(main())
