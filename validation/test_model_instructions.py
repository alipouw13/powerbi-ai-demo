"""Execute the model apply cell against a tabular model that deletes like the real one.

This exists because of the failure people fear most from this loop and would
notice last: opening Prep data for AI (preview) and finding the AI instructions
gone.

The instructions are one string on one property of the semantic model, so
changing them means writing the model back with `createOrReplace`. TMSL is
explicit about what that means: "omission of a read-write object is considered
a deletion". A snapshot that came back short takes the difference with it, and
every check the notebook used to run still passes, because the one thing that
was sent correctly is the instruction string itself.

So the double here is not a store that accepts a write and hands it back. It
applies TMSL's replacement rule, which means a test can hand the cell a damaged
payload and find out whether the cell notices before the model does.

The drift test cannot catch any of this. The notebook is internally consistent,
every cell compiles, and the write succeeds. What catches it is running the real
cell against something that deletes.
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import eval_harness as eh  # noqa: E402

NOTEBOOK = Path(__file__).resolve().parent.parent / "fabric" / "agent_remediate.ipynb"

MODEL_NAME = "ModelUnderTest"
WORKSPACE = "workspace-under-test"

EXISTING = (
    "This model describes coffee sales.\n"
    "Revenue means Total Net Sales.\n"
    "The data covers 2024 and 2025 only.\n"
)
LINE = "When a question does not state a time period, use all available data."


# --------------------------------------------------------------------------
# The double
# --------------------------------------------------------------------------

def a_model(*, tables=4, measures=5, entities=60, instructions=EXISTING):
    """A tabular model shaped like the real one, small enough to reason about."""
    return {
        "name": MODEL_NAME,
        "lastUpdate": "2026-08-10T19:15:10.97+00:00",
        "compatibilityLevel": 1567,
        "model": {
            "culture": "en-US",
            "tables": [
                {
                    "name": f"Table{index}",
                    "columns": [{"name": f"c{n}"} for n in range(6)],
                    "measures": [{"name": f"m{index}_{n}"} for n in range(measures)],
                    "partitions": [{"name": f"p{index}"}],
                }
                for index in range(tables)
            ],
            "relationships": [{"name": f"r{n}"} for n in range(3)],
            "roles": [{"name": "Readers"}],
            "expressions": [{"name": "DirectLake"}],
            "cultures": [{
                "name": "en-US",
                "linguisticMetadata": {
                    "contentType": "json",
                    "content": {
                        "Version": "4.2.0",
                        "Language": "en-US",
                        "Entities": {f"e{n}": {} for n in range(entities)},
                        "Relationships": {f"lr{n}": {} for n in range(entities)},
                        "Agents": {"Internal": {"Version": "1.1.0"}},
                        "CustomInstructions": instructions,
                    },
                },
            }],
        },
    }


class FakeTabularModel:
    """A model behind `get_tmsl` and `execute_tmsl`, with TMSL's delete rule.

    `execute_tmsl` replaces the database with exactly what it was given. That
    is not a shortcut in the double, it is the documented behaviour, and it is
    the whole reason the cell has to check what it is about to send.
    """

    def __init__(self, state=None, *, moves_last_update=True, drops_a_table=False):
        self.state = state if state is not None else a_model()
        self.moves_last_update = moves_last_update
        self.drops_a_table = drops_a_table
        self.writes: list[dict] = []
        self.clock = 0

    def get_tmsl(self, name, workspace=None):  # noqa: ARG002
        return json.dumps(self.state)

    def execute_tmsl(self, script=None, workspace=None):  # noqa: ARG002
        command = json.loads(script)["createOrReplace"]
        if set(command["object"]) != {"database"}:
            raise AssertionError(
                f"unexpected TMSL object scope {command['object']}; the double "
                "only models a whole-database replace"
            )
        replacement = copy.deepcopy(command["database"])

        # A server that loses something on the round trip. Nothing about the
        # request says so, and the instruction still reads back perfectly.
        if self.drops_a_table:
            replacement["model"]["tables"] = replacement["model"]["tables"][:-1]

        self.clock += 1
        if self.moves_last_update:
            replacement["lastUpdate"] = f"2026-08-21T12:00:0{self.clock}+00:00"
        else:
            replacement["lastUpdate"] = self.state.get("lastUpdate")

        self.state = replacement
        self.writes.append(replacement)

    # -- readers used by the assertions -----------------------------------

    @property
    def instructions(self):
        blob = self.state["model"]["cultures"][0]["linguisticMetadata"]["content"]
        return blob.get("CustomInstructions", "")

    @property
    def census(self):
        return eh.model_census(self.state)


class CapturingOpen:
    """`open` for the one path the cell writes, keeping what it was given."""

    def __init__(self):
        self.files: dict[str, list[str]] = {}

    def __call__(self, path, mode="r", encoding=None):  # noqa: ARG002
        chunks: list[str] = []
        self.files[path] = chunks
        capture = self

        class Handle:
            @staticmethod
            def write(text):
                chunks.append(text)

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        capture.last = path
        return Handle()

    def contents(self, path):
        return "".join(self.files[path])


# --------------------------------------------------------------------------
# Getting the real cells out of the generated notebook
# --------------------------------------------------------------------------

def cell_containing(marker: str) -> str:
    cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    sources = ["".join(c["source"]) for c in cells if c["cell_type"] == "code"]
    found = [s for s in sources if marker in s]
    if len(found) != 1:
        raise AssertionError(
            f"expected exactly one code cell containing {marker!r}, "
            f"found {len(found)}"
        )
    return found[0]


def diff_cell() -> str:
    return cell_containing("WILL ADD for")


def apply_cell() -> str:
    return cell_containing("execute_tmsl")


def approval(question_id, instruction=LINE):
    return {
        "approval_id": f"approval-for-{question_id}",
        "question_id": question_id,
        "instruction_target": "semantic_model",
        "proposed_instruction": instruction,
        "approved_by": "alice@example.com",
    }


def run(server, pending, *, dry_run=False, damage=None, opener=None):
    """Read, diff and apply, exactly as the notebook does, and hand back its state.

    `damage` mutates the in-session snapshot between the read and the write,
    which is how a lossy read or a stray mutation would present.
    """
    model_script = json.loads(server.get_tmsl(MODEL_NAME, workspace=WORKSPACE))
    culture = model_script["model"]["cultures"][0]
    content = culture["linguisticMetadata"]["content"]

    namespace = {
        "json": json,
        "fabric": server,
        "merge_instruction": eh.merge_instruction,
        "assert_append_only": eh.assert_append_only,
        "model_census": eh.model_census,
        "census_losses": eh.census_losses,
        "pending": pending,
        "current": content.get("CustomInstructions", ""),
        "model_script": model_script,
        "content": content,
        "last_update_before": model_script.get("lastUpdate"),
        "before_census": eh.model_census(model_script),
        "executing_identity": "runner@example.com",
        "DRY_RUN": dry_run,
        "SEMANTIC_MODEL_NAME": MODEL_NAME,
        "WORKSPACE_ID": WORKSPACE,
    }

    exec(compile(diff_cell(), "<diff_cell>", "exec"), namespace)  # noqa: S102

    if damage is not None:
        damage(model_script)

    opener = opener or CapturingOpen()
    with mock.patch("os.makedirs"), mock.patch("builtins.open", opener):
        exec(compile(apply_cell(), "<apply_cell>", "exec"), namespace)  # noqa: S102

    namespace["_opener"] = opener
    return namespace


# --------------------------------------------------------------------------
# The tests
# --------------------------------------------------------------------------

class TestANormalRemediation(unittest.TestCase):
    """The happy path has to keep working, or the guards are just an outage."""

    def test_the_instruction_is_appended(self) -> None:
        server = FakeTabularModel()
        run(server, [approval("Q10")])
        self.assertIn(LINE, server.instructions)
        self.assertTrue(server.instructions.startswith(EXISTING.rstrip()))

    def test_nothing_else_changes(self) -> None:
        server = FakeTabularModel()
        before = server.census
        run(server, [approval("Q10")])
        self.assertEqual(eh.census_losses(before, server.census), {})

    def test_it_reports_persisted(self) -> None:
        server = FakeTabularModel()
        namespace = run(server, [approval("Q10")])
        self.assertTrue(namespace["persisted"])
        self.assertEqual(len(server.writes), 1)

    def test_the_backup_holds_the_instructions_as_they_were(self) -> None:
        # A backup taken after the change would restore the damage. The whole
        # point of the file is that it is the state to go back to.
        server = FakeTabularModel()
        namespace = run(server, [approval("Q10")])
        opener = namespace["_opener"]
        backed_up = json.loads(opener.contents(namespace["backup_path"]))
        blob = backed_up["model"]["cultures"][0]["linguisticMetadata"]["content"]
        self.assertEqual(blob["CustomInstructions"], EXISTING)
        self.assertNotIn(LINE, blob["CustomInstructions"])
        # and it is the whole model, not just the property
        self.assertEqual(eh.model_census(backed_up), server.census)

    def test_an_instruction_already_there_writes_nothing(self) -> None:
        server = FakeTabularModel(a_model(instructions=EXISTING + "\n" + LINE + "\n"))
        namespace = run(server, [approval("Q10")])
        self.assertEqual(server.writes, [])
        self.assertEqual(namespace["already_present"], [approval("Q10")])

    def test_a_dry_run_writes_nothing(self) -> None:
        server = FakeTabularModel()
        namespace = run(server, [approval("Q10")], dry_run=True)
        self.assertEqual(server.writes, [])
        self.assertFalse(namespace["persisted"])
        self.assertNotIn(LINE, server.instructions)


class TestTheModelCannotBeEmptied(unittest.TestCase):
    """The refusals. Each one is a way the instructions could have vanished."""

    def test_a_payload_that_lost_a_table_is_refused(self) -> None:
        server = FakeTabularModel()
        before = server.census

        def lose_a_table(script):
            script["model"]["tables"].pop()

        with self.assertRaises(RuntimeError) as caught:
            run(server, [approval("Q10")], damage=lose_a_table)

        self.assertIn("missing objects the model still has", str(caught.exception))
        self.assertIn("tables", str(caught.exception))
        self.assertEqual(server.writes, [], "nothing may reach the model")
        self.assertEqual(server.census, before)

    def test_a_payload_that_lost_the_q_and_a_terms_is_refused(self) -> None:
        # Synonyms are the part of AI readiness that no count of tables would
        # notice going missing, and losing them silently degrades every
        # Copilot answer without breaking anything.
        server = FakeTabularModel()

        def lose_the_synonyms(script):
            blob = script["model"]["cultures"][0]["linguisticMetadata"]["content"]
            blob["Entities"] = {}

        with self.assertRaises(RuntimeError) as caught:
            run(server, [approval("Q10")], damage=lose_the_synonyms)

        self.assertIn("linguistic_entities", str(caught.exception))
        self.assertEqual(server.writes, [])

    def test_a_payload_that_lost_the_measures_is_refused(self) -> None:
        server = FakeTabularModel()

        def lose_the_measures(script):
            for table in script["model"]["tables"]:
                table["measures"] = []

        with self.assertRaises(RuntimeError):
            run(server, [approval("Q10")], damage=lose_the_measures)
        self.assertEqual(server.writes, [])

    def test_a_short_read_cannot_replace_the_instructions(self) -> None:
        # The failure the person who reported this was afraid of: a read that
        # came back empty, then a write that leaves one approved sentence
        # where a page of hand-written guidance used to be. It is refused
        # during the diff, before a backup is even taken.
        server = FakeTabularModel()
        model_script = json.loads(server.get_tmsl(MODEL_NAME))
        namespace = {
            "merge_instruction": eh.merge_instruction,
            "assert_append_only": eh.assert_append_only,
            "pending": [approval("Q10")],
            "current": "",  # what a read that could not see the model returns
        }
        exec(compile(diff_cell(), "<diff_cell>", "exec"), namespace)  # noqa: S102
        # The diff itself is fine; the guard is what refuses, once the real
        # text is what it is being compared against.
        with self.assertRaises(ValueError) as caught:
            eh.assert_append_only(
                model_script["model"]["cultures"][0]["linguisticMetadata"]
                ["content"]["CustomInstructions"],
                namespace["proposed"],
            )
        self.assertIn("do not contain the current ones", str(caught.exception))

    def test_the_diff_cell_refuses_a_shrinking_write(self) -> None:
        namespace = {
            "merge_instruction": lambda existing, instruction: ("Just this.", True),
            "assert_append_only": eh.assert_append_only,
            "pending": [approval("Q10")],
            "current": EXISTING,
        }
        with self.assertRaises(ValueError):
            exec(compile(diff_cell(), "<diff_cell>", "exec"), namespace)  # noqa: S102


class TestAWriteThatLandsBadly(unittest.TestCase):
    """Refusals for damage that only exists after the write has happened."""

    def test_a_server_that_drops_a_table_is_caught(self) -> None:
        server = FakeTabularModel(drops_a_table=True)
        with self.assertRaises(RuntimeError) as caught:
            run(server, [approval("Q10")])
        message = str(caught.exception)
        self.assertIn("lost objects", message)
        self.assertIn("model_backups", message, "it has to say what to restore")
        # The instruction did land, which is exactly why the old check passed.
        self.assertIn(LINE, server.instructions)

    def test_a_write_that_never_reached_the_server_is_caught(self) -> None:
        server = FakeTabularModel(moves_last_update=False)
        with self.assertRaises(RuntimeError) as caught:
            run(server, [approval("Q10")])
        self.assertIn("did not reach the model", str(caught.exception))

    def test_a_concurrent_change_is_refused(self) -> None:
        server = FakeTabularModel()

        def somebody_else_edits(_script):
            server.state = copy.deepcopy(server.state)
            server.state["lastUpdate"] = "2026-08-21T13:00:00+00:00"

        with self.assertRaises(RuntimeError) as caught:
            run(server, [approval("Q10")], damage=somebody_else_edits)
        self.assertIn("changed while this run was preparing", str(caught.exception))
        self.assertEqual(server.writes, [])


class TestTheGuardsWouldHaveCaughtTheOriginalFear(unittest.TestCase):
    """Guarding the guards, so a later edit cannot quietly remove them."""

    def test_the_apply_cell_checks_the_payload_before_writing(self) -> None:
        source = apply_cell()
        before_write, _, after_write = source.partition("fabric.execute_tmsl")
        self.assertIn("census_losses", before_write,
                      "the payload has to be checked before it is sent")
        self.assertIn("census_losses", after_write,
                      "and the result has to be checked after")

    def test_the_diff_cell_asserts_append_only(self) -> None:
        self.assertIn("assert_append_only(current, proposed)", diff_cell())

    def test_the_backup_precedes_the_write(self) -> None:
        source = apply_cell()
        self.assertLess(
            source.index("backup written"),
            source.index("fabric.execute_tmsl"),
            "a backup taken after the write is not a restore point",
        )


if __name__ == "__main__":
    unittest.main()
