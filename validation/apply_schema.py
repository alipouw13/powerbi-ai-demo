"""Apply schema.sql and publish the question bank to the SQL database.

A Fabric SQL database takes DDL over its TDS endpoint, not over the item API,
so the schema cannot be applied by the script that creates the database. This
is that missing step, and it is a script rather than a manual instruction
because "run this by hand in the portal" is the step everybody skips.

Authentication is the caller's own Entra token, passed through the ODBC
pre-login attribute the way Azure SQL expects. There is no password anywhere,
and the person running it needs read/write on the database in Fabric.

Both scripts are idempotent. `schema.sql` guards every statement and
`publish_question_bank.py` emits a MERGE, so running this twice is a no-op and
running it after a partial failure resumes.

Usage:
    python validation/apply_schema.py            # apply, then verify
    python validation/apply_schema.py --check    # verify only, change nothing
"""

from __future__ import annotations

import argparse
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import SQL_CONNECTION_STRING, require  # noqa: E402
from publish_question_bank import bank_sha, build_merge  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# The documented ODBC attribute for an Entra access token.
SQL_COPT_SS_ACCESS_TOKEN = 1256


def token() -> str:
    result = subprocess.run(
        ["az", "account", "get-access-token",
         "--resource", "https://database.windows.net/",
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, shell=True, check=True,
    )
    return result.stdout.strip()


def odbc_connection_string(driver: str) -> str:
    """Turn the item's connectionString into one ODBC accepts.

    Fabric hands out an ADO.NET connection string. ODBC uses different
    spellings for the same settings, and rejects the ADO.NET ones outright
    rather than ignoring them, so this is a translation and not tidying.
    """
    replacements = {
        "Encrypt=True": "Encrypt=yes",
        "Encrypt=False": "Encrypt=no",
        "Trust Server Certificate=False": "TrustServerCertificate=no",
        "Trust Server Certificate=True": "TrustServerCertificate=yes",
        "Multiple Active Result Sets=False": "MARS_Connection=no",
        "Multiple Active Result Sets=True": "MARS_Connection=yes",
        "Connect Timeout=": "Connection Timeout=",
        "Data Source=": "Server=",
        "Initial Catalog=": "Database=",
    }
    text = SQL_CONNECTION_STRING
    for old, new in replacements.items():
        text = text.replace(old, new)
    return f"Driver={{{driver}}};{text}"


def connect():
    import pyodbc

    # Newest available driver. 17 predates some of the TLS defaults Fabric
    # expects, so preferring it silently would produce a confusing handshake
    # failure rather than a clear one.
    drivers = [d for d in pyodbc.drivers() if "ODBC Driver" in d and "SQL Server" in d]
    if not drivers:
        raise SystemExit(
            "no Microsoft ODBC driver for SQL Server is installed. Install "
            "ODBC Driver 18: https://aka.ms/odbc18"
        )
    driver = sorted(drivers)[-1]

    encoded = token().encode("utf-16-le")
    packed = struct.pack(f"<I{len(encoded)}s", len(encoded), encoded)

    return pyodbc.connect(
        odbc_connection_string(driver),
        attrs_before={SQL_COPT_SS_ACCESS_TOKEN: packed},
        autocommit=True,
    )


def batches(script: str) -> list[str]:
    """Split a script on its GO separators.

    GO is a client directive rather than T-SQL, so the driver rejects it. Only
    a line that is exactly GO counts, otherwise a column named `go` or a
    comment mentioning it would split a statement in half.
    """
    out: list[str] = []
    current: list[str] = []
    for line in script.splitlines():
        if line.strip().upper() == "GO":
            if current:
                out.append("\n".join(current))
                current = []
            continue
        current.append(line)
    if current and "\n".join(current).strip():
        out.append("\n".join(current))
    return [b for b in out if b.strip()]


def run(cursor, label: str, script: str) -> None:
    parts = batches(script)
    print(f"{label}: {len(parts)} batch(es)")
    for index, batch in enumerate(parts, 1):
        try:
            cursor.execute(batch)
        except Exception as exc:  # noqa: BLE001
            print(f"  batch {index} failed")
            print(f"  {batch.strip()[:300]}")
            raise SystemExit(f"  {exc}") from None
    print(f"{label}: applied")


def verify(cursor) -> int:
    expected_tables = {
        "questions", "runs", "answers", "defects",
        "feedback", "approvals", "remediations",
    }
    expected_views = {"open_approvals", "remediation_queue"}

    cursor.execute(
        "SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = 'dbo'"
    )
    found = {name: kind for name, kind in cursor.fetchall()}
    tables = {n for n, k in found.items() if k == "BASE TABLE"}
    views = {n for n, k in found.items() if k == "VIEW"}

    print()
    print(f"tables: {len(tables)}  {', '.join(sorted(tables))}")
    print(f"views : {len(views)}  {', '.join(sorted(views))}")

    missing = (expected_tables - tables) | (expected_views - views)
    if missing:
        print(f"\nMISSING: {', '.join(sorted(missing))}")
        return 1

    cursor.execute(
        "SELECT COUNT(*), MIN(bank_sha), SUM(CASE WHEN kind = 'probe' THEN 1 ELSE 0 END) "
        "FROM dbo.questions"
    )
    count, sha, probes = cursor.fetchone()
    print(f"questions: {count} ({probes} probes), bank_sha {sha}")

    if count != 18:
        print(f"\nexpected 18 questions, found {count}")
        return 1
    if sha != bank_sha():
        print(f"\npublished bank_sha {sha} is not the current {bank_sha()}. "
              "Re-run without --check to republish.")
        return 1

    # The view the report and the function both read. Selecting from it proves
    # the joins resolve, which a CREATE VIEW does not.
    cursor.execute("SELECT COUNT(*) FROM dbo.remediation_queue")
    print(f"remediation_queue: {cursor.fetchone()[0]} row(s)")
    cursor.execute("SELECT COUNT(*) FROM dbo.open_approvals")
    print(f"open_approvals: {cursor.fetchone()[0]} row(s)")

    print("\nschema is current")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify only, change nothing")
    args = parser.parse_args()

    require("FABRIC_SQL_CONNECTION_STRING")

    connection = connect()
    cursor = connection.cursor()
    try:
        if not args.check:
            if not SCHEMA_PATH.exists():
                raise SystemExit("run python validation/build_sql_schema.py first")
            run(cursor, "schema", SCHEMA_PATH.read_text(encoding="utf-8"))
            run(cursor, "question bank", build_merge())
        return verify(cursor)
    finally:
        cursor.close()
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
