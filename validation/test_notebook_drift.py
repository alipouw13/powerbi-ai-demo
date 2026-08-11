"""Guard the generated notebook against drift and syntax errors.

The notebook embeds copies of eval_harness.py and agent_client.py because a
Fabric notebook cannot import from this repo. Embedded copies rot. These
tests fail the moment the committed notebook stops matching the modules it
was generated from, and they compile every code cell so that a broken cell
is caught here rather than 20 minutes into a Spark session.
"""

from __future__ import annotations

import ast
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_agent_remediation_notebook as agent_builder  # noqa: E402
import build_eval_notebook as builder  # noqa: E402
import build_mirror_notebook as mirror_builder  # noqa: E402
import build_remediation_notebook as remediation_builder  # noqa: E402
import publish_question_bank as bank  # noqa: E402

NOTEBOOK = Path(__file__).resolve().parent.parent / "fabric" / "agent_eval.ipynb"
REMEDIATION_NOTEBOOK = (
    Path(__file__).resolve().parent.parent / "fabric" / "agent_remediate.ipynb"
)
AGENT_NOTEBOOK = (
    Path(__file__).resolve().parent.parent / "fabric" / "agent_remediate_agent.ipynb"
)
MIRROR_NOTEBOOK = (
    Path(__file__).resolve().parent.parent / "fabric" / "mirror_approvals.ipynb"
)


class TestNotebookIsCommitted(unittest.TestCase):
    def test_notebook_exists(self) -> None:
        self.assertTrue(NOTEBOOK.exists(), "run python validation/build_eval_notebook.py")


class TestNotebookMatchesSource(unittest.TestCase):
    def setUp(self) -> None:
        self.committed = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        self.regenerated = builder.build_notebook()

    def test_no_drift(self) -> None:
        self.assertEqual(
            self.committed,
            self.regenerated,
            "fabric/agent_eval.ipynb is stale. Run "
            "python validation/build_eval_notebook.py and commit the result.",
        )


class TestMirrorNotebook(unittest.TestCase):
    """The mirror had no tests at all, which is how it shipped broken.

    It ran every minute, failed every time, and succeeded whenever anybody
    tested it by hand straight after approving something. That looked like a
    scheduling fault for a day. The cause was one line that assumed a query
    always returns something iterable.
    """

    def setUp(self) -> None:
        self.nb = json.loads(MIRROR_NOTEBOOK.read_text(encoding="utf-8"))
        self.code_cells = [c for c in self.nb["cells"] if c["cell_type"] == "code"]
        self.source = "\n".join("".join(c["source"]) for c in self.code_cells)

    def test_no_drift(self) -> None:
        self.assertEqual(
            self.nb, mirror_builder.build_notebook(),
            "fabric/mirror_approvals.ipynb is stale. Run "
            "python validation/build_mirror_notebook.py and commit the result.",
        )

    def test_every_code_cell_compiles(self) -> None:
        for index, cell in enumerate(self.code_cells):
            source = "".join(cell["source"])
            if source.lstrip().startswith("%"):
                continue
            with self.subTest(cell=index):
                try:
                    ast.parse(source)
                except SyntaxError as exc:
                    self.fail(f"code cell {index} does not parse: {exc}")

    def sql_rows(self):
        """Lift sql_rows out of the notebook and make it callable.

        Executing the whole cell would need notebookutils and a live
        workspace, so only the function is compiled. That keeps this a real
        test of the shipped code rather than of a copy.
        """
        tree = ast.parse(self.source)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "sql_rows":
                namespace: dict = {}
                exec(compile(ast.Module([node], []), "<sql_rows>", "exec"),  # noqa: S102
                     namespace)
                return namespace["sql_rows"]
        self.fail("the mirror notebook has no sql_rows helper")

    def test_no_rows_to_mirror_is_not_an_error(self) -> None:
        """The steady state. Almost every run has nothing to copy.

        connect_to_artifact returns None rather than an empty frame when a
        SELECT matches nothing, so this is the case that broke it.
        """
        self.assertEqual(self.sql_rows()(None), [])

    def test_a_dataframe_like_result_is_converted(self) -> None:
        class Frame:
            def to_dict(self, orient):
                assert orient == "records"
                return [{"approval_id": "a"}]

        self.assertEqual(self.sql_rows()(Frame()), [{"approval_id": "a"}])

    def test_a_plain_iterable_result_is_accepted(self) -> None:
        self.assertEqual(self.sql_rows()([{"approval_id": "a"}]),
                         [{"approval_id": "a"}])

    def test_nothing_iterates_a_query_result_directly(self) -> None:
        """Every SELECT has to go through sql_rows, or None crashes it again."""
        self.assertNotIn("list(pending)", self.source)
        self.assertIn("sql_rows(pending)", self.source)

    def test_it_is_a_python_notebook_not_spark(self) -> None:
        """Scheduled runs use the stored metadata, not the kernel you picked.

        notebookutils.data does not exist in a Spark session, so a mirror
        stored as Spark works when you run it by hand and fails on every
        schedule.
        """
        metadata = self.nb["metadata"]
        self.assertEqual(metadata.get("kernel_info", {}).get("name"), "jupyter")
        self.assertEqual(
            metadata.get("microsoft", {}).get("language_group"), "jupyter_python")

    def test_committed_notebook_has_no_deployment_binding(self) -> None:
        self.assertFalse(self.nb["metadata"].get("dependencies"))

    def test_parameters_are_empty_in_source_control(self) -> None:
        params = "".join(
            "".join(c["source"]) for c in self.code_cells
            if "parameters" in c.get("metadata", {}).get("tags", [])
        )
        namespace: dict = {}
        exec(compile(params, "<params>", "exec"), namespace)  # noqa: S102
        for key in ("WORKSPACE_ID", "KUSTO_URI"):
            if key in namespace:
                with self.subTest(parameter=key):
                    self.assertEqual(namespace[key], "")


class TestNotebookStructure(unittest.TestCase):
    def setUp(self) -> None:
        self.nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        self.code_cells = [c for c in self.nb["cells"] if c["cell_type"] == "code"]

    def test_every_code_cell_compiles(self) -> None:
        for index, cell in enumerate(self.code_cells):
            source = "".join(cell["source"])
            if source.lstrip().startswith("%"):
                continue  # magics are not Python
            with self.subTest(cell=index):
                try:
                    ast.parse(source)
                except SyntaxError as exc:
                    self.fail(f"code cell {index} does not parse: {exc}")

    def test_has_a_parameters_cell(self) -> None:
        tagged = [
            c for c in self.code_cells
            if "parameters" in c.get("metadata", {}).get("tags", [])
        ]
        self.assertEqual(len(tagged), 1, "exactly one parameters cell expected")

    def test_committed_notebook_has_no_deployment_binding(self) -> None:
        # A lakehouse binding names a workspace and a lakehouse, so committing
        # one leaks the topology and makes the notebook run against somebody
        # else's data on import. Attach the lakehouse after deploying.
        self.assertNotIn("dependencies", self.nb["metadata"])

    def test_repeat_defaults_above_one(self) -> None:
        # A repeat of 1 cannot distinguish wrong from ambiguous, which is the
        # entire reason this notebook exists rather than a manual pass.
        params = "".join(
            "".join(c["source"]) for c in self.code_cells
            if "parameters" in c.get("metadata", {}).get("tags", [])
        )
        namespace: dict = {}
        exec(compile(params, "<params>", "exec"), namespace)  # noqa: S102
        self.assertGreater(namespace["REPEAT"], 1)

    def test_embeds_the_question_bank(self) -> None:
        joined = "".join("".join(c["source"]) for c in self.code_cells)
        self.assertIn("What is our total net revenue?", joined)
        self.assertIn("Show me sales for the Northwest region.", joined)

    def test_the_embedded_bank_hash_matches_the_publisher(self) -> None:
        # A stale hash would label a run with the wrong instrument, which is
        # worse than not recording one at all: it makes two incomparable runs
        # look comparable.
        params = "".join(
            "".join(c["source"]) for c in self.code_cells
            if "parameters" in c.get("metadata", {}).get("tags", [])
        )
        namespace: dict = {}
        exec(compile(params, "<params>", "exec"), namespace)  # noqa: S102
        self.assertEqual(namespace["BANK_SHA"], bank.bank_sha())

    def test_it_publishes_to_sql_as_well_as_the_eventhouse(self) -> None:
        joined = "".join("".join(c["source"]) for c in self.code_cells)
        for table in ("dbo.runs", "dbo.answers", "dbo.defects"):
            with self.subTest(table=table):
                self.assertIn(table, joined)

    def test_the_sql_publish_is_idempotent(self) -> None:
        # Re-running after a partial failure must not double count a run, and
        # a primary key violation halfway through is worse than a no-op.
        joined = "".join("".join(c["source"]) for c in self.code_cells)
        self.assertIn("MERGE dbo.runs", joined)
        self.assertNotIn("INSERT INTO dbo.runs", joined)

    def test_the_sql_publish_is_skipped_when_unconfigured(self) -> None:
        # A deployment that has not created the database yet must still be
        # able to run the evaluation.
        joined = "".join("".join(c["source"]) for c in self.code_cells)
        self.assertIn("skipping the SQL publish", joined)

    def test_the_sql_publish_parameterises_every_value(self) -> None:
        joined = "".join("".join(c["source"]) for c in self.code_cells)
        sql_section = joined[joined.index("skipping the SQL publish"):]
        sql_section = sql_section[:sql_section.index("VERIFY") if "VERIFY" in sql_section
                                  else len(sql_section)]
        self.assertNotIn('f"MERGE', sql_section)
        self.assertNotIn("f'MERGE", sql_section)

    def test_embeds_the_harness_entry_points(self) -> None:
        joined = "".join("".join(c["source"]) for c in self.code_cells)
        for symbol in (
            "def parse_question_bank",
            "def build_expectations",
            "def grade_answer",
            "def classify_attempts",
            "def route_defect",
            "def alert_conditions",
            "class DataAgentClient",
        ):
            self.assertIn(symbol, joined, f"notebook is missing {symbol}")

    def test_notebook_never_writes_a_verified_answer(self) -> None:
        # The constraint that keeps the loop honest.
        joined = "".join("".join(c["source"]) for c in self.nb["cells"]).lower()
        for banned in ("create_verified_answer", "add_verified_answer"):
            self.assertNotIn(banned, joined)

    def test_notebook_does_not_mutate_the_agent(self) -> None:
        joined = "".join("".join(c["source"]) for c in self.code_cells).lower()
        for banned in ("update_settings", "publish_staging", "add_staging_datasource"):
            self.assertNotIn(banned, joined, "the notebook must not change the agent")


class TestRemediationNotebook(unittest.TestCase):
    def setUp(self) -> None:
        self.nb = json.loads(REMEDIATION_NOTEBOOK.read_text(encoding="utf-8"))
        self.code_cells = [c for c in self.nb["cells"] if c["cell_type"] == "code"]
        self.joined = "".join("".join(c["source"]) for c in self.code_cells)

    def test_no_drift(self) -> None:
        self.assertEqual(
            self.nb,
            remediation_builder.build_notebook(),
            "fabric/agent_remediate.ipynb is stale. Run "
            "python validation/build_remediation_notebook.py and commit the result.",
        )

    def test_every_code_cell_compiles(self) -> None:
        for index, cell in enumerate(self.code_cells):
            source = "".join(cell["source"])
            if source.lstrip().startswith("%"):
                continue
            with self.subTest(cell=index):
                try:
                    ast.parse(source)
                except SyntaxError as exc:
                    self.fail(f"code cell {index} does not parse: {exc}")

    def test_defaults_to_dry_run(self) -> None:
        # A notebook that writes to a governed semantic model must not do so
        # the first time somebody presses Run to see what it does.
        params = "".join(
            "".join(c["source"]) for c in self.code_cells
            if "parameters" in c.get("metadata", {}).get("tags", [])
        )
        namespace: dict = {}
        exec(compile(params, "<params>", "exec"), namespace)  # noqa: S102
        self.assertTrue(namespace["DRY_RUN"])
        self.assertEqual(namespace["APPROVED_BY"], "")

    def test_requires_an_approver(self) -> None:
        self.assertIn("APPROVED_BY is required", self.joined)

    def test_only_acts_on_approved_and_unapplied_rows(self) -> None:
        self.assertIn('decision == "approved"', self.joined)
        # Open work is derived by anti-joining persisted remediations, not
        # read from a mutable flag, because Kusto cannot update a row.
        self.assertIn("leftanti", self.joined)
        self.assertIn("persisted == true", self.joined)

    def test_reads_approvals_from_the_eventhouse_not_delta(self) -> None:
        # One approval store. The Delta copy used to be reconciled by hand.
        self.assertIn("read_kusto", self.joined)
        self.assertNotIn("eval_approvals", self.joined.split("open_approvals_kql")[0])

    def test_never_mutates_an_approval(self) -> None:
        # An append only store has no UPDATE. State is derived instead.
        self.assertNotIn("spark.sql(f\"\"\"\n            UPDATE", self.joined)
        self.assertNotIn("SET applied", self.joined)
        self.assertNotIn("applied = true", self.joined)

    def test_links_each_remediation_to_its_approval(self) -> None:
        # approval_id is what closes the approval, so it has to be carried.
        self.assertIn('approval_id=row["approval_id"]', self.joined)

    def test_approval_is_only_consumed_when_persisted(self) -> None:
        self.assertIn("persisted=bool(was_persisted)", self.joined)

    def test_already_present_instruction_still_closes_the_approval(self) -> None:
        # Otherwise an approval applied by an earlier run, or by a person,
        # sits open forever and nobody is prompted about it again.
        self.assertIn("already_present", self.joined)
        self.assertIn("remediation_row(r, True) for r in already_present", self.joined)

    def test_dry_run_records_nothing(self) -> None:
        # A dry run that wrote a persisted remediation would close the
        # approval without changing the model.
        self.assertIn("if rows and not DRY_RUN:", self.joined)

    def test_refuses_non_model_instruction_targets(self) -> None:
        # Agent instructions do not reach DAX generation, so applying a
        # model-class fix there would look like a change and do nothing.
        self.assertIn("unsupported instruction targets", self.joined)

    def test_backs_up_before_writing(self) -> None:
        backup = self.joined.index("backup written")
        write = self.joined.index("execute_tmsl")
        self.assertLess(backup, write, "the backup must be written before the change")

    def test_reads_back_and_fails_loudly_on_mismatch(self) -> None:
        self.assertIn("read back does not match", self.joined)

    def test_never_writes_a_verified_answer(self) -> None:
        lowered = "".join("".join(c["source"]) for c in self.nb["cells"]).lower()
        for banned in ("create_verified_answer", "add_verified_answer"):
            self.assertNotIn(banned, lowered)

    def test_uses_the_shared_merge_helper(self) -> None:
        # Rather than its own append logic, which would drift from the tests.
        self.assertIn("merge_instruction(", self.joined)

    def test_records_verified_as_false(self) -> None:
        # Merging is not verifying.
        self.assertIn("verified=False", self.joined)

    def test_checks_the_server_side_last_update(self) -> None:
        # A content read back can be served from the session's own copy of the
        # model. lastUpdate is server side, so it is the only evidence that a
        # write actually landed. This test exists because a live Activator run
        # reported success while changing nothing.
        self.assertIn("last_update_before", self.joined)
        self.assertIn("last_update_after", self.joined)
        self.assertIn("server_moved", self.joined)

    def test_fails_loudly_when_the_write_did_not_land(self) -> None:
        self.assertIn("the write did not reach the model", self.joined)

    def test_records_the_executing_identity(self) -> None:
        # A scheduled or Activator run executes as a different principal from
        # the person who clicked Run, and that is the usual cause of a silent
        # no-op, so the run must say who it was.
        self.assertIn("executing_identity", self.joined)

    def test_backup_path_is_always_defined(self) -> None:
        # It is referenced by the record cell on every path, so it must be
        # initialised before the branch rather than only inside it.
        self.assertIn('backup_path = ""', self.joined)

    def test_coerces_dry_run_from_a_string(self) -> None:
        # Activator injects parameters as strings, and "false" is truthy in
        # Python, which would turn every automated remediation into a silent
        # no-op that reports success.
        self.assertIn('str(DRY_RUN).strip().lower() not in', self.joined)

    def test_refuses_to_write_over_a_concurrent_change(self) -> None:
        # This is a read-modify-write of the whole model, so two overlapping
        # runs would each replace it from their own stale snapshot and the
        # second would discard the first one's instruction.
        self.assertIn("the model changed while this run was preparing", self.joined)

    def test_records_an_ordering_key_distinct_from_applied_ts(self) -> None:
        # A verification appends a corrected row carrying the original
        # applied_ts, so applied_ts cannot be the arg_max key.
        self.assertIn("recorded_ts=now", self.joined)


class TestAgentRemediationNotebook(unittest.TestCase):
    """The agent instruction path, and the isolation that makes it safe.

    Separate from agent_remediate because it installs the data agent SDK at
    run time, and this repo has already lost a scheduled job to a pip install
    replacing the runtime's own dependencies.
    """

    def setUp(self) -> None:
        self.nb = json.loads(AGENT_NOTEBOOK.read_text(encoding="utf-8"))
        self.code_cells = [c for c in self.nb["cells"] if c["cell_type"] == "code"]
        self.joined = "".join("".join(c["source"]) for c in self.code_cells)

    def test_no_drift(self) -> None:
        self.assertEqual(
            self.nb,
            agent_builder.build_notebook(),
            "fabric/agent_remediate_agent.ipynb is stale. Run "
            "python validation/build_agent_remediation_notebook.py.",
        )

    def test_every_code_cell_compiles(self) -> None:
        for index, cell in enumerate(self.code_cells):
            source = "".join(cell["source"])
            if source.lstrip().startswith("%"):
                continue
            with self.subTest(cell=index):
                compile(source, f"<agent_cell_{index}>", "exec")

    def test_it_has_a_parameters_cell(self) -> None:
        tagged = [c for c in self.code_cells
                  if "parameters" in c.get("metadata", {}).get("tags", [])]
        self.assertEqual(len(tagged), 1)

    def test_it_defaults_to_dry_run(self) -> None:
        params = "".join(
            "".join(c["source"]) for c in self.code_cells
            if "parameters" in c.get("metadata", {}).get("tags", [])
        )
        namespace: dict = {}
        exec(compile(params, "<params>", "exec"), namespace)  # noqa: S102
        self.assertIs(namespace["DRY_RUN"], True)

    def test_it_coerces_dry_run_from_a_string(self) -> None:
        # A reference run passes parameters as strings, and "false" is truthy.
        self.assertIn('str(DRY_RUN).strip().lower() not in', self.joined)

    def test_it_requires_an_approver(self) -> None:
        self.assertIn("APPROVED_BY is empty", self.joined)

    def test_it_rechecks_the_target_rather_than_trusting_the_caller(self) -> None:
        # The one guard that stops a model-class fix being applied where it
        # can never work, recorded as persisted, and believed.
        self.assertIn("misrouted", self.joined)
        self.assertIn('!= TARGET_DATA_AGENT', self.joined)

    def test_it_refuses_to_write_what_it_could_not_read(self) -> None:
        # update_settings replaces the whole value, so a failed read would
        # delete whatever a person wrote by hand.
        self.assertIn("Could not read the agent's current instructions", self.joined)

    def test_it_appends_under_one_heading(self) -> None:
        self.assertIn("merge_instruction", self.joined)
        self.assertIn(agent_builder.AGENT_HEADING, self.joined)

    def test_it_reads_back_and_fails_loudly_on_mismatch(self) -> None:
        self.assertIn("the write did not land", self.joined)

    def test_it_only_acts_on_approved_and_unapplied_rows(self) -> None:
        self.assertIn('decision == "approved"', self.joined)
        self.assertIn("join kind=leftanti", self.joined)

    def test_it_records_verified_as_false(self) -> None:
        # Merging is not verifying. An evaluation run decides that.
        self.assertIn("verified=false", self.joined)

    def test_dry_run_records_nothing(self) -> None:
        self.assertIn("DRY_RUN, not recording", self.joined)

    def test_it_never_writes_a_verified_answer(self) -> None:
        for forbidden in ("verified_answer", "set_verified_answer"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.joined)

    def test_it_never_touches_the_semantic_model(self) -> None:
        # The two paths are separate so that a broken SDK cannot damage the
        # model. Reaching for TMSL here would undo that.
        for forbidden in ("execute_tmsl", "get_tmsl", "CustomInstructions"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.joined)

    def test_the_install_is_confined_to_this_notebook(self) -> None:
        self.assertIn("%pip install", self.joined)
        for other in (NOTEBOOK, REMEDIATION_NOTEBOOK):
            # Code cells only. Both of those notebooks discuss the pip install
            # rule in prose, and that prose is the reason the rule exists.
            source = "".join(
                "".join(c["source"])
                for c in json.loads(other.read_text(encoding="utf-8"))["cells"]
                if c["cell_type"] == "code"
            )
            with self.subTest(notebook=other.name):
                self.assertNotIn("%pip install", source)


class TestRemediationHandsOffTheAgentWork(unittest.TestCase):
    def setUp(self) -> None:
        nb = json.loads(REMEDIATION_NOTEBOOK.read_text(encoding="utf-8"))
        self.joined = "".join(
            "".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"
        )

    def test_it_splits_rather_than_refusing_everything(self) -> None:
        self.assertIn("agent_pending", self.joined)
        self.assertIn("TARGET_DATA_AGENT", self.joined)

    def test_it_uses_a_reference_run_not_an_inline_run(self) -> None:
        # %run would share the execution context, and the whole point of the
        # split is that the SDK install gets its own session.
        self.assertIn("notebookutils.notebook.run(", self.joined)
        self.assertNotIn("%run agent_remediate_agent", self.joined)

    def test_a_failed_handoff_does_not_fail_the_model_work(self) -> None:
        # The model change has already landed and been recorded by this point.
        self.assertIn("agent remediation failed", self.joined)
        self.assertIn("The approvals stay open", self.joined)

    def test_it_still_refuses_a_target_it_cannot_act_on(self) -> None:
        self.assertIn("unsupported instruction targets", self.joined)


class TestEmbeddedHarnessBehavesLikeTheModule(unittest.TestCase):
    """Execute the embedded copy and check it still grades correctly.

    Proves the extraction did not silently mangle the logic, without needing
    Spark or a workspace.
    """

    def setUp(self) -> None:
        nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        harness_src = None
        for cell in nb["cells"]:
            source = "".join(cell["source"])
            if "def classify_attempts" in source:
                harness_src = source
                break
        self.assertIsNotNone(harness_src, "harness cell not found")
        self.ns: dict = {}
        exec(compile(harness_src, "<embedded_harness>", "exec"), self.ns)  # noqa: S102

    def test_embedded_classification_matches(self) -> None:
        classify = self.ns["classify_attempts"]
        self.assertEqual(classify(["Correct"] * 3), "stable_pass")
        self.assertEqual(classify(["Wrong"] * 3), "stable_failure")
        self.assertEqual(classify(["Correct", "Wrong"]), "flake")

    def test_embedded_grading_matches(self) -> None:
        expected = self.ns["Expected"]("Q01", ((412918.50, "money"),))
        grade, _ = self.ns["grade_answer"](expected, "Total is $412,918.50.")
        self.assertEqual(grade, "Correct")

        grade, _ = self.ns["grade_answer"](expected, "Total is $417,047.69.")
        self.assertEqual(grade, "Wrong")

    def test_embedded_question_bank_parses_to_eighteen(self) -> None:
        nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        bank = None
        for cell in nb["cells"]:
            source = "".join(cell["source"])
            if "QUESTION_BANK_MD" in source:
                ns: dict = {}
                exec(compile(source.split("questions =")[0], "<bank>", "exec"), ns)  # noqa: S102
                bank = ns["QUESTION_BANK_MD"]
                break
        self.assertIsNotNone(bank)
        parsed = self.ns["parse_question_bank"](bank)
        self.assertEqual(len(parsed), 18)


if __name__ == "__main__":
    unittest.main(verbosity=2)
