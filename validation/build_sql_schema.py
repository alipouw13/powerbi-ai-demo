"""Generate the SQL database schema, and create the item in Fabric.

The loop's operational state moves here from a mix of markdown, Delta and an
eventhouse. Three things follow from that, and they are the whole reason this
file is generated rather than hand-written SQL:

* **A user data function can reach it.** Managed connections cover SQL
  databases in Fabric. They do not cover eventhouses, which is why the
  approval function needed a Key Vault connection and a service principal.
  This schema is what deletes all of that.
* **A Power BI report can read it.** A SQL database in Fabric mirrors to
  OneLake, so a shortcut plus Direct Lake gives a report that reflects a
  writeback without a refresh.
* **The eventhouse keeps its one job.** Activator cannot watch a SQL
  database, so approvals are mirrored to the eventhouse for the trigger.
  Nothing downstream of that changes.

Two properties are carried over from the Kusto design deliberately, because
they are the reason it works:

* `approvals.proposed_instruction` is a **copy**, not a foreign key to the
  defect. A person approves a sentence, and the proposal can change on the
  next run.
* "Still open" is **derived**, not stored, as the `open_approvals` view. A
  stored `applied` flag is a thing that can disagree with reality.

Run:
    python validation/build_sql_schema.py             # write schema.sql
    python validation/build_sql_schema.py --create    # create the item too
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import FABRIC_API, SQL_DATABASE_NAME, WORKSPACE_ID, require  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------
#
# Ordered so that the file can be run top to bottom against an empty database.
# Every statement is guarded, so running it twice is safe and running it after
# a partial failure resumes rather than erroring.

TABLES: list[tuple[str, str]] = [
    ("questions", """
-- Published from validation/question-bank.md. Never authored here.
--
-- The bank is the measuring instrument. If it were editable at runtime,
-- somebody could soften a question, the score would rise, and nothing would
-- record that the instrument had changed. bank_sha is what makes that
-- visible: two runs with different hashes are not comparable.
CREATE TABLE dbo.questions (
    question_id   varchar(8)     NOT NULL PRIMARY KEY,
    kind          varchar(16)    NOT NULL,   -- 'scored' | 'probe'
    ordinal       int            NOT NULL,
    prompt        nvarchar(1000) NOT NULL,
    tests         nvarchar(1000) NULL,
    good_outcome  nvarchar(1000) NULL,       -- probes only
    bank_sha      char(40)       NOT NULL,
    published_ts  datetime2(3)   NOT NULL
);
"""),
    ("runs", """
CREATE TABLE dbo.runs (
    run_id                uniqueidentifier NOT NULL PRIMARY KEY,
    run_ts                datetime2(3)     NOT NULL,
    surface               varchar(64)      NOT NULL,
    bank_sha              char(40)         NOT NULL,
    score                 int              NOT NULL,
    max_score             int              NOT NULL,
    previous_score        int              NULL,
    flake_count           int              NOT NULL,
    failure_count         int              NOT NULL,
    guardrails_lost_count int              NOT NULL,
    errored_count         int              NOT NULL,
    alert_severity        varchar(16)      NOT NULL,
    alert_detail          nvarchar(max)    NULL
);
"""),
    ("answers", """
-- One row per attempt, not per question. The repeats are the point: a
-- question answered correctly twice out of three is the finding.
CREATE TABLE dbo.answers (
    run_id         uniqueidentifier NOT NULL,
    question_id    varchar(8)       NOT NULL,
    attempt        int              NOT NULL,
    grade          varchar(16)      NOT NULL,
    classification varchar(24)      NOT NULL,
    detail         nvarchar(max)    NULL,
    latency_ms     int              NOT NULL,
    answer         nvarchar(max)    NULL,
    CONSTRAINT pk_answers PRIMARY KEY (run_id, question_id, attempt),
    CONSTRAINT fk_answers_run
        FOREIGN KEY (run_id) REFERENCES dbo.runs(run_id),
    CONSTRAINT fk_answers_question
        FOREIGN KEY (question_id) REFERENCES dbo.questions(question_id)
);
"""),
    ("defects", """
CREATE TABLE dbo.defects (
    run_id               uniqueidentifier NOT NULL,
    question_id          varchar(8)       NOT NULL,
    classification       varchar(32)      NOT NULL,
    tier                 int              NOT NULL,
    fix_target           nvarchar(200)    NOT NULL,
    instruction_target   varchar(32)      NOT NULL,  -- 'semantic_model' | 'data_agent' | ''
    proposed_instruction nvarchar(max)    NULL,
    rationale            nvarchar(max)    NOT NULL,
    auto_appliable       bit              NOT NULL,
    CONSTRAINT pk_defects PRIMARY KEY (run_id, question_id),
    CONSTRAINT fk_defects_run
        FOREIGN KEY (run_id) REFERENCES dbo.runs(run_id),
    CONSTRAINT fk_defects_question
        FOREIGN KEY (question_id) REFERENCES dbo.questions(question_id)
);
"""),
    ("feedback", """
-- A person saying an answer was wrong. This is NOT an approval and can never
-- become one on its own.
--
-- Feedback is evidence that a defect may exist. If a click could turn an
-- opinion into a model change, the loop would agree with whoever complained
-- most recently, and the score would stop measuring the model.
--
-- created_by is the logged-in report user, read from their token by the
-- function. It is not a parameter, so it cannot be someone else's name.
CREATE TABLE dbo.feedback (
    feedback_id  uniqueidentifier NOT NULL PRIMARY KEY,
    created_ts   datetime2(3)     NOT NULL,
    created_by   nvarchar(256)    NOT NULL,
    created_oid  varchar(64)      NOT NULL,
    run_id       uniqueidentifier NULL,
    question_id  varchar(8)       NOT NULL,
    verdict      varchar(16)      NOT NULL,  -- 'wrong' | 'misleading' | 'right'
    comment      nvarchar(max)    NOT NULL,
    status       varchar(24)      NOT NULL,  -- 'new' | 'triaged' | 'dismissed'
    CONSTRAINT fk_feedback_question
        FOREIGN KEY (question_id) REFERENCES dbo.questions(question_id)
);
"""),
    ("approvals", """
-- One human decision about one sentence.
--
-- proposed_instruction is a copy of the text that was approved, not a
-- reference to the defect that proposed it. The proposal can change on the
-- next run; what was agreed cannot.
CREATE TABLE dbo.approvals (
    approval_id          uniqueidentifier NOT NULL PRIMARY KEY,
    approved_ts          datetime2(3)     NOT NULL,
    question_id          varchar(8)       NOT NULL,
    instruction_target   varchar(32)      NOT NULL,
    proposed_instruction nvarchar(max)    NOT NULL,
    decision             varchar(16)      NOT NULL,
    approved_by          nvarchar(256)    NOT NULL,
    approver_oid         varchar(64)      NOT NULL,
    source               varchar(16)      NOT NULL,  -- 'report' | 'card' | 'cli'
    note                 nvarchar(max)    NULL,
    -- Stamped by the mirror pipeline. An approval with a null mirrored_ts and
    -- an old approved_ts never reached the eventhouse, so the rule never
    -- fired. That is a query, rather than a mystery.
    mirrored_ts          datetime2(3)     NULL,
    CONSTRAINT fk_approvals_question
        FOREIGN KEY (question_id) REFERENCES dbo.questions(question_id)
);
"""),
    ("remediations", """
-- Mirrored back from the eventhouse by the pipeline, because the remediation
-- notebook still writes there. Kept here so open_approvals can be a view and
-- the report can show status without crossing stores.
CREATE TABLE dbo.remediations (
    remediation_id     uniqueidentifier NOT NULL PRIMARY KEY,
    recorded_ts        datetime2(3)     NOT NULL,
    applied_ts         datetime2(3)     NULL,
    approval_id        uniqueidentifier NOT NULL,
    question_id        varchar(8)       NOT NULL,
    instruction_target varchar(32)      NOT NULL,
    instruction        nvarchar(max)    NOT NULL,
    approved_by        nvarchar(256)    NOT NULL,
    applied_by         nvarchar(256)    NOT NULL,
    dry_run            bit              NOT NULL,
    persisted          bit              NOT NULL,
    verified           bit              NOT NULL,
    verified_ts        datetime2(3)     NULL,
    verified_run_id    uniqueidentifier NULL
);
"""),
]

# The one definition of outstanding work, matching the Kusto expression in
# approve.py, the remediation notebook and the Activator rule. An approval is
# open when it is approved and no persisted remediation references it.
VIEWS: list[tuple[str, str]] = [
    ("open_approvals", """
CREATE VIEW dbo.open_approvals AS
SELECT a.*
FROM dbo.approvals AS a
WHERE a.decision = 'approved'
  AND NOT EXISTS (
      SELECT 1 FROM dbo.remediations AS r
      WHERE r.approval_id = a.approval_id AND r.persisted = 1
  );
"""),
    ("remediation_queue", """
-- What a person reads before deciding. One row per question, its latest
-- defect, and where that question has got to.
CREATE VIEW dbo.remediation_queue AS
WITH latest AS (
    SELECT d.*, ROW_NUMBER() OVER (
        PARTITION BY d.question_id ORDER BY r.run_ts DESC) AS rn
    FROM dbo.defects AS d
    JOIN dbo.runs AS r ON r.run_id = d.run_id
), decided AS (
    SELECT a.*, ROW_NUMBER() OVER (
        PARTITION BY a.question_id ORDER BY a.approved_ts DESC) AS rn
    FROM dbo.approvals AS a
)
SELECT
    l.question_id                                   AS [Question],
    q.prompt                                        AS [Asked],
    l.classification                                AS [Problem],
    l.instruction_target                            AS [Target],
    l.proposed_instruction                          AS [Add this instruction],
    l.rationale                                     AS [Why],
    l.tier                                          AS [Tier],
    l.auto_appliable                                AS [Approvable],
    CASE
        WHEN d.decision IS NULL           THEN 'awaiting approval'
        WHEN d.decision = 'rejected'      THEN 'rejected'
        WHEN rm.approval_id IS NULL       THEN 'approved, not yet applied'
        WHEN rm.verified = 1              THEN 'applied and verified'
        ELSE 'applied, not yet verified'
    END                                             AS [Status],
    d.approved_by                                   AS [Approved by]
FROM latest AS l
JOIN dbo.questions AS q ON q.question_id = l.question_id
LEFT JOIN decided AS d ON d.question_id = l.question_id AND d.rn = 1
LEFT JOIN dbo.remediations AS rm
       ON rm.approval_id = d.approval_id AND rm.persisted = 1
WHERE l.rn = 1;
"""),
]

INDEXES = """
CREATE INDEX ix_answers_question   ON dbo.answers(question_id);
CREATE INDEX ix_defects_question   ON dbo.defects(question_id);
CREATE INDEX ix_approvals_question ON dbo.approvals(question_id);
CREATE INDEX ix_approvals_mirror   ON dbo.approvals(mirrored_ts);
CREATE INDEX ix_feedback_question  ON dbo.feedback(question_id);
"""


def guard_table(name: str, body: str) -> str:
    return (
        f"IF OBJECT_ID('dbo.{name}', 'U') IS NULL\nBEGIN\n"
        + "\n".join("    " + line if line.strip() else line
                    for line in body.strip().splitlines())
        + f"\nEND;\nGO\n"
    )


def guard_view(name: str, body: str) -> str:
    # A view is replaced rather than skipped, because unlike a table it holds
    # no data and an out of date definition is a silent wrong answer.
    stripped = body.strip()
    comments = []
    while stripped.startswith("--"):
        head, _, stripped = stripped.partition("\n")
        comments.append(head)
        stripped = stripped.lstrip()
    prefix = ("\n".join(comments) + "\n") if comments else ""
    return (
        f"{prefix}IF OBJECT_ID('dbo.{name}', 'V') IS NOT NULL\n"
        f"    DROP VIEW dbo.{name};\nGO\n{stripped}\nGO\n"
    )


def build_schema() -> str:
    parts = [
        "-- GENERATED by validation/build_sql_schema.py. Do not edit.",
        "--",
        "-- Every statement is guarded, so this is safe to run repeatedly and",
        "-- safe to resume after a partial failure.",
        "",
    ]
    for name, body in TABLES:
        parts.append(guard_table(name, body))
    for name, body in VIEWS:
        parts.append(guard_view(name, body))

    for statement in INDEXES.strip().splitlines():
        index_name = statement.split()[2]
        table = statement.split(" ON ")[1].split("(")[0].strip()
        parts.append(
            f"IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = "
            f"'{index_name}' AND object_id = OBJECT_ID('{table}'))\n"
            f"    {statement.strip()}\nGO\n"
        )
    return "\n".join(parts)


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
        headers={"Authorization": f"Bearer {token()}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8")
            # A 202 can carry a literal "null" body, which json.loads turns
            # into None rather than a dict, so every caller that reads an id
            # off it would raise AttributeError instead of polling.
            parsed = json.loads(raw) if raw.strip() else {}
            return response.status, (parsed or {}), dict(response.headers)
    except urllib.error.HTTPError as exc:
        raise SystemExit(
            f"HTTP {exc.code} {method} {url}\n"
            + exc.read().decode("utf-8", errors="replace")[:1500]
        ) from None


def find_existing() -> str | None:
    _, payload, _ = call(
        "GET", f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/items?type=SQLDatabase"
    )
    for item in payload.get("value", []):
        if item.get("displayName") == SQL_DATABASE_NAME:
            return item["id"]
    return None


def create() -> int:
    existing = find_existing()
    if existing:
        print(f"database already exists: {existing}")
    else:
        print("creating database")
        status, payload, headers = call(
            "POST", f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/items",
            {"displayName": SQL_DATABASE_NAME, "type": "SQLDatabase",
             "description": "Operational state for the data agent accuracy loop."},
        )
        if status == 202:
            operation_id = headers.get("x-ms-operation-id")
            for _ in range(60):
                _, op, _ = call("GET", f"{FABRIC_API}/v1/operations/{operation_id}")
                if op.get("status") == "Succeeded":
                    break
                if op.get("status") in {"Failed", "Undetermined"}:
                    raise SystemExit(f"create failed: {op}")
                time.sleep(5)
        existing = payload.get("id") or find_existing()
        print(f"created {existing}")

    print()
    print("The schema is not applied from here. A SQL database in Fabric takes")
    print("DDL over its SQL endpoint, not over the item API, so run:")
    print()
    print(f"  validation/schema.sql")
    print()
    print("against the database, from the portal query editor or sqlcmd. It is")
    print("guarded throughout, so running it more than once is safe.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create", action="store_true",
                        help="create the SQL database item in Fabric")
    args = parser.parse_args()

    SCHEMA_PATH.write_text(build_schema(), encoding="utf-8")
    print(f"wrote {SCHEMA_PATH.relative_to(ROOT)}")

    if not args.create:
        return 0

    require("FABRIC_WORKSPACE_ID")
    return create()


if __name__ == "__main__":
    sys.exit(main())
