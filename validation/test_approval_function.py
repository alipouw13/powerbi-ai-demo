"""The approval function: drift, and the trust boundary.

The function is generated, so the committed copy can rot exactly like the
notebooks can. It also carries the property no flow can: `approved_by` and
`created_by` are read from the caller's verified token rather than passed in.

The function cannot be imported directly, because it imports
`fabric.functions`, which only exists in the Fabric runtime. So it is executed
against a stub with a fake SQL connection, which proves the code *runs* rather
than merely parses, and lets the guards be tested for real.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import re
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_approval_function as builder  # noqa: E402

FUNCTION_APP = builder.FUNCTION_DIR / "function_app.py"


class UserThrownError(Exception):
    """Stands in for fn.UserThrownError."""

    def __init__(self, message, properties=None):
        super().__init__(message)
        self.message = message
        self.properties = properties or {}


# --------------------------------------------------------------------------
# A fake SQL connection
# --------------------------------------------------------------------------

class FakeCursor:
    """Answers the queries the function asks, and records what it writes.

    Deliberately dumb: it matches on a fragment of each statement rather than
    parsing SQL. A test double that understood SQL would be a second
    implementation to get wrong.
    """

    def __init__(self, state):
        self.state = state
        self._result = None

    def execute(self, statement, *parameters):
        self.state["statements"].append((statement, parameters))
        normalised = " ".join(statement.split())

        if normalised.startswith("SELECT TOP 1 d.proposed_instruction"):
            self._result = self.state["defect"]
        elif normalised.startswith("SELECT TOP 1 approval_id"):
            # Keyed by the decision asked for. Approving a group follows a
            # prior approval; rejecting one follows a prior rejection.
            self._result = self.state["decided_already"].get(parameters[1])
        elif "FROM dbo.similar_fixes" in normalised:
            self._result = list(self.state["siblings"])
        elif "FROM dbo.open_approvals" in normalised:
            self._result = (self.state["open_approvals"],)
        elif "FROM dbo.questions" in normalised:
            self._result = (1 if self.state["question_known"] else 0,)
        elif normalised.startswith("SELECT TOP 1 run_id"):
            self._result = self.state["latest_run"]
        elif "FROM dbo.remediation_queue" in normalised:
            self._result = self.state["queue"]
        elif normalised.startswith("INSERT INTO"):
            self.state["writes"].append((normalised, parameters))
            self._result = None
        else:
            raise AssertionError(f"unexpected statement: {normalised[:120]}")

    def fetchone(self):
        return self._result

    def fetchall(self):
        return self._result or []

    def close(self):
        self.state["cursor_closed"] = True


class FakeConnection:
    def __init__(self, state):
        self.state = state

    def cursor(self):
        return FakeCursor(self.state)

    def commit(self):
        self.state["committed"] = True

    def close(self):
        self.state["closed"] = True


class FakeSqlDb:
    def __init__(self, state):
        self.state = state

    def connect(self):
        return FakeConnection(self.state)


def sql_state(
    *,
    defect=("Answer using all available data.", "semantic_model", 1, True),
    open_approvals=0,
    question_known=True,
    latest_run=("run-under-test",),
    queue=(),
    siblings=(),
    decided_already=None,
):
    return {
        "defect": defect,
        "open_approvals": open_approvals,
        "question_known": question_known,
        "latest_run": latest_run,
        "queue": list(queue),
        # (question, status, target, instruction), as dbo.similar_fixes returns
        # the group a question belongs to.
        "siblings": list(siblings),
        # What the covering question has already been decided as, keyed by
        # decision, because approving a group and rejecting one follow
        # different prior decisions.
        "decided_already": dict(decided_already or {}),
        "statements": [],
        "writes": [],
        "committed": False,
        "closed": False,
        "cursor_closed": False,
    }


def load_module(source: str | None = None) -> types.ModuleType:
    """Execute function_app.py with `fabric.functions` stubbed out."""
    source = source if source is not None else FUNCTION_APP.read_text(encoding="utf-8")

    def passthrough(*_args, **_kwargs):
        return lambda function: function

    fabric_functions = types.SimpleNamespace(
        UserDataFunctions=lambda: types.SimpleNamespace(
            function=passthrough,
            context=passthrough,
            connection=passthrough,
            generic_connection=passthrough,
        ),
        UserThrownError=UserThrownError,
        FabricItem=object,
        FabricSqlConnection=object,
        UserDataFunctionContext=object,
    )
    fabric = types.ModuleType("fabric")
    fabric.functions = fabric_functions

    saved = {name: sys.modules.get(name) for name in ("fabric", "fabric.functions")}
    sys.modules["fabric"] = fabric
    sys.modules["fabric.functions"] = fabric_functions
    try:
        module = types.ModuleType("function_app_under_test")
        exec(compile(source, "function_app.py", "exec"), module.__dict__)  # noqa: S102
        return module
    finally:
        for name, value in saved.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


class Invocation:
    """A UserDataFunctionContext as the platform would supply it.

    The oid is not GUID shaped on purpose. A real one is, but a GUID in a
    committed file trips test_no_secrets, and weakening that check to allow a
    fixture would be the wrong trade.
    """

    def __init__(self, username="admin@example.com", oid="oid-for-admin"):
        self.invocation_id = "invocation-under-test"
        self.executing_user = {}
        if username:
            self.executing_user["PreferredUsername"] = username
        if oid:
            self.executing_user["Oid"] = oid


def written(state, table):
    return [p for s, p in state["writes"] if f"INSERT INTO dbo.{table}" in s]


class TestGeneratedFileIsCurrent(unittest.TestCase):
    def test_it_exists(self) -> None:
        self.assertTrue(FUNCTION_APP.exists(),
                        "run python validation/build_approval_function.py")

    def test_no_drift(self) -> None:
        self.assertEqual(
            FUNCTION_APP.read_text(encoding="utf-8"),
            builder.build_function_app(),
            "fabric/approve_remediation/function_app.py is stale. Regenerate it.",
        )

    def test_definition_parts_are_current(self) -> None:
        for name, expected in (
            ("definition.json", builder.build_definition_json()),
            ("resources/functions.json", builder.build_functions_json()),
        ):
            with self.subTest(part=name):
                path = builder.FUNCTION_DIR / name
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), expected)

    def test_it_compiles(self) -> None:
        ast.parse(FUNCTION_APP.read_text(encoding="utf-8"))

    def test_it_carries_no_tenant_values(self) -> None:
        # The SQL alias is a connection name, not an identifier. Nothing else
        # about a deployment appears in the source at all now, which is a
        # property the Key Vault version did not have.
        source = FUNCTION_APP.read_text(encoding="utf-8")
        for forbidden in ("kusto", "vault.azure.net", "login.microsoftonline.com",
                          "client_secret", "CLIENT_ID", "TENANT_ID"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_the_key_vault_dependency_is_gone(self) -> None:
        # The whole point of moving the store to SQL.
        libraries = {
            lib["name"] for lib in builder.build_definition_json()["libraries"]["public"]
        }
        self.assertNotIn("azure-keyvault-secrets", libraries)
        for entry in builder.build_functions_json()["functionsMetadata"]:
            audiences = {b.get("audienceType") for b in entry["bindings"]}
            with self.subTest(function=entry["name"]):
                self.assertNotIn("KeyVault", audiences)


class TestTheManagedConnectionSurvivesADeploy(unittest.TestCase):
    """The guard that was missing, and what its absence cost.

    `connectedDataSources` carries a `dmtsConnectionId`, a tenant object
    created when a person picks the database under Manage connections. It
    cannot be generated, so the builder emits an empty list.

    `updateDefinition` replaces the whole definition, so deploying without a
    carry-over **deletes the connection**. Every function that takes `sqlDb`
    then fails with "Unable to load data successfully for fabric item", the
    report says only that the request could not be submitted, and the item
    looks perfectly healthy.

    This is the same failure the report builder already guards against with
    `carry_over_button_action`: a deploy silently destroying the one part of
    an item a person had to configure by hand.
    """

    # Deliberately not GUID shaped. A real connection carries GUIDs, but a
    # GUID in a committed file trips test_no_secrets, and weakening that check
    # to allow a fixture would be the wrong trade. The same reasoning as the
    # Invocation oid above.
    CONNECTION = {
        "alias": builder.SQL_ALIAS,
        "artifactId": "artifact-id-under-test",
        "artifactType": "SqlDatabase",
        "dmtsConnectionId": "dmts-connection-id-under-test",
        "workspaceId": "workspace-id-under-test",
    }

    def deployed(self, sources):
        definition = builder.build_definition_json()
        definition["connectedDataSources"] = sources
        return {"definition.json": json.dumps(definition, indent=2) + "\n"}

    def fresh(self):
        return {"definition.json":
                json.dumps(builder.build_definition_json(), indent=2) + "\n"}

    def test_a_fresh_build_carries_no_connection_of_its_own(self) -> None:
        """Otherwise this whole class would pass without carrying anything."""
        definition = builder.build_definition_json()
        self.assertEqual(definition["connectedDataSources"], [])

    def test_the_connection_is_kept(self) -> None:
        parts = self.fresh()
        builder.carry_over_connections(parts, self.deployed([self.CONNECTION]))
        kept = json.loads(parts["definition.json"])["connectedDataSources"]
        self.assertEqual(kept, [self.CONNECTION])

    def test_the_dmts_id_survives_exactly(self) -> None:
        """It is the only part that cannot be reconstructed from anything."""
        parts = self.fresh()
        builder.carry_over_connections(parts, self.deployed([self.CONNECTION]))
        self.assertIn(self.CONNECTION["dmtsConnectionId"], parts["definition.json"])

    def test_carrying_over_leaves_the_rest_of_the_definition_alone(self) -> None:
        parts = self.fresh()
        builder.carry_over_connections(parts, self.deployed([self.CONNECTION]))
        after = json.loads(parts["definition.json"])
        expected = builder.build_definition_json()
        self.assertEqual(after["functions"], expected["functions"])
        self.assertEqual(after["libraries"], expected["libraries"])
        self.assertEqual(after["runtime"], expected["runtime"])

    def test_it_is_safe_on_a_first_deploy(self) -> None:
        """Nothing deployed yet, so there is nothing to keep."""
        parts = self.fresh()
        builder.carry_over_connections(parts, {})
        self.assertEqual(parts, self.fresh())

    def test_an_unreadable_deployed_item_aborts_rather_than_wiping(self) -> None:
        """Fail closed. The two failure modes look identical and are opposite.

        "No definition parts" and "the API did not answer" both arrive as an
        empty result. One is a first deploy; the other is one call away from
        deleting a working connection. `deployed_definition` raises instead,
        and `deploy` turns that into a refusal.
        """
        source = Path(builder.__file__).read_text(encoding="utf-8")
        body = source.split("def deploy(")[1].split("\ndef ")[0]
        self.assertIn("CouldNotRead", body)
        self.assertIn("raise SystemExit", body)
        self.assertIn("Nothing was deployed", body)

    def test_reading_no_parts_is_an_error_not_an_empty_answer(self) -> None:
        self.assertTrue(issubclass(builder.CouldNotRead, Exception))
        source = Path(builder.__file__).read_text(encoding="utf-8")
        body = source.split("def deployed_definition(")[1].split("\ndef ")[0]
        # Every exit from the reader that is not a successful parse has to
        # raise, or the caller cannot tell empty from broken.
        self.assertNotIn("return {}", body)
        self.assertIn('raise CouldNotRead("getDefinition returned no parts")', body)

    def test_a_flaky_platform_deploy_is_retried_once(self) -> None:
        """The platform's own function deployment step fails intermittently.

        It comes back as a bare "Azure function deployment failed with
        error:" and succeeds on the next attempt. Retrying is only safe
        because the update is atomic, which is why the retry is bounded and
        commented rather than a general-purpose loop.
        """
        self.assertTrue(issubclass(builder.DeployFailed, Exception))
        source = Path(builder.__file__).read_text(encoding="utf-8")
        body = source.split("def deploy(")[1].split("\ndef ")[0]
        self.assertIn("for attempt in (1, 2):", body)
        self.assertIn("except DeployFailed", body)
        self.assertIn("Nothing was changed", body)

    def test_a_repeated_failure_still_stops(self) -> None:
        """A retry that never gives up would hide a real breakage."""
        source = Path(builder.__file__).read_text(encoding="utf-8")
        body = source.split("def deploy(")[1].split("\ndef ")[0]
        self.assertIn("if attempt == 2:", body)
        self.assertIn("raise SystemExit", body)

    def test_it_is_safe_when_the_item_has_no_connection_yet(self) -> None:
        parts = self.fresh()
        builder.carry_over_connections(parts, self.deployed([]))
        self.assertEqual(parts, self.fresh())

    def test_unreadable_deployed_json_does_not_stop_a_deploy(self) -> None:
        parts = self.fresh()
        builder.carry_over_connections(parts, {"definition.json": "{not json"})
        self.assertEqual(parts, self.fresh())

    def test_it_warns_when_no_connection_uses_the_alias_the_code_asks_for(self) -> None:
        """A connection under the wrong alias fails exactly like none at all."""
        wrong = dict(self.CONNECTION, alias="somethingelse")
        parts = self.fresh()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            builder.carry_over_connections(parts, self.deployed([wrong]))
        self.assertIn("WARNING", stdout.getvalue())
        self.assertIn(builder.SQL_ALIAS, stdout.getvalue())

    def test_every_function_asks_for_the_same_alias(self) -> None:
        """One connection serves them all, so one alias has to serve them all."""
        source = builder.build_function_app()
        decorated = re.findall(r'@udf\.connection\(argName="sqlDb", alias="([^"]+)"\)',
                               source)
        self.assertEqual(len(decorated), len(builder.FUNCTIONS))
        self.assertEqual(set(decorated), {builder.SQL_ALIAS})

    def test_the_bindings_name_the_same_alias(self) -> None:
        for entry in builder.build_functions_json()["functionsMetadata"]:
            aliases = [b.get("alias") for b in entry["bindings"] if b.get("alias")]
            with self.subTest(function=entry["name"]):
                self.assertEqual(aliases, [builder.SQL_ALIAS])

    def test_the_carried_connection_never_reaches_the_committed_file(self) -> None:
        """It is carried in memory, on the way to the tenant, and nowhere else.

        A dmtsConnectionId and a workspaceId in a committed file would be
        exactly the tenant leak the rest of this repo works to avoid.
        """
        on_disk = json.loads(FUNCTION_APP.parent.joinpath("definition.json")
                             .read_text(encoding="utf-8"))
        self.assertEqual(on_disk["connectedDataSources"], [])
        text = FUNCTION_APP.parent.joinpath("definition.json").read_text(encoding="utf-8")
        for leak in ("dmtsConnectionId", "workspaceId", "artifactId"):
            with self.subTest(field=leak):
                self.assertNotIn(leak, text)


class TestTheConnectionAliasCanBeOverridden(unittest.TestCase):
    """Because the portal generates the alias and nothing can rename it.

    The connection is created by a portal flow that mints the alias from the
    data source's name. There is no API to create the connection, and none to
    rename it. If a tenant generates something other than the default, the
    functions fail with "Unable to load data successfully for fabric item",
    which names the function and not the cause.

    So the alias is configurable, and a deploy that finds a mismatch says
    exactly which environment variable to set.
    """

    def test_the_default_is_what_the_committed_file_carries(self) -> None:
        """A plain checkout must build byte-identically to what is committed."""
        self.assertEqual(builder.SQL_ALIAS, "agentevalsql")
        self.assertIn('alias="agentevalsql"', FUNCTION_APP.read_text(encoding="utf-8"))

    def test_the_alias_reaches_every_decorator_and_binding(self) -> None:
        """One connection serves all five functions, so one alias must too."""
        source = builder.build_function_app()
        decorated = re.findall(r'@udf\.connection\(argName="sqlDb", alias="([^"]+)"\)',
                               source)
        self.assertEqual(len(decorated), len(builder.FUNCTIONS))
        self.assertEqual(set(decorated), {builder.SQL_ALIAS})

        for entry in builder.build_functions_json()["functionsMetadata"]:
            aliases = [b.get("alias") for b in entry["bindings"] if b.get("alias")]
            with self.subTest(function=entry["name"]):
                self.assertEqual(aliases, [builder.SQL_ALIAS])

    def test_the_environment_variable_is_read(self) -> None:
        """Reloaded rather than monkeypatched, so this tests the real wiring."""
        import importlib

        saved = os.environ.get("FABRIC_SQL_ALIAS")
        os.environ["FABRIC_SQL_ALIAS"] = "generated_by_the_portal"
        try:
            import config
            importlib.reload(config)
            self.assertEqual(config.SQL_ALIAS, "generated_by_the_portal")
        finally:
            if saved is None:
                os.environ.pop("FABRIC_SQL_ALIAS", None)
            else:
                os.environ["FABRIC_SQL_ALIAS"] = saved
            import config
            importlib.reload(config)
            importlib.reload(builder)

    def test_the_default_survives_the_reload(self) -> None:
        """Guards the test above from leaving the module in a changed state."""
        self.assertEqual(builder.SQL_ALIAS, "agentevalsql")


class TestTrustBoundary(unittest.TestCase):
    """The reason to prefer a function over a flow."""

    def test_identity_is_never_a_parameter(self) -> None:
        tree = ast.parse(FUNCTION_APP.read_text(encoding="utf-8"))
        for name in ("approve_remediation", "submit_feedback"):
            function = next(
                node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == name
            )
            names = {a.arg for a in function.args.args} | {
                a.arg for a in function.args.kwonlyargs
            }
            with self.subTest(function=name):
                for forbidden in ("approved_by", "created_by", "approver", "user"):
                    self.assertNotIn(forbidden, names)

    def test_the_declared_parameters_match_the_code(self) -> None:
        declared = {
            entry["name"]: {
                p["name"] for p in entry["fabricProperties"]["fabricFunctionParameters"]
            }
            for entry in builder.build_functions_json()["functionsMetadata"]
        }
        tree = ast.parse(FUNCTION_APP.read_text(encoding="utf-8"))
        for name, expected in declared.items():
            function = next(
                node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == name
            )
            actual = {a.arg for a in function.args.args} - {"sqlDb", "invocation"}
            with self.subTest(function=name):
                self.assertEqual(actual, expected)

    def test_the_approver_comes_from_the_token(self) -> None:
        module = load_module()
        state = sql_state()
        module.approve_remediation(FakeSqlDb(state), Invocation("alice@example.com"),
                                   "Q10", "approved", "")
        self.assertIn("alice@example.com", written(state, "approvals")[0])

    def test_the_immutable_object_id_is_recorded_too(self) -> None:
        module = load_module()
        state = sql_state()
        module.approve_remediation(FakeSqlDb(state), Invocation(oid="oid-xyz"),
                                   "Q10", "approved", "")
        self.assertIn("oid-xyz", written(state, "approvals")[0])

    def test_an_unidentified_caller_is_refused(self) -> None:
        module = load_module()
        state = sql_state()
        with self.assertRaises(UserThrownError):
            module.approve_remediation(FakeSqlDb(state), Invocation("", ""),
                                       "Q10", "approved", "")
        self.assertEqual(state["writes"], [])

    def test_it_records_a_decision_and_never_applies_one(self) -> None:
        source = FUNCTION_APP.read_text(encoding="utf-8")
        for forbidden in ("RunNotebook", "jobs/instances", "execute_tmsl",
                          "CustomInstructions", "update_settings"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_no_sql_statement_is_built_from_a_value(self) -> None:
        # An f-string or a concatenation reaching execute() is how an
        # injection gets in, and the report's question slicer is free text.
        tree = ast.parse(FUNCTION_APP.read_text(encoding="utf-8"))
        checked = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "attr", None) != "execute":
                continue
            checked += 1
            statement = node.args[0]
            self.assertIsInstance(
                statement, ast.Constant,
                "SQL passed to execute() must be a literal; values go in "
                "parameters",
            )
        self.assertGreater(checked, 0, "found no execute() calls to check")


class TestApprovalGuards(unittest.TestCase):
    def test_it_writes_one_approval_and_commits(self) -> None:
        module = load_module()
        state = sql_state()
        result = module.approve_remediation(FakeSqlDb(state), Invocation(),
                                            "Q10", "approved", "looks right")
        self.assertEqual(len(written(state, "approvals")), 1)
        self.assertTrue(state["committed"])
        self.assertTrue(state["closed"])
        self.assertIn("Q10", result)

    def test_it_refuses_a_tier_two_defect(self) -> None:
        module = load_module()
        state = sql_state(defect=("", "semantic_model", 2, False))
        with self.assertRaises(UserThrownError) as caught:
            module.approve_remediation(FakeSqlDb(state), Invocation(),
                                       "Q07", "approved", "")
        self.assertIn("tier 2", str(caught.exception))
        self.assertEqual(state["writes"], [])

    def test_a_tier_two_defect_can_still_be_rejected(self) -> None:
        module = load_module()
        state = sql_state(defect=("", "semantic_model", 2, False))
        result = module.approve_remediation(FakeSqlDb(state), Invocation(),
                                            "Q07", "rejected", "")
        self.assertIn("Rejected", result)
        self.assertEqual(len(written(state, "approvals")), 1)

    def test_it_refuses_an_empty_instruction(self) -> None:
        module = load_module()
        state = sql_state(defect=("", "semantic_model", 1, True))
        with self.assertRaises(UserThrownError):
            module.approve_remediation(FakeSqlDb(state), Invocation(),
                                       "Q10", "approved", "")

    def test_it_refuses_a_second_open_approval(self) -> None:
        module = load_module()
        state = sql_state(open_approvals=1)
        with self.assertRaises(UserThrownError) as caught:
            module.approve_remediation(FakeSqlDb(state), Invocation(),
                                       "Q10", "approved", "")
        self.assertIn("already has an approval", str(caught.exception))
        self.assertEqual(state["writes"], [])

    def test_a_missing_defect_is_a_readable_error(self) -> None:
        module = load_module()
        state = sql_state(defect=None)
        with self.assertRaises(UserThrownError) as caught:
            module.approve_remediation(FakeSqlDb(state), Invocation(),
                                       "Q99", "approved", "")
        self.assertIn("Q99", str(caught.exception))

    def test_it_refuses_a_decision_it_does_not_know(self) -> None:
        module = load_module()
        state = sql_state()
        with self.assertRaises(UserThrownError):
            module.approve_remediation(FakeSqlDb(state), Invocation(),
                                       "Q10", "maybe", "")

    def test_it_refuses_an_empty_question(self) -> None:
        module = load_module()
        state = sql_state()
        with self.assertRaises(UserThrownError):
            module.approve_remediation(FakeSqlDb(state), Invocation(),
                                       "   ", "approved", "")

    def test_a_hostile_question_id_stays_in_the_parameters(self) -> None:
        module = load_module()
        state = sql_state()
        module.approve_remediation(FakeSqlDb(state), Invocation(),
                                   "Q10'; DROP TABLE dbo.approvals; --",
                                   "approved", "")
        for statement, _parameters in state["statements"]:
            with self.subTest(statement=statement[:50]):
                self.assertNotIn("DROP TABLE", statement)
        self.assertIn("Q10'; DROP TABLE DBO.APPROVALS; --",
                      written(state, "approvals")[0])

    def test_it_copies_the_sentence_rather_than_pointing_at_it(self) -> None:
        module = load_module()
        sentence = "When a question does not state a time period, use all data."
        state = sql_state(defect=(sentence, "semantic_model", 1, True))
        module.approve_remediation(FakeSqlDb(state), Invocation(),
                                   "Q10", "approved", "")
        self.assertIn(sentence, written(state, "approvals")[0])

    def test_it_carries_the_instruction_target_through(self) -> None:
        module = load_module()
        state = sql_state(defect=("Name every group.", "data_agent", 1, True))
        result = module.approve_remediation(FakeSqlDb(state), Invocation(),
                                            "Q08", "approved", "")
        self.assertIn("data_agent", written(state, "approvals")[0])
        self.assertIn("data agent instructions", result)

    def test_a_model_target_says_so_in_the_reply(self) -> None:
        module = load_module()
        state = sql_state()
        result = module.approve_remediation(FakeSqlDb(state), Invocation(),
                                            "Q10", "approved", "")
        self.assertIn("model AI instructions", result)


class TestBulkApprovalOfSimilarFixes(unittest.TestCase):
    """Approving a group is one decision, and one change.

    The harness proposes from a small library, so one wrong behaviour usually
    appears as the same sentence against several questions. Approving each of
    them separately would queue the same write four times, produce four
    identical lines in the model, and give four chances for one of them to
    fail halfway.
    """

    SENTENCE = "When a question does not state a time period, use all data."

    def group(self, *rows, decided_already=None):
        if decided_already is None:
            decided_already = {
                "approved": ("approval-for-q11", self.SENTENCE, "semantic_model"),
            }
        return sql_state(
            defect=(self.SENTENCE, "semantic_model", 1, True),
            siblings=rows,
            decided_already=decided_already,
        )

    def waiting(self, *questions):
        return [(q, "awaiting approval", "semantic_model", self.SENTENCE)
                for q in questions]

    # -- what a person is told ------------------------------------------

    def test_approving_one_names_the_others(self) -> None:
        """Said at the moment of approving, because that is when it is useful.

        Finding out later that four other questions carried the same sentence
        means four more trips through the same queue.
        """
        module = load_module()
        state = self.group(*self.waiting("Q12", "Q14"))
        result = module.approve_remediation(FakeSqlDb(state), Invocation(),
                                            "Q11", "approved", "")
        self.assertIn("Q12", result)
        self.assertIn("Q14", result)
        self.assertIn("approve_similar", result)

    def test_approving_one_says_nothing_when_the_fix_is_unique(self) -> None:
        module = load_module()
        state = self.group()
        result = module.approve_remediation(FakeSqlDb(state), Invocation(),
                                            "Q11", "approved", "")
        self.assertNotIn("approve_similar", result)

    def test_it_does_not_offer_questions_already_decided(self) -> None:
        module = load_module()
        state = self.group(
            ("Q12", "approved, not yet applied", "semantic_model", self.SENTENCE),
            *self.waiting("Q14"),
        )
        result = module.approve_remediation(FakeSqlDb(state), Invocation(),
                                            "Q11", "approved", "")
        self.assertIn("Q14", result)
        self.assertNotIn("Q12", result)

    def test_listing_shows_every_member_and_its_state(self) -> None:
        """"Three others, two already done" is not "three others, untouched"."""
        module = load_module()
        state = self.group(
            ("Q12", "applied and verified", "semantic_model", self.SENTENCE),
            *self.waiting("Q14"),
        )
        result = module.list_similar_pending(FakeSqlDb(state), Invocation(), "Q11")
        self.assertIn("Q12 (applied and verified)", result)
        self.assertIn("Q14 (awaiting approval)", result)
        self.assertIn("1 of them are still waiting", result)

    def test_listing_writes_nothing(self) -> None:
        module = load_module()
        state = self.group(*self.waiting("Q12"))
        module.list_similar_pending(FakeSqlDb(state), Invocation(), "Q11")
        self.assertEqual(state["writes"], [])

    def test_listing_a_question_with_no_group_says_so(self) -> None:
        module = load_module()
        state = self.group()
        result = module.list_similar_pending(FakeSqlDb(state), Invocation(), "Q11")
        self.assertIn("No other question", result)

    # -- what approving a group actually writes ---------------------------

    def test_it_records_a_decision_for_every_question_in_the_group(self) -> None:
        module = load_module()
        state = self.group(*self.waiting("Q12", "Q14"))
        module.approve_similar(FakeSqlDb(state), Invocation(), "Q11",
                               "approved", "same fix")
        approvals = written(state, "approvals")
        self.assertEqual(len(approvals), 2)
        self.assertIn("Q12", approvals[0])
        self.assertIn("Q14", approvals[1])
        self.assertTrue(state["committed"])

    def test_each_covered_approval_names_the_one_that_carries_the_change(self) -> None:
        module = load_module()
        state = self.group(*self.waiting("Q12"))
        module.approve_similar(FakeSqlDb(state), Invocation(), "Q11",
                               "approved", "")
        self.assertIn("approval-for-q11", written(state, "approvals")[0])

    def test_it_closes_each_covered_approval_so_nothing_is_applied_twice(self) -> None:
        """The property the whole feature rests on.

        An approval is open until a persisted remediation references it, and
        an open approval is what the notebook applies. Without the closing
        row, approving four questions would write the same sentence four
        times.
        """
        module = load_module()
        state = self.group(*self.waiting("Q12", "Q14"))
        module.approve_similar(FakeSqlDb(state), Invocation(), "Q11",
                               "approved", "")
        remediations = written(state, "remediations")
        self.assertEqual(len(remediations), 2)
        for parameters in remediations:
            with self.subTest(parameters=parameters[4]):
                # persisted, so the approval is closed and no run picks it up.
                self.assertIn(1, parameters)

    def test_a_covered_remediation_claims_no_applied_time(self) -> None:
        """It changed nothing, and the history must not say otherwise."""
        module = load_module()
        state = self.group(*self.waiting("Q12"))
        module.approve_similar(FakeSqlDb(state), Invocation(), "Q11",
                               "approved", "")
        parameters = written(state, "remediations")[0]
        # remediation_id, recorded_ts, applied_ts, ...
        self.assertIsNone(parameters[2])

    def test_a_covered_remediation_says_what_covered_it(self) -> None:
        module = load_module()
        state = self.group(*self.waiting("Q12"))
        module.approve_similar(FakeSqlDb(state), Invocation(), "Q11",
                               "approved", "")
        self.assertIn("covered by approval approval-for-q11",
                      written(state, "remediations")[0])

    # -- the guards -------------------------------------------------------

    def test_it_refuses_when_the_first_question_was_never_approved(self) -> None:
        """Otherwise a group could be approved with nothing carrying it."""
        module = load_module()
        state = sql_state(siblings=self.waiting("Q12"), decided_already={})
        with self.assertRaises(UserThrownError) as caught:
            module.approve_similar(FakeSqlDb(state), Invocation(), "Q11",
                                   "approved", "")
        self.assertIn("has not been approved", str(caught.exception))
        self.assertEqual(state["writes"], [])

    def test_approving_a_group_will_not_follow_a_rejection(self) -> None:
        """Reading a rejection as licence to approve would invent agreement."""
        module = load_module()
        state = self.group(*self.waiting("Q12"), decided_already={
            "rejected": ("approval-for-q11", self.SENTENCE, "semantic_model"),
        })
        with self.assertRaises(UserThrownError):
            module.approve_similar(FakeSqlDb(state), Invocation(), "Q11",
                                   "approved", "")
        self.assertEqual(state["writes"], [])

    def test_a_group_can_be_rejected_after_one_rejection(self) -> None:
        """Rejecting four questions one at a time is the same four clicks."""
        module = load_module()
        state = self.group(*self.waiting("Q12", "Q14"), decided_already={
            "rejected": ("approval-for-q11", self.SENTENCE, "semantic_model"),
        })
        result = module.approve_similar(FakeSqlDb(state), Invocation(), "Q11",
                                        "rejected", "not this one")
        self.assertEqual(len(written(state, "approvals")), 2)
        self.assertIn("Rejected", result)

    def test_it_writes_nothing_when_the_group_is_already_decided(self) -> None:
        module = load_module()
        state = self.group(
            ("Q12", "approved, not yet applied", "semantic_model", self.SENTENCE),
        )
        result = module.approve_similar(FakeSqlDb(state), Invocation(), "Q11",
                                        "approved", "")
        self.assertIn("Nothing to do", result)
        self.assertEqual(state["writes"], [])

    def test_rejecting_a_group_records_no_remediation(self) -> None:
        """A rejection changes nothing, so there is nothing to close."""
        module = load_module()
        state = self.group(*self.waiting("Q12", "Q14"), decided_already={
            "rejected": ("approval-for-q11", self.SENTENCE, "semantic_model"),
        })
        result = module.approve_similar(FakeSqlDb(state), Invocation(), "Q11",
                                        "rejected", "not this one")
        self.assertEqual(len(written(state, "approvals")), 2)
        self.assertEqual(written(state, "remediations"), [])
        self.assertIn("Rejected", result)

    def test_a_rejected_row_is_not_covered_by_anything(self) -> None:
        module = load_module()
        state = self.group(*self.waiting("Q12"), decided_already={
            "rejected": ("approval-for-q11", self.SENTENCE, "semantic_model"),
        })
        module.approve_similar(FakeSqlDb(state), Invocation(), "Q11",
                               "rejected", "")
        self.assertNotIn("approval-for-q11", written(state, "approvals")[0])

    def test_the_bulk_approver_also_comes_from_the_token(self) -> None:
        module = load_module()
        state = self.group(*self.waiting("Q12"))
        module.approve_similar(FakeSqlDb(state), Invocation("carol@example.com"),
                               "Q11", "approved", "")
        self.assertIn("carol@example.com", written(state, "approvals")[0])

    def test_it_refuses_a_decision_it_does_not_know(self) -> None:
        module = load_module()
        state = self.group(*self.waiting("Q12"))
        with self.assertRaises(UserThrownError):
            module.approve_similar(FakeSqlDb(state), Invocation(), "Q11",
                                   "maybe", "")
        self.assertEqual(state["writes"], [])

    def test_a_hostile_question_id_stays_in_the_parameters(self) -> None:
        module = load_module()
        state = self.group(*self.waiting("Q12"))
        module.approve_similar(FakeSqlDb(state), Invocation(),
                               "Q11'; DROP TABLE dbo.approvals; --",
                               "approved", "")
        for statement, _parameters in state["statements"]:
            with self.subTest(statement=statement[:50]):
                self.assertNotIn("DROP TABLE", statement)


class TestFeedback(unittest.TestCase):
    def test_it_records_named_feedback(self) -> None:
        module = load_module()
        state = sql_state()
        result = module.submit_feedback(FakeSqlDb(state), Invocation("bob@example.com"),
                                        "Q10", "wrong", "The regions are missing.")
        parameters = written(state, "feedback")[0]
        self.assertIn("bob@example.com", parameters)
        self.assertIn("The regions are missing.", parameters)
        self.assertIn("Q10", result)

    def test_feedback_is_never_an_approval(self) -> None:
        module = load_module()
        state = sql_state()
        module.submit_feedback(FakeSqlDb(state), Invocation(),
                               "Q10", "wrong", "Looks off.")
        self.assertEqual(written(state, "approvals"), [])
        self.assertEqual(len(written(state, "feedback")), 1)

    def test_it_lands_as_new_for_triage(self) -> None:
        module = load_module()
        state = sql_state()
        module.submit_feedback(FakeSqlDb(state), Invocation(),
                               "Q10", "wrong", "Looks off.")
        self.assertIn("new", written(state, "feedback")[0])

    def test_it_links_the_feedback_to_the_latest_run(self) -> None:
        module = load_module()
        state = sql_state(latest_run=("run-under-test",))
        module.submit_feedback(FakeSqlDb(state), Invocation(),
                               "Q10", "wrong", "Looks off.")
        self.assertIn("run-under-test", written(state, "feedback")[0])

    def test_it_survives_having_no_runs_yet(self) -> None:
        module = load_module()
        state = sql_state(latest_run=None)
        module.submit_feedback(FakeSqlDb(state), Invocation(),
                               "Q10", "wrong", "Looks off.")
        self.assertIn(None, written(state, "feedback")[0])

    def test_it_refuses_an_unknown_question(self) -> None:
        module = load_module()
        state = sql_state(question_known=False)
        with self.assertRaises(UserThrownError):
            module.submit_feedback(FakeSqlDb(state), Invocation(),
                                   "Q99", "wrong", "Looks off.")
        self.assertEqual(state["writes"], [])

    def test_it_refuses_an_empty_comment(self) -> None:
        module = load_module()
        state = sql_state()
        with self.assertRaises(UserThrownError):
            module.submit_feedback(FakeSqlDb(state), Invocation(),
                                   "Q10", "wrong", "   ")

    def test_it_refuses_a_verdict_it_does_not_know(self) -> None:
        module = load_module()
        state = sql_state()
        with self.assertRaises(UserThrownError):
            module.submit_feedback(FakeSqlDb(state), Invocation(),
                                   "Q10", "rubbish", "Looks off.")

    def test_the_reply_says_it_is_not_a_change(self) -> None:
        module = load_module()
        state = sql_state()
        result = module.submit_feedback(FakeSqlDb(state), Invocation(),
                                        "Q10", "wrong", "Looks off.")
        self.assertIn("not a change", result)


class TestQueue(unittest.TestCase):
    def test_an_empty_queue_reads_as_a_sentence(self) -> None:
        module = load_module()
        state = sql_state(queue=[])
        self.assertEqual(
            module.list_pending_remediations(FakeSqlDb(state), Invocation()),
            "Nothing is waiting for a decision.",
        )

    def test_it_names_the_target_and_the_sentence(self) -> None:
        module = load_module()
        state = sql_state(queue=[
            ("Q10", "flake", "semantic_model", True, "Use all available data."),
            ("Q07", "stable_failure", "", False, None),
        ])
        result = module.list_pending_remediations(FakeSqlDb(state), Invocation())
        self.assertIn("2 waiting", result)
        self.assertIn("approvable, semantic_model", result)
        self.assertIn("needs a person", result)
        self.assertIn("Use all available data.", result)


class TestReportButtonCompatibility(unittest.TestCase):
    """A Power BI data function button will not bind to anything else."""

    def test_every_function_returns_a_string(self) -> None:
        for entry in builder.build_functions_json()["functionsMetadata"]:
            with self.subTest(function=entry["name"]):
                self.assertEqual(
                    entry["fabricProperties"]["fabricFunctionReturnType"], "str"
                )

    def test_the_annotations_agree(self) -> None:
        tree = ast.parse(FUNCTION_APP.read_text(encoding="utf-8"))
        for name in builder.FUNCTIONS:
            function = next(
                node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == name
            )
            with self.subTest(function=name):
                self.assertEqual(getattr(function.returns, "id", None), "str")

    def test_the_public_endpoint_is_off(self) -> None:
        for entry in builder.build_definition_json()["functions"]:
            with self.subTest(function=entry["name"]):
                self.assertFalse(entry["isPublicEndpointEnabled"])

    def test_every_declared_function_is_implemented(self) -> None:
        module = load_module()
        declared = {e["name"] for e in builder.build_definition_json()["functions"]}
        self.assertEqual(declared, set(builder.FUNCTIONS))
        for name in declared:
            self.assertTrue(callable(getattr(module, name, None)))

    def test_every_function_uses_the_same_connection_alias(self) -> None:
        for entry in builder.build_functions_json()["functionsMetadata"]:
            aliases = {b.get("alias") for b in entry["bindings"] if b.get("alias")}
            with self.subTest(function=entry["name"]):
                self.assertEqual(aliases, {builder.SQL_ALIAS})

    def test_the_connection_is_closed_on_the_error_path(self) -> None:
        # A leaked connection in a function a report button calls is a slow
        # leak nobody sees until the pool is exhausted, and the error path is
        # the one that gets exercised least.
        module = load_module()
        state = sql_state(defect=None)
        with self.assertRaises(UserThrownError):
            module.approve_remediation(FakeSqlDb(state), Invocation(),
                                       "Q99", "approved", "")
        self.assertTrue(state["closed"], "the connection leaked on the error path")
        self.assertTrue(state["cursor_closed"], "the cursor leaked on the error path")


if __name__ == "__main__":
    unittest.main()
