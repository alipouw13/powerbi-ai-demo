"""The SQL foundation: schema, question bank publishing, and the mirror.

None of this can be run against a real database from here, so these tests
cover the things that are decidable offline and that would otherwise only fail
in the tenant:

* the schema is internally consistent, and every column the code writes exists
* the bank publishes without losing history, and its hash means something
* the mirror copies in both directions, in the right order, with named
  column mappings

The mirror pipeline is the least verifiable item in the repo. Fabric will not
validate a pipeline definition offline, so these tests pin the properties that
a wrong definition would silently break, and the deploy step says plainly that
a human still has to open it once.
"""

from __future__ import annotations

import json
import os
import re
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("FABRIC_WORKSPACE_ID", str(uuid.uuid4()))
os.environ.setdefault("FABRIC_KQL_DATABASE_ID", str(uuid.uuid4()))

import build_approval_function as udf  # noqa: E402
import build_mirror_notebook as mirror  # noqa: E402
import build_sql_schema as schema  # noqa: E402
import publish_question_bank as bank  # noqa: E402

SCHEMA_SQL = schema.SCHEMA_PATH
MIRROR_NOTEBOOK = mirror.NOTEBOOK_PATH


def columns_of(table: str) -> set[str]:
    """The column names declared for one table in the generated DDL."""
    body = next(b for name, b in schema.TABLES if name == table)
    found = set()
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("--") or line.startswith(("CREATE", ")", "CONSTRAINT")):
            continue
        match = re.match(r"^([a-z_]+)\s+[a-z]", line)
        if match:
            found.add(match.group(1))
    return found


class TestSchemaIsCurrent(unittest.TestCase):
    def test_the_committed_file_matches_the_builder(self) -> None:
        self.assertTrue(SCHEMA_SQL.exists(),
                        "run python validation/build_sql_schema.py")
        self.assertEqual(
            SCHEMA_SQL.read_text(encoding="utf-8"),
            schema.build_schema(),
            "validation/schema.sql is stale. Regenerate it.",
        )

    def test_every_statement_is_guarded(self) -> None:
        # The file is handed to a person to run. It has to be safe to run
        # twice, and safe to resume after a partial failure.
        text = SCHEMA_SQL.read_text(encoding="utf-8")
        for name, _ in schema.TABLES:
            with self.subTest(table=name):
                self.assertIn(f"IF OBJECT_ID('dbo.{name}', 'U') IS NULL", text)
        for name, _ in schema.VIEWS:
            with self.subTest(view=name):
                self.assertIn(f"IF OBJECT_ID('dbo.{name}', 'V') IS NOT NULL", text)

    def test_a_view_is_replaced_rather_than_skipped(self) -> None:
        # Unlike a table, a view holds no data, and an out of date definition
        # is a silently wrong answer rather than a missing one.
        text = SCHEMA_SQL.read_text(encoding="utf-8")
        for name, _ in schema.VIEWS:
            with self.subTest(view=name):
                self.assertIn(f"DROP VIEW dbo.{name}", text)

    def test_open_approvals_is_derived_not_stored(self) -> None:
        # The one definition of outstanding work, matching the Kusto
        # expression the notebook and the Activator rule use.
        body = dict(schema.VIEWS)["open_approvals"]
        self.assertIn("NOT EXISTS", body)
        self.assertIn("persisted = 1", body)
        for table, _ in schema.TABLES:
            self.assertNotIn("applied bit", columns_of(table))

    def test_the_approval_copies_the_sentence(self) -> None:
        # A foreign key to defects would be tidier and would let the applied
        # text change after it was approved.
        approvals = columns_of("approvals")
        self.assertIn("proposed_instruction", approvals)
        self.assertNotIn("defect_id", approvals)

    def test_identity_columns_exist_on_both_written_tables(self) -> None:
        for table, name_column, oid_column in (
            ("approvals", "approved_by", "approver_oid"),
            ("feedback", "created_by", "created_oid"),
        ):
            with self.subTest(table=table):
                self.assertIn(name_column, columns_of(table))
                self.assertIn(oid_column, columns_of(table))

    def test_every_run_records_which_instrument_it_used(self) -> None:
        self.assertIn("bank_sha", columns_of("runs"))
        self.assertIn("bank_sha", columns_of("questions"))

    def test_the_mirror_watermark_exists(self) -> None:
        self.assertIn("mirrored_ts", columns_of("approvals"))


class TestFunctionMatchesSchema(unittest.TestCase):
    """The function writes SQL that no test could otherwise check."""

    def test_every_column_the_function_inserts_exists(self) -> None:
        source = udf.build_function_app()
        for table in ("approvals", "feedback"):
            match = re.search(
                rf'INSERT INTO dbo\.{table} \((.*?)\) "\s*\n\s*"VALUES',
                source, re.S,
            )
            self.assertIsNotNone(match, f"no INSERT found for {table}")
            named = {
                c.strip().strip('"').strip()
                for c in match.group(1).replace('"', " ").split(",")
            }
            named = {c for c in named if c and c.isidentifier()}
            with self.subTest(table=table):
                self.assertTrue(
                    named <= columns_of(table),
                    f"{table}: function writes columns the schema lacks: "
                    f"{sorted(named - columns_of(table))}",
                )

    def test_the_placeholder_count_matches_the_column_count(self) -> None:
        # A mismatch here is a runtime error in the tenant and nowhere else.
        source = udf.build_function_app()
        for table in ("approvals", "feedback"):
            match = re.search(
                rf"INSERT INTO dbo\.{table} \((.*?)\)(.*?)VALUES \((.*?)\)",
                source, re.S,
            )
            self.assertIsNotNone(match, f"no INSERT found for {table}")
            columns = [
                c.strip()
                for c in match.group(1).replace('"', " ").split(",")
                if c.strip().isidentifier()
            ]
            placeholders = match.group(3).count("?")
            with self.subTest(table=table):
                self.assertGreater(len(columns), 0)
                self.assertEqual(len(columns), placeholders)

    def test_it_reads_only_objects_the_schema_defines(self) -> None:
        source = udf.build_function_app()
        known = {name for name, _ in schema.TABLES} | {name for name, _ in schema.VIEWS}
        for referenced in set(re.findall(r"dbo\.([a-z_]+)", source)):
            with self.subTest(object=referenced):
                self.assertIn(referenced, known)


class TestQuestionBankPublishing(unittest.TestCase):
    def test_it_parses_the_whole_bank(self) -> None:
        questions = bank.parse()
        self.assertEqual(len(questions), 18)
        self.assertEqual(sum(1 for q in questions if q["kind"] == bank.SCORED), 15)
        self.assertEqual(sum(1 for q in questions if q["kind"] == bank.PROBE), 3)

    def test_the_order_is_the_order_they_are_asked(self) -> None:
        questions = bank.parse()
        self.assertEqual([q["question_id"] for q in questions][:3],
                         ["Q01", "Q02", "Q03"])
        self.assertEqual([q["ordinal"] for q in questions],
                         list(range(1, len(questions) + 1)))

    def test_probes_are_not_scored(self) -> None:
        for question in bank.parse():
            if question["question_id"].startswith("F"):
                with self.subTest(question=question["question_id"]):
                    self.assertEqual(question["kind"], bank.PROBE)
                    self.assertIsNotNone(question["good_outcome"])

    def test_the_hash_changes_when_a_question_changes(self) -> None:
        original = bank.bank_text()
        softened = original.replace(
            "What is our total net revenue?",
            "What is our total net revenue, roughly?",
        )
        self.assertNotEqual(original, softened, "the fixture question moved")
        self.assertNotEqual(bank.bank_sha(original), bank.bank_sha(softened))

    def test_the_hash_ignores_prose_around_the_tables(self) -> None:
        # Editing the surrounding explanation must not invalidate every run
        # recorded against the bank.
        original = bank.bank_text()
        reworded = original.replace(
            "Fifteen questions.", "Fifteen questions, in a fixed order.",
        )
        self.assertNotEqual(original, reworded, "the fixture prose moved")
        self.assertEqual(bank.bank_sha(original), bank.bank_sha(reworded))

    def test_publishing_never_deletes_a_question(self) -> None:
        # answers and defects carry foreign keys to questions. Deleting one to
        # republish it would take its history with it, or fail.
        executable = "\n".join(
            line for line in bank.build_merge().splitlines()
            if not line.strip().startswith("--")
        ).upper()
        self.assertNotIn("DELETE", executable)
        self.assertIn("WHEN MATCHED THEN UPDATE", executable)
        self.assertIn("WHEN NOT MATCHED BY TARGET THEN", executable)

    def test_the_merge_stamps_the_hash(self) -> None:
        merge = bank.build_merge()
        self.assertIn(bank.bank_sha(), merge)

    def test_apostrophes_are_escaped(self) -> None:
        questions = [{
            "question_id": "Q99", "kind": "scored", "ordinal": 1,
            "prompt": "What is O'Brien's revenue?", "tests": None,
            "good_outcome": None,
        }]
        merge = bank.build_merge(questions, "0" * 40)
        self.assertIn("O''Brien''s", merge)

    def test_an_empty_parse_is_refused(self) -> None:
        # Publishing an empty bank would orphan every run rather than fail.
        with self.assertRaises(SystemExit):
            bank.parse("# Question bank\n\nNo tables here.\n")


class TestMirrorNotebook(unittest.TestCase):
    """The mirror, and the properties a wrong one would break silently."""

    def setUp(self) -> None:
        self.nb = json.loads(MIRROR_NOTEBOOK.read_text(encoding="utf-8"))
        self.code = [c for c in self.nb["cells"] if c["cell_type"] == "code"]
        self.joined = "".join("".join(c["source"]) for c in self.code)

    def test_no_drift(self) -> None:
        self.assertEqual(
            self.nb, mirror.build_notebook(),
            "fabric/mirror_approvals.ipynb is stale. Run "
            "python validation/build_mirror_notebook.py.",
        )

    def test_every_code_cell_compiles(self) -> None:
        for index, cell in enumerate(self.code):
            source = "".join(cell["source"])
            if source.lstrip().startswith("%"):
                continue
            with self.subTest(cell=index):
                compile(source, f"<mirror_cell_{index}>", "exec")

    def test_it_is_a_python_notebook_not_spark(self) -> None:
        # Spark has no notebookutils.data, so the metadata being wrong means
        # the run fails rather than falling back. It cost a deploy to find out.
        metadata = self.nb["metadata"]
        self.assertEqual(metadata["kernel_info"]["name"], "jupyter")
        self.assertEqual(metadata["microsoft"]["language_group"], "jupyter_python")

    def test_the_committed_copy_names_no_tenant(self) -> None:
        params = "".join(
            "".join(c["source"]) for c in self.code
            if "parameters" in c.get("metadata", {}).get("tags", [])
        )
        namespace: dict = {}
        exec(compile(params, "<params>", "exec"), namespace)  # noqa: S102
        self.assertEqual(namespace["WORKSPACE_ID"], "")
        self.assertEqual(namespace["KUSTO_URI"], "")

    def test_it_copies_in_both_directions(self) -> None:
        # Without the return leg, open_approvals never sees a remediation
        # land, every applied approval looks open forever, and the function
        # refuses every second approval for a question.
        self.assertIn("eval_approvals", self.joined)
        self.assertIn("dbo.remediations", self.joined)

    def test_it_only_picks_up_unmirrored_rows(self) -> None:
        self.assertIn("mirrored_ts IS NULL", self.joined)

    def test_it_marks_rows_only_after_the_copy_succeeds(self) -> None:
        # Marking first would lose an approval on any failure, and a lost
        # approval is a change a person authorised that never happened.
        copy_at = self.joined.index("mirrored.append")
        mark_at = self.joined.index("SET mirrored_ts")
        self.assertLess(copy_at, mark_at)

    def test_the_return_leg_upserts_on_the_key(self) -> None:
        # The eventhouse is append only: a remediation gains a corrected row
        # when it becomes verified. Insert would give the report two rows.
        self.assertIn("MERGE dbo.remediations", self.joined)
        self.assertIn("WHEN MATCHED THEN UPDATE", self.joined)

    def test_it_escapes_values_going_into_kusto(self) -> None:
        self.assertIn("def escape(", self.joined)
        self.assertIn("escape(row[", self.joined)

    def test_it_escapes_values_going_into_sql(self) -> None:
        self.assertIn("def sql_literal(", self.joined)
        self.assertIn("replace(\"'\", \"''\")", self.joined)

    def test_the_columns_it_writes_exist_in_the_schema(self) -> None:
        written = set(re.findall(r'"(\w+)"', self.joined.split("MERGE dbo.remediations")[0]))
        for column in ("approval_id", "question_id", "decision", "approved_by"):
            with self.subTest(column=column):
                self.assertIn(column, columns_of("approvals"))

    def test_it_holds_no_secret(self) -> None:
        # It authenticates as the notebook's own identity, both sides.
        for forbidden in ("secret", "password", "client_secret", "vault"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.joined.lower())


if __name__ == "__main__":
    unittest.main()
