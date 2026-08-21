"""Execute the agent apply cell against a data agent that behaves like the real one.

This exists because of a failure that every other kind of test missed.

Two instructions were approved for the data agent. The remediation ran, the
report showed them as decided, and the agent's instructions were unchanged.
Nothing errored anywhere a person would look.

The cause was two APIs that look interchangeable and are not:

* Writing `aiInstructions` PATCHes the **staging** configuration through the
  public Fabric API. Staging is a draft. Nothing queries it. The published
  configuration only changes when something calls the publish endpoint.
* `get_configuration()` is the deprecated workload-host API and reads
  `additionalInstructions` from a different plane again.

So the notebook wrote a draft it then failed to read back, raised, and its
caller swallowed the exception and printed a line among fifty.

A drift test cannot catch that: the notebook was internally consistent and
every cell compiled. What catches it is running the cell against a double that
keeps staging and published apart, exactly as the service does. These tests
fail against the old code and pass against the new.

The double follows the public Fabric REST API the notebook now calls directly:
`GET|PATCH /dataAgents/{id}/staging/settings`, `POST /dataAgents/{id}/staging/publish`
and `GET /dataAgents/{id}/settings` for the published configuration.

It used to double `fabric.dataagent.client.FabricDataAgentManagement`. The SDK
is gone: installing it at run time cancelled the notebook's Spark session in
ten seconds, before a line of its own code ran, on the first agent-targeted
approval that ever reached it.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

AGENT_NOTEBOOK = (
    Path(__file__).resolve().parent.parent / "fabric" / "agent_remediate_agent.ipynb"
)

WORKSPACE = "workspace-under-test"
AGENT_ID = "agent-under-test"
BASE = (f"https://api.fabric.microsoft.com/v1/workspaces/{WORKSPACE}"
        f"/dataAgents/{AGENT_ID}")

SENTENCE = (
    "When you answer a question that groups a figure, name every group "
    "alongside its value."
)
OTHER = "Name the measure you used when you give a figure."


# --------------------------------------------------------------------------
# The double
# --------------------------------------------------------------------------

class FakeAgent:
    """A data agent with a staging draft and a published configuration.

    The two are separate on purpose. That separation is the entire bug, and a
    double that collapsed them would pass whatever the notebook did.
    """

    def __init__(self, staging=None, published=None, *, publishes=True,
                 has_published_settings=True):
        self.staging = staging
        self.published = published
        self.publishes = publishes
        self.has_published_settings = has_published_settings
        self.patches = []
        self.publish_calls = []

    def handle(self, method, url, body):
        """Answer one request the way the service does, status code and all."""
        path = url[len(BASE):] if url.startswith(BASE) else url

        if method == "GET" and path == "/staging/settings":
            return 200, ({} if self.staging is None
                         else {"aiInstructions": self.staging})

        if method == "GET" and path == "/settings":
            if not self.has_published_settings:
                # What a never-published agent actually does, rather than an
                # empty body that would read as "no instructions".
                return 404, {"error": "this data agent has never been published"}
            return 200, ({} if self.published is None
                         else {"aiInstructions": self.published})

        if method == "PATCH" and path == "/staging/settings":
            self.patches.append(body.get("aiInstructions"))
            self.staging = body.get("aiInstructions")
            return 200, {"aiInstructions": self.staging}

        if method == "POST" and path == "/staging/publish":
            self.publish_calls.append(body.get("publishedDescription"))
            if self.publishes:
                self.published = self.staging
                # A published agent has published settings, so this stops
                # being a never-published one the moment the publish succeeds.
                self.has_published_settings = True
            return 200, {"publishedDescription": body.get("publishedDescription")}

        return 404, {"error": f"no route for {method} {path}"}


class FakeHTTPError(Exception):
    """urllib.error.HTTPError, as far as the cell can tell."""

    def __init__(self, code, payload):
        super().__init__(f"HTTP {code}")
        self.code = code
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class FakeRequest:
    def __init__(self, url, data=None, method="GET", headers=None):
        self.url = url
        self.data = data
        self.method = method
        self.headers = headers or {}


class FakeUrllib:
    """Stands in for the `urllib` the notebook imports in an earlier cell.

    The cell reaches `urllib.request.Request`, `urllib.request.urlopen` and
    `urllib.error.HTTPError`, so those are the only three that need to exist.
    """

    def __init__(self, agent):
        self.agent = agent

        transport = self

        class _Request:
            request_class = FakeRequest

            @staticmethod
            def Request(url, data=None, method="GET", headers=None):  # noqa: N802
                return FakeRequest(url, data, method, headers)

            @staticmethod
            def urlopen(request, timeout=None):  # noqa: ARG004
                body = json.loads(request.data.decode("utf-8")) if request.data else None
                status, payload = transport.agent.handle(
                    request.method, request.url, body or {}
                )
                if status >= 400:
                    raise FakeHTTPError(status, payload)
                return FakeResponse(status, payload)

        class _Error:
            HTTPError = FakeHTTPError

        self.request = _Request
        self.error = _Error


class FakeNotebookutils:
    class credentials:  # noqa: N801
        @staticmethod
        def getToken(_audience):  # noqa: N802
            return "token-under-test"


def apply_cell() -> str:
    """The generated cell that writes to the agent, straight from the notebook."""
    cells = json.loads(AGENT_NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    sources = ["".join(c["source"]) for c in cells if c["cell_type"] == "code"]
    found = [s for s in sources if "/staging/publish" in s]
    if len(found) != 1:
        raise AssertionError(
            f"expected exactly one cell that writes to the agent, found {len(found)}"
        )
    return found[0]


def approval(question_id, instruction=SENTENCE):
    return {
        "approval_id": f"approval-for-{question_id}",
        "question_id": question_id,
        "instruction_target": "data_agent",
        "proposed_instruction": instruction,
        "approved_by": "alice@example.com",
    }


def _refusing(agent, method, path, status):
    """The agent's own routing, except one route answers with an error.

    Read access without write access is the permission shape this loop is
    most likely to meet in a real tenant, and it is invisible unless it is
    tested: the service returns a status code rather than raising.
    """
    original = agent.handle

    def handle(request_method, url, body):
        if request_method == method and url.endswith(path):
            return status, {"error": f"{method} {path} refused"}
        return original(request_method, url, body)

    return handle


def run(agent, pending, dry_run=False):
    """Execute the apply cell against the fake service, and return its namespace."""
    namespace = {
        "json": json,
        "urllib": FakeUrllib(agent),
        "notebookutils": FakeNotebookutils,
        "pending": pending,
        "DRY_RUN": dry_run,
        "APPROVED_BY": "alice@example.com",
        "WORKSPACE_ID": WORKSPACE,
        "DATA_AGENT_NAME": "Contoso Coffee agent",
        "DATA_AGENT_ID": AGENT_ID,
    }
    exec(compile(apply_cell(), "<apply_cell>", "exec"), namespace)  # noqa: S102
    return namespace


# --------------------------------------------------------------------------
# The tests
# --------------------------------------------------------------------------

class TestTheInstructionReachesThePublishedAgent(unittest.TestCase):
    """The failure that started this: approved, recorded, and not there."""

    def test_an_approved_sentence_ends_up_in_the_published_configuration(self) -> None:
        agent = FakeAgent(staging="", published="")
        run(agent, [approval("Q11")])
        self.assertIn(SENTENCE, agent.published)

    def test_writing_staging_alone_is_not_enough(self) -> None:
        """The whole bug in one assertion.

        The staging PATCH changes a draft. A run that stopped there would
        leave the agent people query exactly as it was, while the loop
        recorded the instruction as applied.
        """
        agent = FakeAgent(staging="", published="")
        run(agent, [approval("Q11")])
        self.assertEqual(len(agent.publish_calls), 1)
        self.assertEqual(agent.staging, agent.published)

    def test_the_publish_names_who_approved_it(self) -> None:
        agent = FakeAgent(staging="", published="")
        run(agent, [approval("Q11")])
        self.assertIn("alice@example.com", agent.publish_calls[0])

    def test_it_appends_rather_than_replacing_what_a_person_wrote(self) -> None:
        agent = FakeAgent(staging="Answer in British English.",
                          published="Answer in British English.")
        run(agent, [approval("Q11")])
        self.assertIn("Answer in British English.", agent.published)
        self.assertIn(SENTENCE, agent.published)

    def test_two_approvals_both_land(self) -> None:
        agent = FakeAgent(staging="", published="")
        namespace = run(agent, [approval("Q11"), approval("Q08", OTHER)])
        self.assertIn(SENTENCE, agent.published)
        self.assertIn(OTHER, agent.published)
        self.assertEqual(len(namespace["applied"]), 2)


class TestItRefusesToClaimAChangeItDidNotMake(unittest.TestCase):
    """The other half of the failure: a no-op reported as success."""

    def test_a_publish_that_does_nothing_is_an_error(self) -> None:
        """The shape of "can read the agent, cannot write it".

        A silent no-op is the one outcome that must never be recorded as a
        fix, because the report would then show a change that never happened
        and the next evaluation would be blamed for not improving.
        """
        agent = FakeAgent(staging="", published="", publishes=False)
        with self.assertRaises(RuntimeError) as caught:
            run(agent, [approval("Q11")])
        self.assertIn("did not carry every approved instruction",
                      str(caught.exception))

    def test_it_refuses_when_staging_cannot_be_read(self) -> None:
        """The staging PATCH replaces the whole value.

        Writing without a reliable read would delete whatever a person wrote
        by hand, so this refuses instead.
        """
        agent = FakeAgent(staging=None, published="")
        with self.assertRaises(ValueError) as caught:
            run(agent, [approval("Q11")])
        self.assertIn("Could not read the agent's staging settings",
                      str(caught.exception))
        self.assertEqual(agent.patches, [])

    def test_a_rejected_write_is_not_recorded_as_applied(self) -> None:
        """403 is the shape of "can read the agent, cannot write it".

        urllib raises on a 4xx, and an unhandled raise here would reach the
        caller's handoff and be swallowed the same way the original bug was.
        """
        agent = FakeAgent(staging="", published="")
        agent.handle = _refusing(agent, "PATCH", "/staging/settings", 403)
        with self.assertRaises(RuntimeError) as caught:
            run(agent, [approval("Q11")])
        self.assertIn("returned 403", str(caught.exception))
        self.assertEqual(agent.published, "")

    def test_a_rejected_publish_is_not_recorded_as_applied(self) -> None:
        """The write can succeed and the publish still be refused.

        That leaves the sentence in a draft nobody queries, which is the
        state this whole notebook exists to stop being reported as a fix.
        """
        agent = FakeAgent(staging="", published="")
        agent.handle = _refusing(agent, "POST", "/staging/publish", 403)
        with self.assertRaises(RuntimeError) as caught:
            run(agent, [approval("Q11")])
        self.assertIn("returned 403", str(caught.exception))
        self.assertEqual(agent.published, "")

    def test_an_agent_with_no_instructions_yet_is_not_unreadable(self) -> None:
        """Empty is a fact about the agent. Unreadable is a failure.

        Confusing the two would make the first ever remediation refuse.
        """
        agent = FakeAgent(staging="", published=None,
                          has_published_settings=False)
        run(agent, [approval("Q11")])
        self.assertIn(SENTENCE, agent.published)


class TestItDoesNotApplyWhatIsAlreadyThere(unittest.TestCase):
    """Re-applying an applied instruction is a duplicate line, not a fix."""

    def test_a_published_sentence_is_not_written_again(self) -> None:
        published = f"## Automated remediation\n\n{SENTENCE}\n"
        agent = FakeAgent(staging=published, published=published)
        namespace = run(agent, [approval("Q11")])
        self.assertEqual(agent.patches, [])
        self.assertEqual(agent.publish_calls, [])
        self.assertEqual(namespace["applied"], [])
        self.assertEqual(len(namespace["already_present"]), 1)

    def test_it_does_not_duplicate_the_line(self) -> None:
        published = f"## Automated remediation\n\n{SENTENCE}\n"
        agent = FakeAgent(staging=published, published=published)
        run(agent, [approval("Q11")])
        self.assertEqual(agent.published.count(SENTENCE), 1)

    def test_a_group_sharing_one_sentence_writes_it_once(self) -> None:
        """What bulk approval relies on being true.

        Four questions, one sentence. The agent gets one line.
        """
        agent = FakeAgent(staging="", published="")
        run(agent, [approval(q) for q in ("Q11", "Q12", "Q14", "Q15")])
        self.assertEqual(agent.published.count(SENTENCE), 1)

    def test_a_sentence_stuck_in_staging_is_published_without_a_second_patch(self) -> None:
        """Recovery from the state this bug leaves behind.

        Every run before the fix wrote staging and never published. Those
        agents have the text in the draft and not in the published copy, and
        the right response is to publish rather than to append it twice.
        """
        agent = FakeAgent(staging=f"## Automated remediation\n\n{SENTENCE}\n",
                          published="")
        run(agent, [approval("Q11")])
        self.assertEqual(agent.patches, [])
        self.assertEqual(len(agent.publish_calls), 1)
        self.assertIn(SENTENCE, agent.published)
        self.assertEqual(agent.published.count(SENTENCE), 1)


class TestDryRun(unittest.TestCase):
    def test_a_dry_run_writes_nothing_and_publishes_nothing(self) -> None:
        agent = FakeAgent(staging="", published="")
        run(agent, [approval("Q11")], dry_run=True)
        self.assertEqual(agent.patches, [])
        self.assertEqual(agent.publish_calls, [])
        self.assertEqual(agent.published, "")

    def test_nothing_pending_touches_nothing(self) -> None:
        agent = FakeAgent(staging="", published="")
        namespace = run(agent, [])
        self.assertEqual(agent.patches, [])
        self.assertEqual(agent.publish_calls, [])
        self.assertEqual(namespace["applied"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
