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

import build_eval_notebook as builder  # noqa: E402

NOTEBOOK = Path(__file__).resolve().parent.parent / "fabric" / "agent_eval.ipynb"


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

    def test_default_lakehouse_is_attached(self) -> None:
        lakehouse = self.nb["metadata"]["dependencies"]["lakehouse"]
        self.assertTrue(lakehouse["default_lakehouse"])
        self.assertTrue(lakehouse["default_lakehouse_workspace_id"])

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
