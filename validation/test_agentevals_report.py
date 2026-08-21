"""Prove the AgentEvals report only asks for fields the model actually has.

A report definition round-trips happily with a misspelled field. PBIR is not
validated against the semantic model on write, so `Answers.Grade` and
`Answers.Grades` are equally acceptable to the API, and the difference only
shows up as "can't display this visual" in front of whoever opened it.

Both sides are generated from specs in this repo, so the check is exact rather
than approximate: every Entity and Property in the report is looked up in the
model spec, and hidden columns and renamed tables are accounted for because
they come from the same source.

Run with:

    python -m unittest discover -s validation -p "test_*.py" -v
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_agentevals_model as model  # noqa: E402
import build_agentevals_report as report  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# A placeholder id, so the parts can be built without touching Fabric.
NIL = "00000000-0000-0000-0000-000000000000"


def parts() -> dict[str, str]:
    return report.build(NIL, "CY26SU08")


def visual_parts() -> dict[str, dict]:
    return {path: json.loads(text) for path, text in parts().items()
            if path.endswith("visual.json")}


def field_references(payload) -> list[tuple[str, str]]:
    """Every (entity, property) pair anywhere in a visual definition."""
    found: list[tuple[str, str]] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            for kind in ("Measure", "Column"):
                inner = node.get(kind)
                if isinstance(inner, dict) and "Property" in inner:
                    entity = (inner.get("Expression", {})
                                   .get("SourceRef", {})
                                   .get("Entity"))
                    if entity:
                        found.append((entity, inner["Property"]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return found


MODEL_COLUMNS = {
    (table.name, col.name) for table in model.TABLES for col in table.columns
}
MODEL_MEASURES = {(m.table, m.name) for m in model.MEASURES}


class TestEveryFieldResolves(unittest.TestCase):
    def test_every_reference_is_a_real_column_or_measure(self) -> None:
        for path, payload in visual_parts().items():
            for entity, prop in field_references(payload):
                with self.subTest(visual=path, field=f"{entity}[{prop}]"):
                    self.assertTrue(
                        (entity, prop) in MODEL_COLUMNS
                        or (entity, prop) in MODEL_MEASURES,
                        f"{entity}[{prop}] is not in the model. The report "
                        "would load and the visual would show an error.",
                    )

    def test_measures_are_used_as_measures(self) -> None:
        """A measure referenced as a Column silently returns nothing."""
        for path, payload in visual_parts().items():
            text = json.dumps(payload)
            for table, name in MODEL_MEASURES:
                needle = ('{"Column": {"Expression": {"SourceRef": '
                          f'{{"Entity": "{table}"}}}}, "Property": "{name}"}}')
                with self.subTest(visual=path, measure=f"{table}[{name}]"):
                    self.assertNotIn(re.sub(r"\s+", "", needle),
                                     re.sub(r"\s+", "", text))

    def test_query_refs_match_their_field(self) -> None:
        """queryRef must be Entity.Property or the visual loses its binding."""
        for path, payload in visual_parts().items():
            self._check_projections(path, payload)

    def _check_projections(self, path: str, node) -> None:
        if isinstance(node, dict):
            if "queryRef" in node and "field" in node:
                refs = field_references(node["field"])
                self.assertEqual(len(refs), 1, f"{path}: odd projection")
                entity, prop = refs[0]
                self.assertEqual(node["queryRef"], f"{entity}.{prop}",
                                 f"{path}: queryRef does not match its field")
            for value in node.values():
                self._check_projections(path, value)
        elif isinstance(node, list):
            for value in node:
                self._check_projections(path, value)


class TestNoVisualAsksForAnImpossibleJoin(unittest.TestCase):
    """A visual may use columns from at most one fact table.

    Answers and Defects both point at Questions, so a table that mixes their
    columns asks Power BI to relate one attempt to one proposed fix. No such
    relationship exists, and the visual renders as "can't determine
    relationships between the fields" rather than failing at write time. The
    first version of this report shipped exactly that, and it was only caught
    by rendering the report and looking at it.

    Measures are exempt: a measure aggregates in filter context and does not
    need a row-level path.
    """

    # The many side of every relationship in the model.
    FACT_TABLES = {rel.from_table for rel in model.RELATIONSHIPS}

    def column_entities(self, payload) -> set[str]:
        entities: set[str] = set()

        def walk(node) -> None:
            if isinstance(node, dict):
                inner = node.get("Column")
                if isinstance(inner, dict) and "Property" in inner:
                    entity = (inner.get("Expression", {})
                                   .get("SourceRef", {}).get("Entity"))
                    if entity:
                        entities.add(entity)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(payload)
        return entities

    def test_no_visual_mixes_two_fact_tables(self) -> None:
        for path, payload in visual_parts().items():
            facts = self.column_entities(payload) & self.FACT_TABLES
            with self.subTest(visual=path):
                self.assertLessEqual(
                    len(facts), 1,
                    f"columns from {sorted(facts)} in one visual. There is no "
                    "row-level path between them, so this renders as an error.",
                )

    def test_the_model_actually_has_fact_tables(self) -> None:
        """Guard the guard: an empty set would make the test above vacuous."""
        self.assertGreater(len(self.FACT_TABLES), 1)


class TestNoVisualCrossJoinsTwoTables(unittest.TestCase):
    """A visual mixing columns from two tables needs a measure to prune it.

    This is the bug that made the approval queue list fixes that did not
    exist. A table of columns alone is a cross join: Power BI groups by the
    columns it was given and, with nothing to evaluate, keeps every
    combination rather than only the ones the relationships support. The
    queue showed all eighteen questions against every outcome and every
    tier, including questions that had never failed, plus a blank question
    id for the combinations belonging to no question at all. Seventy-six
    rows where thirteen were real.

    The relationships were never wrong. Adding any measure restores the
    normal behaviour, because rows where every measure is blank are dropped,
    and a fact measure is blank exactly where no fact row exists.

    So each such visual carries a measure over its fact table, chosen to be
    worth reading rather than a hidden guard: the row count is what makes a
    recurring defect look different from a one-off. Losing it is a data
    correctness bug, not a cosmetic one, which is why this is a test.
    """

    FACT_TABLES = {rel.from_table for rel in model.RELATIONSHIPS}

    @staticmethod
    def _entities(payload, kind: str) -> set[str]:
        found: set[str] = set()

        def walk(node) -> None:
            if isinstance(node, dict):
                inner = node.get(kind)
                if isinstance(inner, dict) and "Property" in inner:
                    entity = (inner.get("Expression", {})
                                   .get("SourceRef", {}).get("Entity"))
                    if entity:
                        found.add(entity)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(payload)
        return found

    def test_every_multi_table_visual_has_a_measure(self) -> None:
        for path, payload in visual_parts().items():
            columns = self._entities(payload, "Column")
            if len(columns) < 2:
                continue
            with self.subTest(visual=path, tables=sorted(columns)):
                self.assertTrue(
                    self._entities(payload, "Measure"),
                    f"columns from {sorted(columns)} and no measure. This "
                    "renders as a cross join of every combination, which "
                    "looks like real data and is not.",
                )

    def test_the_pruning_measure_is_over_the_fact_table(self) -> None:
        """A measure over the dimension prunes nothing.

        It is non-blank for every row of the cross join, so the visual is
        just as wrong and now looks deliberate.
        """
        for path, payload in visual_parts().items():
            columns = self._entities(payload, "Column")
            if len(columns) < 2:
                continue
            facts = columns & self.FACT_TABLES
            measures = self._entities(payload, "Measure")
            with self.subTest(visual=path):
                self.assertTrue(
                    measures & facts,
                    f"measures {sorted(measures)} are not over any of the "
                    f"fact tables {sorted(facts)} whose columns this visual "
                    "shows, so they cannot prune the join.",
                )

    def test_this_would_have_caught_the_original_bug(self) -> None:
        """Guard the guard, against the version of the queue that shipped."""
        broken = {"visual": {"query": {"queryState": {"Values": {"projections": [
            {"field": report.column("Questions", "Question ID")},
            {"field": report.column("Defects", "Defect Outcome")},
        ]}}}}}
        self.assertEqual(
            self._entities(broken, "Column"), {"Questions", "Defects"})
        self.assertFalse(self._entities(broken, "Measure"))


class TestLayoutMatchesTheContosoGrid(unittest.TestCase):
    """The two reports should look like one product, not two.

    These are the numbers read off the Contoso Coffee report, so a drift here
    is a drift away from it.
    """

    def test_nothing_falls_off_the_canvas(self) -> None:
        for path, payload in visual_parts().items():
            pos = payload["position"]
            with self.subTest(visual=path):
                self.assertGreaterEqual(pos["x"], 0)
                self.assertGreaterEqual(pos["y"], 0)
                self.assertLessEqual(pos["x"] + pos["width"], report.CANVAS_W)
                self.assertLessEqual(pos["y"] + pos["height"], report.CANVAS_H)

    def test_nothing_overlaps_the_header_band(self) -> None:
        for path, payload in visual_parts().items():
            pos = payload["position"]
            kind = payload["visual"]["visualType"]
            if kind in {"shape", "textbox", "slicer"}:
                continue
            with self.subTest(visual=path):
                self.assertGreaterEqual(
                    pos["y"], report.HEADER_H,
                    "a tile under the header band is a tile nobody can read",
                )

    def test_kpi_cards_sit_on_the_shared_pitch(self) -> None:
        for path, payload in visual_parts().items():
            if payload["visual"]["visualType"] != "cardVisual":
                continue
            pos = payload["position"]
            with self.subTest(visual=path):
                self.assertIn(pos["x"], report.CARD_X)
                self.assertEqual(pos["y"], report.CARD_Y)
                self.assertEqual(pos["width"], report.CARD_W)
                self.assertEqual(pos["height"], report.CARD_H)

    def test_each_page_has_a_header_band_and_a_title(self) -> None:
        for name, _, _ in report.PAGES:
            kinds = [
                json.loads(text)["visual"]["visualType"]
                for path, text in parts().items()
                if path.startswith(f"definition/pages/{name}/visuals/")
            ]
            with self.subTest(page=name):
                self.assertEqual(kinds.count("shape"), 1)
                self.assertGreaterEqual(kinds.count("textbox"), 1)

    def test_visuals_do_not_overlap_each_other(self) -> None:
        for name, _, _ in report.PAGES:
            tiles = [
                json.loads(text)
                for path, text in parts().items()
                if path.startswith(f"definition/pages/{name}/visuals/")
            ]
            # The band sits behind everything by design, and the title sits on
            # the band, so both are excluded from the overlap check.
            boxes = [
                (t["name"], t["position"]) for t in tiles
                if t["visual"]["visualType"] not in {"shape", "textbox"}
                and t["position"]["y"] >= report.HEADER_H
            ]
            for i, (name_a, a) in enumerate(boxes):
                for name_b, b in boxes[i + 1:]:
                    overlap = (
                        a["x"] < b["x"] + b["width"]
                        and b["x"] < a["x"] + a["width"]
                        and a["y"] < b["y"] + b["height"]
                        and b["y"] < a["y"] + a["height"]
                    )
                    with self.subTest(page=name, a=name_a, b=name_b):
                        self.assertFalse(overlap, "two tiles occupy the same space")


class TestTheWritebackPage(unittest.TestCase):
    """The page only earns its name if the pieces of the task flow are there."""

    def page_two(self) -> list[dict]:
        name = report.P2_NAME
        return [json.loads(text) for path, text in parts().items()
                if path.startswith(f"definition/pages/{name}/visuals/")]

    def test_there_is_an_input_slicer_per_free_text_parameter(self) -> None:
        """approve_remediation takes decision and note, so there are two."""
        inputs = [v for v in self.page_two()
                  if v["visual"]["visualType"] == "textSlicer"]
        self.assertEqual(len(inputs), 2)

    def test_input_slicers_carry_no_data_column(self) -> None:
        """With a column bound they would filter the page, not collect input."""
        for tile in self.page_two():
            if tile["visual"]["visualType"] != "textSlicer":
                continue
            with self.subTest(visual=tile["name"]):
                self.assertNotIn("query", tile["visual"])

    def test_there_is_exactly_one_data_function_button(self) -> None:
        buttons = [v for v in self.page_two()
                   if v["visual"]["visualType"] == "actionButton"]
        self.assertEqual(len(buttons), 1)

    def test_button_state_formatting_carries_a_selector(self) -> None:
        """Without a selector, text and fill are accepted and then ignored.

        The button renders as an empty outline with no label, which is how
        the first version of this page shipped.
        """
        for tile in self.page_two():
            if tile["visual"]["visualType"] != "actionButton":
                continue
            for name in ("text", "fill", "outline"):
                for block in tile["visual"]["objects"][name]:
                    with self.subTest(block=name):
                        self.assertIn("selector", block)
                        self.assertIn("id", block["selector"])

    def test_the_button_has_a_distinct_loading_state(self) -> None:
        """A button that looks the same while it runs gets clicked twice."""
        for tile in self.page_two():
            if tile["visual"]["visualType"] != "actionButton":
                continue
            states = {block["selector"]["id"]
                      for block in tile["visual"]["objects"]["fill"]}
            self.assertIn("loading", states)

    def test_the_queue_shows_the_sentence_being_approved(self) -> None:
        """Approving text nobody can read is a rubber stamp with extra steps."""
        text = json.dumps(self.page_two())
        self.assertIn("Proposed Instruction", text)

    def test_the_page_separates_approved_applied_and_verified(self) -> None:
        text = json.dumps(self.page_two())
        for name in ("Approved", "Awaiting Apply", "Verified Fix %"):
            with self.subTest(measure=name):
                self.assertIn(name, text)


class TestTheSimilarFixesPage(unittest.TestCase):
    """One wrong behaviour, several questions, one decision.

    The harness proposes from a small library, so the same sentence turns up
    against four or five questions at once. Approving them separately would
    queue the same write four times and produce four identical lines.
    """

    def page_three(self) -> list[dict]:
        name = report.P3_NAME
        return [json.loads(text) for path, text in parts().items()
                if path.startswith(f"definition/pages/{name}/visuals/")]

    def test_the_page_exists_in_the_order(self) -> None:
        order = json.loads(parts()["definition/pages/pages.json"])["pageOrder"]
        self.assertIn(report.P3_NAME, order)

    def test_it_shows_the_sentence_the_group_shares(self) -> None:
        """Approving a group without reading the sentence is a rubber stamp."""
        text = json.dumps(self.page_three())
        self.assertIn("Proposed Instruction", text)
        self.assertIn("Questions Sharing This Fix", text)

    def test_it_has_its_own_button_and_its_own_inputs(self) -> None:
        buttons = [v for v in self.page_three()
                   if v["visual"]["visualType"] == "actionButton"]
        inputs = [v for v in self.page_three()
                  if v["visual"]["visualType"] == "textSlicer"]
        self.assertEqual(len(buttons), 1)
        self.assertEqual(len(inputs), 2)

    def test_its_slicer_ids_are_stable(self) -> None:
        """The binding names them by visual id, so the ids cannot drift."""
        names = {json.loads(text)["name"] for path, text in parts().items()
                 if path.endswith("visual.json")}
        for key in ("decision", "note"):
            with self.subTest(slicer=key):
                self.assertIn(report.vid(f"{report.P3}/input/{key}"), names)

    def test_the_two_writeback_buttons_are_not_on_the_same_page(self) -> None:
        """They take the same parameters and mean very different things.

        Side by side, approving a group when you meant to approve one
        question is a slip rather than a decision.
        """
        for name in (report.P2_NAME, report.P3_NAME):
            buttons = [
                json.loads(text) for path, text in parts().items()
                if path.startswith(f"definition/pages/{name}/visuals/")
                and json.loads(text)["visual"]["visualType"] == "actionButton"
            ]
            with self.subTest(page=name):
                self.assertEqual(len(buttons), 1)

    def test_it_separates_written_from_already_present(self) -> None:
        """A covered approval is not a fix, and must not be counted as one."""
        text = json.dumps(self.page_three())
        for name in ("Instructions Written", "Already Present",
                     "Covered By Another Approval"):
            with self.subTest(measure=name):
                self.assertIn(name, text)

    def test_it_says_that_not_approving_is_allowed(self) -> None:
        text = json.dumps(self.page_three())
        self.assertIn("Choosing not to approve them is a valid answer", text)


class TestTheApprovalButtonHasSomethingToBindTo(unittest.TestCase):
    """The writeback breaks without this, and it breaks in the portal.

    A data function parameter is bound through conditional formatting. Binding
    to the Question ID column needs an aggregation like First or Max, which
    silently picks one row out of however many are selected and records a
    decision against a question the approver did not mean.

    This model also used to set discourageImplicitMeasures, which made the
    column fail outright with "a measure is required here". That flag is off
    now, so both work and this is the safer of the two.

    Nothing in the report definition can catch a broken binding, because the
    binding is not in the report definition. This is the guard instead.
    """

    NAME = "Selected Question ID"

    def measure(self) -> model.Measure:
        found = [m for m in model.MEASURES if m.name == self.NAME]
        self.assertEqual(len(found), 1,
                         f"{self.NAME} is what the approval button binds to")
        return found[0]

    def test_the_binding_measure_exists(self) -> None:
        self.measure()

    def test_it_is_selectedvalue_not_an_aggregation(self) -> None:
        """First or Max would approve a fix for a question nobody chose."""
        expression = self.measure().expression
        self.assertIn("SELECTEDVALUE", expression)
        for aggregate in ("FIRSTNONBLANK", "MAX (", "MIN (", "TOPN"):
            with self.subTest(aggregate=aggregate):
                self.assertNotIn(aggregate, expression)

    def test_it_reads_the_question_the_queue_selects(self) -> None:
        self.assertIn("'Questions'[Question ID]", self.measure().expression)

    def test_it_is_easy_to_find_in_a_portal_dialog(self) -> None:
        """No display folder, because it has exactly one job.

        It was in one called "Report bindings", which is tidier and put the
        one field somebody needs one expand deeper than the columns they were
        already looking at, in a dialog where the obvious choice fails.
        """
        self.assertEqual(self.measure().folder, "")

    def test_the_model_does_not_discourage_implicit_measures(self) -> None:
        """Because that is what made this binding impossible in the first place.

        With the flag on, the Question ID column greys out and Power BI says
        a measure is required. With it off, both the column and this measure
        work, and this measure is still the safer of the two.
        """
        import build_agentevals_model as m

        self.assertNotIn("discourageImplicitMeasures", m.model_tmdl())


class TestTheButtonBindingSurvivesARebuild(unittest.TestCase):
    """The one part of this report that cannot be regenerated.

    The data function binding names a workspace and a function by id, so it is
    authored once in the format pane and lives only in the deployed report.
    This script replaces every part, so without carrying it over a rebuild
    deletes it and the button goes quiet. Nobody notices until an approval
    does not arrive.
    """

    def deployed_with_binding(self) -> dict[str, str]:
        """A stand-in for the real report, with a button somebody has bound."""
        built = parts()
        button_path = next(
            path for path, text in built.items()
            if path.endswith("visual.json")
            and json.loads(text)["visual"]["visualType"] == "actionButton"
        )
        payload = json.loads(built[button_path])
        # visualContainerObjects, not objects. The first version of the
        # carry-over looked under objects, found nothing, said nothing, and
        # the rebuild deleted a working binding. A test that used the wrong
        # container would have passed while the code was broken.
        payload["visual"].setdefault("visualContainerObjects", {})["visualLink"] = [{
            "properties": {
                "show": {"expr": {"Literal": {"Value": "true"}}},
                "type": {"expr": {"Literal": {"Value": "'DataFunction'"}}},
                "dataFunction": {"metadata": {"dataFunction": {
                    "name": "approve_remediation",
                    "parameters": [
                        {"name": "questionId", "type": "ValueParameter"},
                        {"name": "decision", "type": "SlicerParameter",
                         "slicer": report.vid(f"{report.P2}/input/decision")},
                        {"name": "note", "type": "SlicerParameter",
                         "slicer": report.vid(f"{report.P2}/input/note")},
                    ],
                }}},
            }
        }]
        built[button_path] = json.dumps(payload, indent=2)
        return built

    def rebuilt_button(self, deployed: dict[str, str]) -> dict:
        fresh = parts()
        report.carry_over_button_action(fresh, deployed)
        return json.loads(next(
            text for path, text in fresh.items()
            if path.endswith("visual.json")
            and json.loads(text)["visual"]["visualType"] == "actionButton"
        ))

    def test_a_fresh_build_has_no_binding_of_its_own(self) -> None:
        """Otherwise this test would pass without carrying anything over."""
        button = json.loads(next(
            text for path, text in parts().items()
            if path.endswith("visual.json")
            and json.loads(text)["visual"]["visualType"] == "actionButton"
        ))
        for container in ("objects", "visualContainerObjects"):
            with self.subTest(container=container):
                self.assertNotIn("visualLink",
                                 button["visual"].get(container, {}))

    def test_the_binding_is_carried_over(self) -> None:
        button = self.rebuilt_button(self.deployed_with_binding())
        self.assertIn("visualLink", button["visual"]["visualContainerObjects"])
        self.assertIn("approve_remediation", json.dumps(button))

    def test_the_carried_binding_keeps_its_parameter_wiring(self) -> None:
        """A binding that survives but loses its parameters is still broken."""
        button = self.rebuilt_button(self.deployed_with_binding())
        text = json.dumps(button)
        for name in ("questionId", "decision", "note"):
            with self.subTest(parameter=name):
                self.assertIn(name, text)

    def test_carrying_over_is_safe_when_nothing_is_bound(self) -> None:
        """First run: the deployed report has a button and no binding."""
        fresh = parts()
        report.carry_over_button_action(fresh, parts())
        self.assertEqual(fresh, parts())

    def test_the_slicer_ids_the_binding_points_at_are_stable(self) -> None:
        """The binding names slicers by visual id, so the ids cannot drift."""
        names = {json.loads(text)["name"] for path, text in parts().items()
                 if path.endswith("visual.json")}
        for key in ("decision", "note"):
            with self.subTest(slicer=key):
                self.assertIn(report.vid(f"{report.P2}/input/{key}"), names)

    def test_every_bound_button_is_carried_not_just_the_first(self) -> None:
        """There are two writeback buttons now.

        A carry-over that stopped at the first would keep the approval
        binding and silently drop the bulk approval one, which is the same
        failure this function exists to prevent, on a different button.
        """
        built = parts()
        buttons = [
            path for path, text in built.items()
            if path.endswith("visual.json")
            and json.loads(text)["visual"]["visualType"] == "actionButton"
        ]
        self.assertEqual(len(buttons), 2, "the report should have two buttons")

        for path, function in zip(sorted(buttons),
                                  ("approve_remediation", "approve_similar")):
            payload = json.loads(built[path])
            payload["visual"].setdefault("visualContainerObjects", {})[
                "visualLink"] = [{
                    "properties": {
                        "type": {"expr": {"Literal": {"Value": "'DataFunction'"}}},
                        "dataFunction": {"metadata": {"dataFunction": {
                            "name": function,
                            "parameters": [
                                {"name": "questionId", "type": "ValueParameter"},
                            ],
                        }}},
                    }
                }]
            built[path] = json.dumps(payload, indent=2)

        fresh = parts()
        report.carry_over_button_action(fresh, built)
        rebuilt = json.dumps([
            json.loads(text) for path, text in fresh.items()
            if path.endswith("visual.json")
            and json.loads(text)["visual"]["visualType"] == "actionButton"
        ])
        for function in ("approve_remediation", "approve_similar"):
            with self.subTest(function=function):
                self.assertIn(function, rebuilt)


class TestGeneratedPartsAreComplete(unittest.TestCase):
    REQUIRED = (
        "definition.pbir",
        "definition/report.json",
        "definition/version.json",
        "definition/pages/pages.json",
    )

    def test_every_required_part_is_present(self) -> None:
        built = parts()
        for path in self.REQUIRED:
            with self.subTest(part=path):
                self.assertIn(path, built)

    def test_every_page_in_the_order_has_a_page_json(self) -> None:
        built = parts()
        order = json.loads(built["definition/pages/pages.json"])["pageOrder"]
        for name in order:
            with self.subTest(page=name):
                self.assertIn(f"definition/pages/{name}/page.json", built)

    def test_visual_names_are_unique(self) -> None:
        names = [json.loads(text)["name"] for path, text in parts().items()
                 if path.endswith("visual.json")]
        self.assertEqual(len(names), len(set(names)))

    def test_the_build_is_deterministic(self) -> None:
        self.assertEqual(parts(), parts())

    def test_the_model_is_referenced_by_id_not_by_name_alone(self) -> None:
        pbir = json.loads(parts()["definition.pbir"])
        connection = pbir["datasetReference"]["byConnection"]["connectionString"]
        self.assertIn("semanticmodelid=", connection)


if __name__ == "__main__":
    unittest.main(verbosity=2)
