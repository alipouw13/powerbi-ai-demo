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
import inspect
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("FABRIC_WORKSPACE_ID", str(uuid.uuid4()))
os.environ.setdefault("FABRIC_KQL_DATABASE_ID", str(uuid.uuid4()))

import apply_schema  # noqa: E402
import build_approval_function as udf  # noqa: E402
import build_mirror_notebook as mirror  # noqa: E402
import build_sql_schema as schema  # noqa: E402
import eval_harness as eh  # noqa: E402
import publish_question_bank as bank  # noqa: E402

SCHEMA_SQL = schema.SCHEMA_PATH
MIRROR_NOTEBOOK = mirror.NOTEBOOK_PATH
EVAL_BUILDER = Path(__file__).resolve().parent / "build_eval_notebook.py"


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


class TestTheQueueReportsTheModelNotThePaperTrail(unittest.TestCase):
    """Drift between what this database remembers and what the model holds.

    The AI instructions are editable in the portal. When somebody replaces
    that box, every sentence the loop appended disappears and not one row
    here changes, so the queue goes on saying "already present, nothing to
    write" about a sentence that no longer exists. That is worse than saying
    nothing: it sends the next person hunting a measure bug that is not
    there. This happened on the demo tenant.
    """

    def setUp(self) -> None:
        self.sql = next(b for name, b in schema.VIEWS if name == "remediation_queue")
        # Comments quote the very strings these tests look for, so ordering
        # must be judged on the SQL alone.
        self.code = "\n".join(
            line for line in self.sql.splitlines()
            if not line.strip().startswith("--")
        )

    def test_the_defects_table_records_what_the_model_held(self) -> None:
        self.assertIn("instruction_in_model", columns_of("defects"))

    def test_the_column_is_nullable(self) -> None:
        """Rows written before the column existed cannot be back-filled.

        Nobody knows what the model held at the time, and a default of 0
        would report every historical defect as drift.
        """
        body = next(b for name, b in schema.TABLES if name == "defects")
        line = next(x for x in body.splitlines() if "instruction_in_model" in x)
        self.assertIn("NULL", line)
        self.assertNotIn("NOT NULL", line)

    def test_existing_databases_get_the_column(self) -> None:
        """The CREATE TABLE is guarded on the table not existing, so without
        a migration this column only ever appears on a fresh database."""
        self.assertIn(
            ("defects", "instruction_in_model",
             "ALTER TABLE dbo.defects ADD instruction_in_model bit NULL;"),
            schema.MIGRATIONS,
        )

    def test_the_queue_reports_drift(self) -> None:
        self.assertIn("but not in the model now", self.code)

    def test_drift_is_only_claimed_about_the_newest_run(self) -> None:
        """A fix that worked leaves no new defect.

        Its last defect row stays behind with the flag still false, so
        without scoping to the newest run every successful fix would be
        reported as missing from the model.
        """
        self.assertIn("l.run_id = n.run_id", self.code)
        self.assertIn("SELECT TOP 1 run_id FROM dbo.runs ORDER BY run_ts DESC",
                      self.code)

    def test_drift_outranks_the_remembered_status(self) -> None:
        """It has to be tested before the branches it contradicts, or the
        CASE returns the stale answer and the new one is unreachable."""
        drift = self.code.index("but not in the model now")
        for stale in ("already present, nothing to write",
                      "applied and verified"):
            with self.subTest(branch=stale):
                self.assertLess(drift, self.code.index(stale))

    def test_an_undecided_question_is_not_called_drift(self) -> None:
        """'awaiting approval' must still win, because nothing was applied."""
        self.assertLess(self.code.index("awaiting approval"),
                        self.code.index("but not in the model now"))

    def test_a_rejected_question_is_not_called_drift(self) -> None:
        self.assertLess(self.code.index("'rejected'"),
                        self.code.index("but not in the model now"))

    def test_a_null_flag_cannot_trigger_drift(self) -> None:
        """Compared with = 0, so the historical NULLs stay silent."""
        self.assertIn("l.instruction_in_model = 0", self.code)

    def test_the_eval_notebook_writes_the_flag(self) -> None:
        """A column nothing populates is a column that always reads NULL."""
        source = EVAL_BUILDER.read_text(encoding="utf-8")
        self.assertIn("instruction_in_model=bool(p.instruction_in_model)", source)
        self.assertIn("instruction_in_model", source)

    def test_every_delta_append_can_take_a_new_column(self) -> None:
        """Delta refuses an append carrying a column the table has not seen.

        Without mergeSchema, adding a field to the harness fails the run at
        the write step -- after all 15 questions have been asked, paid for,
        and thrown away. The Kusto side needs .alter-merge on the eventhouse
        table for the same reason; that one cannot be fixed from here.
        """
        source = EVAL_BUILDER.read_text(encoding="utf-8")
        appends = [line for line in source.splitlines() if "saveAsTable" in line]
        self.assertEqual(len(appends), 3, appends)
        window = source.split("saveAsTable")
        for index, chunk in enumerate(window[:-1]):
            with self.subTest(write=index):
                self.assertIn("mergeSchema", chunk[-400:])


class TestReadingTheInstructionsOutOfAModel(unittest.TestCase):
    """`current_instructions` is the one place that knows where they live.

    Every level of the path is optional in TMSL, and this runs inside an
    evaluation. An IndexError here fails a run about coffee sales.
    """

    def a_model(self, text):
        return {"model": {"cultures": [
            {"name": "en-US",
             "linguisticMetadata": {"content": {"CustomInstructions": text}}}
        ]}}

    def test_it_reads_them(self) -> None:
        self.assertEqual(eh.current_instructions(self.a_model("Use net sales.")),
                         "Use net sales.")

    def test_a_model_with_no_cultures_is_not_an_error(self) -> None:
        self.assertEqual(eh.current_instructions({"model": {"cultures": []}}), "")

    def test_a_model_with_no_linguistic_metadata_is_not_an_error(self) -> None:
        self.assertEqual(
            eh.current_instructions({"model": {"cultures": [{"name": "en-US"}]}}), "")

    def test_an_empty_script_is_not_an_error(self) -> None:
        for script in ({}, {"model": {}}, None):
            with self.subTest(script=script):
                self.assertEqual(eh.current_instructions(script), "")

    def test_a_null_value_becomes_a_string(self) -> None:
        """TMSL can carry an explicit null, and "" is what callers can use."""
        self.assertEqual(eh.current_instructions(self.a_model(None)), "")

    def test_it_agrees_with_instruction_present(self) -> None:
        model = self.a_model("Alpha.\nBeta.")
        text = eh.current_instructions(model)
        self.assertTrue(eh.instruction_present(text, "Beta."))
        self.assertFalse(eh.instruction_present(text, "Gamma."))


class TestTheHarnessAsksTheModelNotItsOwnHistory(unittest.TestCase):
    """Where "already applied" comes from, and why it cannot be the log.

    The AI instructions are editable in the portal. A person replacing that
    box removes sentences this loop applied without changing a single row, so
    a harness that trusts eval_remediations keeps insisting a fix is in place,
    escalates the question to "needs a human" every run, and never
    re-proposes the one sentence that would fix it.
    """

    def setUp(self) -> None:
        self.source = EVAL_BUILDER.read_text(encoding="utf-8")

    def test_it_reads_the_live_model(self) -> None:
        self.assertIn("fabric.get_tmsl(SEMANTIC_MODEL_NAME", self.source)
        self.assertIn("current_instructions(_model)", self.source)

    def test_it_no_longer_trusts_the_remediation_log(self) -> None:
        self.assertNotIn('spark.table(lh + "eval_remediations")', self.source)

    def test_it_tests_membership_line_by_line(self) -> None:
        """Substring matching would call a sentence present because a longer
        one happens to contain it."""
        self.assertIn("instruction_present(_live, text)", self.source)

    def test_an_unreadable_model_proposes_everything(self) -> None:
        """Fail noisy, not silent.

        Assuming the history is right would be quiet and wrong; proposing a
        fix that is already there is merely noise a person can dismiss.
        """
        window = self.source[self.source.index("fabric.get_tmsl"):]
        window = window[:window.index("proposals = propose_fixes")]
        self.assertIn("except Exception", window)
        self.assertIn("applied_instructions = frozenset()", window)
        self.assertIn("WARNING", window)

    def test_the_model_name_is_a_parameter_of_this_notebook(self) -> None:
        """Reading the model needs its name, and a bare NameError here is
        invisible: the read is wrapped in `except Exception`, so a missing
        parameter degrades to "the model has no instructions" and every fix
        gets proposed again forever, with only a warning nobody reads.
        """
        nb = json.loads(
            (Path(__file__).resolve().parent.parent
             / "fabric" / "agent_eval.ipynb").read_text(encoding="utf-8"))
        params = "".join(
            "".join(c["source"]) for c in nb["cells"]
            if "parameters" in c.get("metadata", {}).get("tags", [])
        )
        namespace: dict = {}
        exec(compile(params, "<params>", "exec"), namespace)  # noqa: S102
        self.assertIn("SEMANTIC_MODEL_NAME", namespace)
        self.assertTrue(namespace["SEMANTIC_MODEL_NAME"])


class TestWhoAppliedIt(unittest.TestCase):
    """`interactive_approver`, and the line it must not cross.

    Typing your own name into a generated notebook buys nothing: the cell is
    regenerated on every deploy so the value does not survive, and a typed
    string is the least trustworthy identity available. When a person is
    sitting there, the platform already knows who they are.

    It must stay shut for unattended runs. The Activator rule passes
    APPROVED_BY itself, so an empty one there means the rule lost its
    parameter, and applying a change to a governed model on the strength of a
    missing value is the thing this whole guard exists to prevent.
    """

    HUMAN = {"isForInteractive": True, "userName": "System Administrator",
             "userId": "00000000-0000-0000-0000-000000000000"}

    def test_an_interactive_run_is_attributed(self) -> None:
        self.assertEqual(
            eh.interactive_approver(self.HUMAN),
            "System Administrator (00000000-0000-0000-0000-000000000000)")

    def test_an_unattended_run_gets_nothing(self) -> None:
        context = dict(self.HUMAN, isForInteractive=False)
        self.assertEqual(eh.interactive_approver(context), "")

    def test_a_pipeline_run_gets_nothing(self) -> None:
        context = dict(self.HUMAN, isForInteractive=False, isForPipeline=True)
        self.assertEqual(eh.interactive_approver(context), "")

    def test_a_missing_flag_is_not_interactive(self) -> None:
        """Absent must not read as permission."""
        context = {k: v for k, v in self.HUMAN.items() if k != "isForInteractive"}
        self.assertEqual(eh.interactive_approver(context), "")

    def test_an_empty_context_is_not_an_error(self) -> None:
        for context in ({}, None):
            with self.subTest(context=context):
                self.assertEqual(eh.interactive_approver(context), "")

    def test_the_object_id_is_required(self) -> None:
        """A display name alone cannot identify anybody. Two people can share
        one, and it can be changed."""
        context = dict(self.HUMAN, userId="")
        self.assertEqual(eh.interactive_approver(context), "")

    def test_a_display_name_does_not_have_to_look_like_an_address(self) -> None:
        """The regression this was built from.

        This tenant reports `userName` as "System Administrator". A check for
        something email-shaped would reject the real person and let nobody
        through, which is worse than the friction it replaced.
        """
        self.assertIn("System Administrator", eh.interactive_approver(self.HUMAN))

    def test_an_unknown_name_falls_back_to_the_id(self) -> None:
        context = dict(self.HUMAN, userName="unknown")
        self.assertEqual(eh.interactive_approver(context),
                         "00000000-0000-0000-0000-000000000000")


class TestTheRemediationNotebookAttributesTheRun(unittest.TestCase):
    def setUp(self) -> None:
        self.source = (Path(__file__).resolve().parent
                       / "build_remediation_notebook.py").read_text(encoding="utf-8")

    def test_it_infers_before_it_refuses(self) -> None:
        """Order matters: refusing first makes the fallback unreachable."""
        self.assertLess(self.source.index("interactive_approver(notebook_context)"),
                        self.source.index("APPROVED_BY is required"))

    def test_it_still_refuses_when_nobody_is_there(self) -> None:
        self.assertIn("APPROVED_BY is required", self.source)

    def test_it_says_so_when_it_infers(self) -> None:
        """A change attributed by inference must not look like one somebody
        typed. The run output is the only place that can say which."""
        self.assertIn("APPROVED_BY was empty, so this run is attributed",
                      self.source)

    def test_it_does_not_print_one_identity_as_two(self) -> None:
        """`applied_by` pairs the typed name with the platform's. When the
        first came from the platform they are the same by construction, and
        showing both reads like corroboration from a source that is not
        there."""
        self.assertIn("APPROVED_BY if APPROVED_BY_INFERRED", self.source)


class TestDryRunIsResolvedNotTrusted(unittest.TestCase):
    """The single most expensive parameter in the loop.

    Activator and pipelines inject parameters as strings, and every non-empty
    string is truthy in Python. `if DRY_RUN:` on the literal "false" turns an
    approved remediation into a no-op that reports success: the person
    approved a fix, everything says it worked, and the model never changed.
    That is indistinguishable from the loop being broken, and it is what a
    demo audience would see.
    """

    def test_a_string_false_means_apply(self) -> None:
        for value in ("false", "False", "FALSE", " false ", "0", "no"):
            with self.subTest(value=value):
                self.assertFalse(eh.resolve_dry_run(value))

    def test_a_real_boolean_still_works(self) -> None:
        self.assertTrue(eh.resolve_dry_run(True))
        self.assertFalse(eh.resolve_dry_run(False))

    def test_the_default_writes_nothing(self) -> None:
        self.assertTrue(eh.resolve_dry_run("true"))

    def test_anything_unrecognised_writes_nothing(self) -> None:
        """Fail safe. A blank box or a typo must not authorise a write to a
        governed model; the cost of a needless dry run is one more click."""
        for value in ("", "   ", "maybe", None, "flase"):
            with self.subTest(value=value):
                self.assertTrue(eh.resolve_dry_run(value))


class TestBothRemediationNotebooksResolveDryRun(unittest.TestCase):
    """And can actually call it.

    `agent_remediate_agent` does not embed the harness -- it talks to REST and
    the eventhouse and needs none of the scoring -- so a shared helper is only
    shared if the build puts a copy in the notebook. Getting that wrong is a
    NameError on the agent path, which is the path nobody runs until a demo.
    """

    NOTEBOOKS = ("agent_remediate.ipynb", "agent_remediate_agent.ipynb")

    def cells(self, name):
        nb = json.loads((Path(__file__).resolve().parent.parent / "fabric" / name)
                        .read_text(encoding="utf-8"))
        return [("".join(c["source"])) for c in nb["cells"] if c["cell_type"] == "code"]

    def test_each_one_resolves_it(self) -> None:
        for name in self.NOTEBOOKS:
            with self.subTest(notebook=name):
                self.assertIn("resolve_dry_run(DRY_RUN)", "".join(self.cells(name)))

    def test_each_one_can_reach_the_definition(self) -> None:
        for name in self.NOTEBOOKS:
            with self.subTest(notebook=name):
                cells = self.cells(name)
                defined = next(
                    (i, s.index("def resolve_dry_run")) for i, s in enumerate(cells)
                    if "def resolve_dry_run" in s
                )
                used = next(
                    (i, s.index("resolve_dry_run(DRY_RUN)")) for i, s in enumerate(cells)
                    if "resolve_dry_run(DRY_RUN)" in s
                )
                self.assertLess(defined, used,
                                f"{name} calls resolve_dry_run before defining it")

    def test_the_copy_is_lifted_not_retyped(self) -> None:
        """One definition. A hand-copied second one can drift, and the two
        notebooks would then disagree about what "false" means."""
        source = inspect.getsource(eh.resolve_dry_run)
        agent = "".join(self.cells("agent_remediate_agent.ipynb"))
        self.assertIn(source.strip(), agent)

    def test_nobody_reintroduces_the_fail_open_blank(self) -> None:
        """An earlier version treated "" as false, so a cleared parameter box
        applied changes for real."""
        for name in self.NOTEBOOKS:
            with self.subTest(notebook=name):
                self.assertNotIn('("false", "0", "no", "")',
                                 "".join(self.cells(name)))


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

    TABLES_WRITTEN = ("approvals", "feedback", "remediations")

    def inserts(self, table: str) -> list[tuple[list[str], int]]:
        """Every INSERT the function makes into one table.

        Every one, not the first one. There are two into dbo.approvals now,
        and a version of this test that stopped at the first would have said
        nothing about the one bulk approval uses.
        """
        source = udf.build_function_app()
        found = []
        for match in re.finditer(
            rf"INSERT INTO dbo\.{table} \((.*?)\)(.*?)VALUES \((.*?)\)",
            source, re.S,
        ):
            columns = [
                c.strip()
                for c in match.group(1).replace('"', " ").split(",")
                if c.strip().isidentifier()
            ]
            found.append((columns, match.group(3).count("?")))
        return found

    def test_every_column_the_function_inserts_exists(self) -> None:
        for table in self.TABLES_WRITTEN:
            statements = self.inserts(table)
            self.assertTrue(statements, f"no INSERT found for {table}")
            for index, (columns, _) in enumerate(statements):
                with self.subTest(table=table, statement=index):
                    named = {c for c in columns if c.isidentifier()}
                    self.assertTrue(
                        named <= columns_of(table),
                        f"{table}: function writes columns the schema lacks: "
                        f"{sorted(named - columns_of(table))}",
                    )

    def test_the_placeholder_count_matches_the_column_count(self) -> None:
        # A mismatch here is a runtime error in the tenant and nowhere else.
        for table in self.TABLES_WRITTEN:
            statements = self.inserts(table)
            self.assertTrue(statements, f"no INSERT found for {table}")
            for index, (columns, placeholders) in enumerate(statements):
                with self.subTest(table=table, statement=index):
                    self.assertGreater(len(columns), 0)
                    self.assertEqual(len(columns), placeholders)

    def test_it_reads_only_objects_the_schema_defines(self) -> None:
        source = udf.build_function_app()
        known = {name for name, _ in schema.TABLES} | {name for name, _ in schema.VIEWS}
        for referenced in set(re.findall(r"dbo\.([a-z_]+)", source)):
            with self.subTest(object=referenced):
                self.assertIn(referenced, known)

    def test_only_the_bulk_path_writes_a_remediation(self) -> None:
        """Nothing here applies anything, and that has to stay true.

        The remediation row bulk approval writes is not an application: it
        records that this decision needs no write of its own. It is allowed
        precisely because it has no applied_ts, so it can never be mistaken
        for a change to the model or the agent.
        """
        source = udf.build_function_app()
        body = source.split("def approve_similar")[-1]
        self.assertIn("INSERT INTO dbo.remediations", body)
        self.assertEqual(source.count("INSERT INTO dbo.remediations"), 1)


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

    def test_closing_rows_reach_the_eventhouse(self) -> None:
        """Bulk approvals are written in SQL and closed in SQL.

        The remediation notebook finds open work with a leftanti join in the
        eventhouse. Without this leg it would see four approved questions with
        nothing closing them and queue four identical writes.
        """
        self.assertIn("set-or-append eval_remediations", self.joined)
        self.assertIn("in_eventhouse", self.joined)

    def test_a_closing_row_is_copied_before_the_approval_it_closes(self) -> None:
        """Otherwise the rule fires on an approval nothing appears to close."""
        push_at = self.joined.index("SQL remediation(s) not yet in the eventhouse")
        approvals_at = self.joined.index("approval(s) to mirror")
        self.assertLess(push_at, approvals_at)

    def test_it_never_copies_a_row_back_out_again(self) -> None:
        """The two remediation legs must not fight over the same rows."""
        self.assertIn("not in in_eventhouse", self.joined)

    def test_a_null_datetime_survives_the_round_trip(self) -> None:
        """A null applied_ts is the marker for "nothing was written".

        It arrives from this driver as pandas NaT, which is not None, is not
        equal to itself, and formats as the string "NaT".
        """
        self.assertIn("def kusto_datetime(", self.joined)
        self.assertIn('"NaT"', self.joined)

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


class TestTheSchemaVerifier(unittest.TestCase):
    """`apply_schema.py --check` has to notice a half-upgraded database.

    Every CREATE TABLE is guarded on the table not existing, which is what
    makes the schema safe to re-run and also what makes it blind to a table
    that is already there with an older shape. So the verifier is the only
    thing standing between a missing column and a writeback that fails in
    front of whoever pressed the button.
    """

    class FakeCursor:
        """Answers the verifier's queries for a database in a chosen state."""

        def __init__(self, tables, views, columns, broken_views=()):
            self.tables = tables
            self.views = views
            self.columns = columns
            self.broken_views = set(broken_views)
            self.selected = []
            self._result = None
            self._rows = []

        def execute(self, statement, *parameters):
            normalised = " ".join(statement.split())
            if "INFORMATION_SCHEMA.TABLES" in normalised:
                self._rows = (
                    [(name, "BASE TABLE") for name in self.tables]
                    + [(name, "VIEW") for name in self.views]
                )
            elif "INFORMATION_SCHEMA.COLUMNS" in normalised:
                self._result = (1 if parameters in self.columns else 0,)
            elif "FROM dbo.questions" in normalised:
                self._result = (18, bank.bank_sha(), 3)
            elif normalised.startswith("SELECT COUNT(*) FROM dbo."):
                name = normalised.rsplit(".", 1)[-1]
                self.selected.append(name)
                if name in self.broken_views:
                    raise RuntimeError(f"Invalid column name in {name}")
                self._result = (0,)
            else:
                raise AssertionError(f"unexpected statement: {normalised[:90]}")

        def fetchone(self):
            return self._result

        def fetchall(self):
            return self._rows

    def healthy(self, **overrides):
        state = {
            "tables": {name for name, _ in schema.TABLES},
            "views": {name for name, _ in schema.VIEWS},
            "columns": {(t, c) for t, c, _ in schema.MIGRATIONS},
        }
        state.update(overrides)
        return self.FakeCursor(**state)

    def test_a_current_database_passes(self) -> None:
        self.assertEqual(apply_schema.verify(self.healthy()), 0)

    def test_it_notices_a_view_that_was_never_created(self) -> None:
        """The gap this test exists for.

        The expected objects used to be a hardcoded list, so adding
        similar_fixes to the schema left the verifier reporting "schema is
        current" for a database that did not have it, and the report page
        that reads it would have failed instead.
        """
        cursor = self.healthy(views={"open_approvals", "remediation_queue"})
        self.assertEqual(apply_schema.verify(cursor), 1)

    def test_it_notices_a_missing_migrated_column(self) -> None:
        self.assertEqual(apply_schema.verify(self.healthy(columns=set())), 1)

    def test_it_notices_a_view_that_exists_but_does_not_run(self) -> None:
        """CREATE VIEW succeeds against columns that do not exist.

        A view can be present and broken, so existence is not evidence.
        """
        cursor = self.healthy()
        cursor.broken_views = {"similar_fixes"}
        self.assertEqual(apply_schema.verify(cursor), 1)

    def test_it_selects_from_every_view_rather_than_a_chosen_two(self) -> None:
        cursor = self.healthy()
        apply_schema.verify(cursor)
        self.assertEqual(set(cursor.selected),
                         {name for name, _ in schema.VIEWS})

    def test_it_derives_what_it_expects_from_the_builder(self) -> None:
        """So a new table or view cannot be added without the verifier knowing."""
        source = Path(apply_schema.__file__).read_text(encoding="utf-8")
        verify_body = source.split("def verify(")[1].split("\ndef ")[0]
        self.assertIn("schema.TABLES", verify_body)
        self.assertIn("schema.VIEWS", verify_body)
        self.assertIn("schema.MIGRATIONS", verify_body)


if __name__ == "__main__":
    unittest.main()
