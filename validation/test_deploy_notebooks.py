"""What the notebook deployer must never do.

Three of these are regressions that already happened once, in this workspace,
and each one was invisible at the time:

- a notebook regenerated and never deployed, so the workspace ran code that
  was not in source control and no test could see the difference
- a listing that 404'd read as "the notebooks do not exist", which very nearly
  created a second copy of every one of them
- a `getDefinition` that returns 403 on a labelled tenant read as "this
  notebook has no lakehouse", which would unbind a working notebook every
  single deploy

The fourth is the one that has not happened yet and would be worst: injecting
a value into `APPROVED_BY` or `QUESTION_ID` would ship a notebook that
remediates one fixed question as one fixed person, on every schedule, forever.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import deploy_notebooks as deployer  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


class TestParameterInjection(unittest.TestCase):
    """Which empty strings get filled, and which are none of its business."""

    FILL = {"WORKSPACE_ID": "ws-1", "KUSTO_URI": "https://k", "DATA_AGENT_ID": ""}

    def test_a_tenant_value_is_filled(self) -> None:
        self.assertEqual(
            deployer.inject(['WORKSPACE_ID = ""\n'], self.FILL),
            ['WORKSPACE_ID = "ws-1"\n'],
        )

    def test_a_trailing_comment_survives(self) -> None:
        self.assertEqual(
            deployer.inject(['KUSTO_URI = ""  # the cluster\n'], self.FILL),
            ['KUSTO_URI = "https://k"  # the cluster\n'],
        )

    def test_a_run_parameter_is_left_alone(self) -> None:
        """The ones a person fills in when they start a run.

        A deployed notebook with APPROVED_BY already set would record every
        future approval as whoever last deployed it.
        """
        for name in ("APPROVED_BY", "QUESTION_ID", "APPROVAL_IDS"):
            with self.subTest(parameter=name):
                line = f'{name} = ""\n'
                self.assertEqual(deployer.inject([line], self.FILL), [line])

    def test_an_empty_config_value_is_not_injected(self) -> None:
        """An unset variable must not overwrite anything with "".

        It is already "", so this is only a difference in intent -- but the
        moment a default is added to the committed notebook, injecting an
        empty config value would silently erase it.
        """
        self.assertEqual(
            deployer.inject(['DATA_AGENT_ID = ""\n'], self.FILL),
            ['DATA_AGENT_ID = ""\n'],
        )

    def test_a_committed_default_is_not_touched(self) -> None:
        line = 'KUSTO_DB = "EH_AgentEval"\n'
        self.assertEqual(deployer.inject([line], self.FILL), [line])

    def test_dry_run_stays_true(self) -> None:
        """The safety default. A deploy that flipped it would write on import."""
        self.assertEqual(deployer.inject(["DRY_RUN = True\n"], self.FILL),
                         ["DRY_RUN = True\n"])


class TestTheLakehouseBinding(unittest.TestCase):
    """A notebook that writes Delta tables must come out of this bound."""

    def prepare(self, name, *, deployed=None, raises=None):
        if raises is not None:
            read = mock.Mock(side_effect=raises)
        else:
            read = mock.Mock(return_value=deployed or {})
        with mock.patch.object(deployer, "deployed_notebook", read), \
                mock.patch.object(deployer, "LAKEHOUSE_ID", "lh-1"), \
                mock.patch.object(deployer, "LAKEHOUSE_NAME", "LH_ContosoCoffee"), \
                mock.patch.object(deployer, "WORKSPACE_ID", "ws-1"), \
                mock.patch.object(deployer, "require", lambda *a: None):
            return deployer.prepare(name, {name: "item-1"})

    def test_an_unreadable_item_still_gets_bound(self) -> None:
        """The 403 case, which is every deploy on a labelled tenant.

        Falling through to no binding would leave agent_eval unable to write
        eval_runs, and the failure appears an hour later inside a scheduled
        Spark job rather than here.
        """
        notebook = self.prepare(
            "agent_eval", raises=deployer.CouldNotRead("403 ItemHasProtectedLabel"))
        lakehouse = notebook["metadata"]["dependencies"]["lakehouse"]
        self.assertEqual(lakehouse["default_lakehouse"], "lh-1")

    def test_an_existing_binding_wins_over_the_default(self) -> None:
        """Somebody may have pointed it at a different lakehouse on purpose."""
        notebook = self.prepare("agent_remediate", deployed={"metadata": {
            "dependencies": {"lakehouse": {
                "default_lakehouse": "other",
                "default_lakehouse_name": "LH_Theirs"}}}})
        lakehouse = notebook["metadata"]["dependencies"]["lakehouse"]
        self.assertEqual(lakehouse["default_lakehouse"], "other")

    def test_an_empty_dependencies_block_is_not_a_binding(self) -> None:
        notebook = self.prepare("agent_eval", deployed={"metadata": {
            "dependencies": {"lakehouse": {}}}})
        lakehouse = notebook["metadata"]["dependencies"]["lakehouse"]
        self.assertEqual(lakehouse["default_lakehouse"], "lh-1")

    def test_a_notebook_that_needs_no_lakehouse_gets_none(self) -> None:
        """Binding one that does not need it is not free: it pins the
        notebook to a workspace object it never uses."""
        notebook = self.prepare("mirror_approvals")
        self.assertFalse(notebook["metadata"].get("dependencies"))

    def test_every_notebook_that_writes_delta_is_listed(self) -> None:
        """The list is hand-maintained, so check it against the source.

        A new saveAsTable in a notebook nobody added to NEEDS_LAKEHOUSE fails
        only when it runs.
        """
        for name, relative in deployer.NOTEBOOKS.items():
            source = json.loads((REPO / relative).read_text(encoding="utf-8"))
            code = "".join(
                "".join(c["source"]) for c in source["cells"]
                if c["cell_type"] == "code")
            with self.subTest(notebook=name):
                if "saveAsTable" in code:
                    self.assertIn(name, deployer.NEEDS_LAKEHOUSE)


class TestItRefusesRatherThanGuesses(unittest.TestCase):
    def test_a_failed_listing_is_not_an_empty_workspace(self) -> None:
        with mock.patch.object(deployer, "call", return_value=(404, {}, {})):
            with self.assertRaises(deployer.CouldNotRead):
                deployer.find_existing()

    def test_the_typed_route_falls_back_to_items(self) -> None:
        responses = [
            (404, {}, {}),
            (200, {"value": [
                {"displayName": "agent_eval", "id": "1", "type": "Notebook"},
                {"displayName": "LH_ContosoCoffee", "id": "2", "type": "Lakehouse"},
            ]}, {}),
        ]
        with mock.patch.object(deployer, "call", side_effect=responses):
            self.assertEqual(deployer.find_existing(), {"agent_eval": "1"})

    def test_a_missing_notebook_stops_the_deploy(self) -> None:
        """It must not create. Creating on a bad lookup is how a workspace
        ends up with two of everything and a schedule on the wrong one."""
        with mock.patch.object(deployer, "find_existing", return_value={}), \
                mock.patch.object(deployer, "token", return_value="t"), \
                mock.patch.object(deployer, "require", lambda *a: None), \
                mock.patch.object(sys, "argv", ["deploy_notebooks.py", "--deploy"]):
            with self.assertRaises(SystemExit) as caught:
                deployer.main()
        self.assertIn("will not create", str(caught.exception))

    def test_it_never_calls_the_create_route(self) -> None:
        """Belt and braces: no code path posts to the collection endpoint."""
        source = Path(deployer.__file__).read_text(encoding="utf-8")
        self.assertNotIn('"POST", f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/items"',
                         source)


class TestTheCommittedCopyStaysClean(unittest.TestCase):
    """Injection happens on a copy. The repo must never gain tenant values."""

    def test_preparing_does_not_write_the_committed_file(self) -> None:
        before = (REPO / deployer.NOTEBOOKS["agent_eval"]).read_bytes()
        with mock.patch.object(deployer, "deployed_notebook",
                               side_effect=deployer.CouldNotRead("no")), \
                mock.patch.object(deployer, "LAKEHOUSE_ID", "lh-1"), \
                mock.patch.object(deployer, "require", lambda *a: None):
            deployer.prepare("agent_eval", {"agent_eval": "item-1"})
        self.assertEqual((REPO / deployer.NOTEBOOKS["agent_eval"]).read_bytes(), before)

    def test_every_deployed_notebook_is_a_real_file(self) -> None:
        for name, relative in deployer.NOTEBOOKS.items():
            with self.subTest(notebook=name):
                self.assertTrue((REPO / relative).exists(), relative)


if __name__ == "__main__":
    unittest.main()
