"""Hold the AgentEvals model to the rules that make it readable by AI.

The deployed model can be asked whether its measures evaluate, and
`build_agentevals_model.py --apply` does exactly that. It cannot be asked
anything else: the executeQueries endpoint refuses `INFO.MEASURES` and the
other DMVs, so "does every visible column have a description" has no answer
over REST.

These tests answer it from the spec instead. The spec is what gets deployed,
so a rule proved here is a rule the model obeys.

Run with:

    python -m unittest discover -s validation -p "test_*.py" -v
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_agentevals_model as model  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# Measures that exist so a report control can bind to them, rather than to
# answer a question. They are held to different rules below.
BINDING_MEASURES = {"Selected Question ID"}


def visible_columns():
    for table in model.TABLES:
        for column in table.columns:
            if not column.hidden:
                yield table, column


def all_columns():
    for table in model.TABLES:
        for column in table.columns:
            yield table, column


class TestEverythingVisibleIsDescribed(unittest.TestCase):
    """Copilot reads descriptions. An undescribed field is a guess."""

    def test_every_table_has_a_description(self) -> None:
        for table in model.TABLES:
            with self.subTest(table=table.name):
                self.assertTrue(table.description.strip())

    def test_every_visible_column_has_a_description(self) -> None:
        for table, column in visible_columns():
            with self.subTest(table=table.name, column=column.name):
                self.assertTrue(column.description.strip())

    def test_every_measure_has_a_description(self) -> None:
        for measure in model.MEASURES:
            with self.subTest(measure=measure.name):
                self.assertTrue(measure.description.strip())

    def test_descriptions_lead_with_the_meaning(self) -> None:
        """Copilot reads roughly the first 200 characters.

        A description that spends them on a caveat has spent them.
        """
        for measure in model.MEASURES:
            with self.subTest(measure=measure.name):
                opening = measure.description[:200]
                self.assertNotIn("Do not", opening[:40])
                self.assertGreater(len(opening.split()), 5)


class TestNothingCanBeSummedByAccident(unittest.TestCase):
    """The failure this model exists to avoid, applied to itself.

    `runs.score` is 13 out of 15 for one run. Summed over ten runs it is 130,
    which is not a wrong number so much as a meaningless one, and it looks
    perfectly reasonable on a card. Every number worth adding up has a
    measure, so no column needs to be summable.
    """

    def test_no_column_is_set_to_summarize(self) -> None:
        for table, column in all_columns():
            with self.subTest(table=table.name, column=column.name):
                self.assertEqual(column.summarize_by, "none")

    def test_per_run_score_columns_are_hidden(self) -> None:
        runs = next(t for t in model.TABLES if t.source == "runs")
        for name in ("score", "max_score", "previous_score", "flake_count",
                     "failure_count", "guardrails_lost_count", "errored_count"):
            column = next(c for c in runs.columns if c.source == name)
            with self.subTest(column=name):
                self.assertTrue(
                    column.hidden,
                    f"{name} is a per-run value. Visible, it invites a sum "
                    "across runs, which is why there is a measure for it.",
                )

    def test_latency_is_hidden_behind_measures(self) -> None:
        answers = next(t for t in model.TABLES if t.source == "answers")
        latency = next(c for c in answers.columns if c.source == "latency_ms")
        self.assertTrue(latency.hidden)
        self.assertTrue(
            any("Response Time" in m.name for m in model.MEASURES),
            "hiding latency without a measure over it just loses the data",
        )


class TestKeysAreHidden(unittest.TestCase):
    """A GUID is never an answer to a business question."""

    KEY_SUFFIXES = ("_id", "_oid")

    def test_identifier_columns_are_hidden(self) -> None:
        for table, column in all_columns():
            if not column.source.endswith(self.KEY_SUFFIXES):
                continue
            # question_id on Questions is the exception, and the reason is
            # that people say "Q7" out loud. It is a label, not a key.
            if table.source == "questions" and column.source == "question_id":
                continue
            with self.subTest(table=table.name, column=column.source):
                self.assertTrue(column.hidden)


class TestRelationships(unittest.TestCase):
    def test_every_relationship_points_at_a_real_column(self) -> None:
        columns = {
            (table.name, column.name)
            for table in model.TABLES for column in table.columns
        }
        for rel in model.RELATIONSHIPS:
            with self.subTest(relationship=f"{rel.from_table}->{rel.to_table}"):
                self.assertIn((rel.from_table, rel.from_column), columns)
                self.assertIn((rel.to_table, rel.to_column), columns)

    def test_the_ambiguous_path_is_the_inactive_one(self) -> None:
        """Questions reaches Remediations through Approvals.

        A second live path would make the filter ambiguous, and Power BI
        rejects an ambiguous model outright rather than picking one.
        """
        inactive = [r for r in model.RELATIONSHIPS if not r.active]
        self.assertEqual(len(inactive), 1)
        self.assertEqual(inactive[0].from_table, "Remediations")
        self.assertEqual(inactive[0].to_table, "Questions")

    def test_every_relationship_says_why_it_exists(self) -> None:
        for rel in model.RELATIONSHIPS:
            with self.subTest(relationship=f"{rel.from_table}->{rel.to_table}"):
                self.assertTrue(rel.why.strip())


class TestMeasures(unittest.TestCase):
    def test_measure_names_are_unique(self) -> None:
        names = [m.name for m in model.MEASURES]
        self.assertEqual(len(names), len(set(names)))

    def test_every_measure_belongs_to_a_table_in_the_model(self) -> None:
        tables = {t.name for t in model.TABLES}
        for measure in model.MEASURES:
            with self.subTest(measure=measure.name):
                self.assertIn(measure.table, tables)

    def test_every_analysis_measure_is_in_a_display_folder(self) -> None:
        """Folders keep the field list readable.

        Report bindings are exempt and are checked separately: a field whose
        only job is to be found in a portal dialog should not be one expand
        deeper than the columns beside it.
        """
        for measure in model.MEASURES:
            if measure.name in BINDING_MEASURES:
                continue
            with self.subTest(measure=measure.name):
                self.assertTrue(measure.folder)

    def test_binding_measures_sit_at_the_root_of_their_table(self) -> None:
        for name in BINDING_MEASURES:
            measure = next(m for m in model.MEASURES if m.name == name)
            with self.subTest(measure=name):
                self.assertEqual(measure.folder, "")

    def test_measures_do_not_use_reserved_words_as_variables(self) -> None:
        """A VAR called Current compiles nowhere and deploys fine.

        Fabric accepted it, left the measure in an error state, and said
        nothing. It was only found by evaluating the measure afterwards.
        """
        reserved = {"current", "date", "value", "true", "false", "not",
                    "order", "row", "table", "column", "measure"}
        pattern = re.compile(r"\bVAR\s+(\w+)")
        for measure in model.MEASURES:
            for name in pattern.findall(measure.expression):
                with self.subTest(measure=measure.name, var=name):
                    self.assertNotIn(name.lower(), reserved)

    def test_measures_reference_model_names_not_sql_names(self) -> None:
        """The rename is the point. A measure that reads dbo's names undoes it."""
        sql_names = {t.source for t in model.TABLES}
        for measure in model.MEASURES:
            for referenced in re.findall(r"'([^']+)'\[", measure.expression):
                with self.subTest(measure=measure.name, table=referenced):
                    self.assertNotIn(referenced, sql_names)


class TestSourceIsUntouched(unittest.TestCase):
    """Rename in the model, never in the database.

    The SQL schema is the loop's operational store and other things write to
    it. A model that renamed a source column would simply stop loading.
    """

    def test_every_table_maps_to_a_table_in_schema_sql(self) -> None:
        schema = (ROOT / "validation" / "schema.sql").read_text(encoding="utf-8")
        for table in model.TABLES:
            with self.subTest(table=table.source):
                self.assertIn(f"dbo.{table.source}", schema)

    def test_every_column_maps_to_a_column_in_schema_sql(self) -> None:
        schema = (ROOT / "validation" / "schema.sql").read_text(encoding="utf-8")
        for table, column in all_columns():
            with self.subTest(table=table.source, column=column.source):
                self.assertRegex(schema, rf"\b{re.escape(column.source)}\b")

    def test_the_model_covers_every_table_in_the_schema(self) -> None:
        expected = {"questions", "runs", "answers", "defects", "feedback",
                    "approvals", "remediations"}
        self.assertEqual({t.source for t in model.TABLES}, expected)


class TestGeneratedTmdl(unittest.TestCase):
    """The TMDL has to parse, and Fabric's parser is the strict kind."""

    def setUp(self) -> None:
        self.parts = model.build("00000000-0000-0000-0000-000000000000")

    def test_every_table_becomes_a_part(self) -> None:
        for table in model.TABLES:
            with self.subTest(table=table.name):
                self.assertIn(f"definition/tables/{table.name}.tmdl", self.parts)

    def test_descriptions_use_the_triple_slash_form(self) -> None:
        """`description:` is not a property in this context.

        Fabric rejects the whole definition for it, naming a line number and
        not the reason, so this is worth pinning.
        """
        for path, text in self.parts.items():
            if not path.endswith(".tmdl"):
                continue
            with self.subTest(part=path):
                self.assertNotIn("\tdescription:", text)

    def test_names_with_spaces_are_quoted(self) -> None:
        table = self.parts["definition/tables/Evaluation Runs.tmdl"]
        self.assertIn("table 'Evaluation Runs'", table)
        self.assertIn("column 'Run Time'", table)

    def test_partitions_still_point_at_the_sql_table(self) -> None:
        for table in model.TABLES:
            text = self.parts[f"definition/tables/{table.name}.tmdl"]
            with self.subTest(table=table.name):
                self.assertIn(f"entityName: {table.source}", text)
                self.assertIn("schemaName: dbo", text)
                self.assertIn("mode: directLake", text)

    def test_hidden_columns_are_marked_hidden(self) -> None:
        text = self.parts["definition/tables/Evaluation Runs.tmdl"]
        run_id = text.split("column 'Run ID'")[1].split("column")[0]
        self.assertIn("isHidden", run_id)

    def test_implicit_measures_are_not_discouraged(self) -> None:
        """This flag is off on purpose, and the reason is worth keeping.

        It breaks translytical binding: a data function parameter is bound
        through conditional formatting, which needs an aggregation, and the
        flag switches implicit aggregations off model-wide. Every column greys
        out and Power BI says "a measure is required here".

        What it was protecting against is handled better by hiding columns.
        Every per-run score column is hidden, so nobody can drag one onto a
        visual and sum it across runs. The rule below is what actually holds
        that line, and it is asserted by TestNothingCanBeSummedByAccident.
        """
        self.assertNotIn("discourageImplicitMeasures",
                         self.parts["definition/model.tmdl"])

    def test_the_inactive_relationship_is_written_as_inactive(self) -> None:
        text = self.parts["definition/relationships.tmdl"]
        self.assertEqual(text.count("isActive: false"), 1)

    def test_lineage_tags_are_stable_across_builds(self) -> None:
        again = model.build("00000000-0000-0000-0000-000000000000")
        self.assertEqual(self.parts, again)

    def test_no_tenant_ids_leak_into_the_committed_measure_file(self) -> None:
        text = (ROOT / "semantic-model" / "agentevals" / "measures.dax").read_text(
            encoding="utf-8")
        guid = re.compile(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
            re.IGNORECASE)
        self.assertEqual(guid.findall(text), [])


class TestMeasuresDocIsCurrent(unittest.TestCase):
    """measures.dax is generated. A hand edit would be silently overwritten."""

    def test_committed_file_matches_the_spec(self) -> None:
        path = ROOT / "semantic-model" / "agentevals" / "measures.dax"
        self.assertTrue(path.exists(), "run build_agentevals_model.py --docs")
        self.assertEqual(
            path.read_text(encoding="utf-8"), model.build_measures_doc(),
            "measures.dax is out of date. Run:\n"
            "  python validation/build_agentevals_model.py --docs",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
