"""Validate the real-time dashboard definition before it reaches Fabric.

Every test here corresponds to a real load failure. The dashboard's own
validation happens in the browser, which is a slow and unpleasant place to
discover that an id was not a UUID, so the same rules run here instead.

Run with:

    python -m unittest discover -s validation -p "test_*.py" -v
"""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_dashboard as dash  # noqa: E402


class TestDefinitionValidates(unittest.TestCase):
    def setUp(self) -> None:
        self.definition = dash.build_definition()

    def test_no_problems(self) -> None:
        self.assertEqual(dash.validate(self.definition), [])

    def test_schema_version_is_set(self) -> None:
        # "Missing migration for dashboard version 78. Required version: 78
        # Received version: 78" was a real load failure caused by declaring
        # the target version. The client migrates forward from the version in
        # the file, so the file must name a version it has a migration from.
        self.assertEqual(self.definition["schema_version"], "52")

    def test_auto_refresh_has_no_extra_properties(self) -> None:
        # At this schema version autoRefresh accepts only `enabled`. Adding
        # defaultDuration or minimumDuration fails validation with "must NOT
        # have unevaluated properties" and stops the dashboard loading.
        self.assertEqual(set(self.definition["autoRefresh"]), {"enabled"})

    def test_every_tile_is_a_table(self) -> None:
        # A chart carries column bindings that have to survive the client's
        # schema migration, and a tile that fails to render takes the whole
        # dashboard with it. Tables render from any result shape.
        for tile in self.definition["tiles"]:
            with self.subTest(tile=tile["title"]):
                self.assertEqual(tile["visualType"], "table")
                self.assertEqual(tile["visualOptions"], {})

    def test_every_id_is_a_real_uuid(self) -> None:
        # Readable ids like "ds-agent-eval" are rejected at load time with
        # "Needs to follow the UUID format as defined by RFC 4122".
        for section in ("tiles", "queries", "pages", "dataSources"):
            for entry in self.definition[section]:
                with self.subTest(section=section, id=entry["id"]):
                    uuid.UUID(entry["id"])

    def test_each_query_is_referenced_exactly_once(self) -> None:
        referenced = [t["queryRef"]["queryId"] for t in self.definition["tiles"]]
        self.assertEqual(len(referenced), len(set(referenced)))
        self.assertEqual(set(referenced), {q["id"] for q in self.definition["queries"]})

    def test_ids_are_stable_across_runs(self) -> None:
        # Otherwise every deploy replaces the dashboard and drops pinned
        # references and share targets.
        again = dash.build_definition()
        self.assertEqual(
            [t["id"] for t in self.definition["tiles"]],
            [t["id"] for t in again["tiles"]],
        )
        self.assertEqual(self.definition["id"], again["id"])

    def test_required_top_level_sections_exist(self) -> None:
        for key in ("tiles", "queries", "pages", "dataSources", "baseQueries",
                    "parameters", "title", "autoRefresh"):
            self.assertIn(key, self.definition)


class TestValidatorCatchesRealFailures(unittest.TestCase):
    """The validator has to fail on the things that actually broke."""

    def setUp(self) -> None:
        self.definition = dash.build_definition()

    def test_rejects_a_non_uuid_id(self) -> None:
        self.definition["dataSources"][0]["id"] = "ds-agent-eval"
        problems = dash.validate(self.definition)
        self.assertTrue(any("RFC 4122" in p for p in problems), problems)

    def test_rejects_a_query_referenced_twice(self) -> None:
        shared = self.definition["tiles"][0]["queryRef"]["queryId"]
        self.definition["tiles"][1]["queryRef"]["queryId"] = shared
        problems = dash.validate(self.definition)
        self.assertTrue(any("referenced 2 times" in p for p in problems), problems)

    def test_rejects_a_tile_pointing_at_a_missing_query(self) -> None:
        self.definition["tiles"][0]["queryRef"]["queryId"] = str(uuid.uuid4())
        problems = dash.validate(self.definition)
        self.assertTrue(any("unknown query" in p for p in problems), problems)

    def test_rejects_a_tile_on_an_unknown_page(self) -> None:
        self.definition["tiles"][0]["pageId"] = str(uuid.uuid4())
        problems = dash.validate(self.definition)
        self.assertTrue(any("unknown page" in p for p in problems), problems)

    def test_rejects_a_query_on_an_unknown_data_source(self) -> None:
        self.definition["queries"][0]["dataSource"]["dataSourceId"] = str(uuid.uuid4())
        problems = dash.validate(self.definition)
        self.assertTrue(any("unknown data source" in p for p in problems), problems)

    def test_rejects_duplicate_tile_ids(self) -> None:
        self.definition["tiles"][1]["id"] = self.definition["tiles"][0]["id"]
        problems = dash.validate(self.definition)
        self.assertTrue(any("duplicate id" in p for p in problems), problems)

    def test_rejects_an_unsupported_auto_refresh_property(self) -> None:
        # The real failure: "/autoRefresh ... must NOT have unevaluated
        # properties" for defaultDuration and minimumDuration.
        self.definition["autoRefresh"]["defaultDuration"] = "5m"
        problems = dash.validate(self.definition)
        self.assertTrue(
            any("autoRefresh" in p and "defaultDuration" in p for p in problems),
            problems,
        )

    def test_rejects_an_unsupported_tile_property(self) -> None:
        self.definition["tiles"][0]["description"] = "not in the schema"
        problems = dash.validate(self.definition)
        self.assertTrue(any("description" in p for p in problems), problems)

    def test_rejects_an_unsupported_query_property(self) -> None:
        self.definition["queries"][0]["name"] = "not in the schema"
        problems = dash.validate(self.definition)
        self.assertTrue(any("name" in p for p in problems), problems)


class TestQueriesMatchTheTables(unittest.TestCase):
    """Guard against a tile querying a column the pipeline stopped writing."""

    def setUp(self) -> None:
        self.text = "\n".join(q["text"] for q in dash.build_definition()["queries"])

    def test_only_known_tables_are_queried(self) -> None:
        known = {"eval_runs", "eval_defects", "eval_approvals", "eval_remediations"}
        referenced = {
            line.split("|")[0].strip()
            for line in self.text.splitlines()
            if line and not line.startswith(("|", " ", ")")) and "(" not in line
        }
        referenced = {r for r in referenced if r and not r.startswith("//")}
        self.assertTrue(referenced.issubset(known), f"unknown tables: {referenced - known}")

    def test_the_remediation_queue_shows_the_instruction_text(self) -> None:
        # The whole reason the dashboard exists.
        self.assertIn("proposed_instruction", self.text)

    def test_it_surfaces_what_cannot_be_automated(self) -> None:
        self.assertIn("Needs a human", str(dash.TILE_SPECS))


if __name__ == "__main__":
    unittest.main(verbosity=2)
