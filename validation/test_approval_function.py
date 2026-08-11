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
import json
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
):
    return {
        "defect": defect,
        "open_approvals": open_approvals,
        "question_known": question_known,
        "latest_run": latest_run,
        "queue": list(queue),
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
