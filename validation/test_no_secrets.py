"""Prove that nothing tenant specific is committed.

The repo is public and gets forked. A workspace id, a Kusto hostname, a
notebook id or a recipient address in source control is both a small
information leak and an active hazard: a notebook that already points at
somebody's workspace will happily run against it on import.

These tests are deliberately blunt. They scan the committed tree for the
shapes of the things that must not be there, rather than for a known list of
values, so that a new id pasted in next month is caught too.

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

ROOT = Path(__file__).resolve().parent.parent
VALIDATION = ROOT / "validation"
FABRIC = ROOT / "fabric"

GUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)

# A Fabric or Kusto host that names a real cluster.
KUSTO_HOST = re.compile(
    r"https://[a-z0-9-]*trd-[a-z0-9]+[a-z0-9.-]*\.kusto\.[a-z.]+", re.IGNORECASE
)

# An address in a tenant, as opposed to the example.com ones used in docs.
TENANT_EMAIL = re.compile(
    r"\b[\w.+-]+@(?!example\.com|example\.org)[\w-]+\.(?:onmicrosoft\.com|microsoft\.com)\b",
    re.IGNORECASE,
)

# GUIDs that are legitimately in the repo because they are not tenant facts.
ALLOWED_GUIDS = {
    # The uuid5 namespace the dashboard uses to generate stable tile ids. It
    # is an arbitrary constant, not a workspace identifier.
    "6f1d3f5a-0c7f-4f2e-9c8a-5b1e7d2a4c30",
    # The RFC 4122 nil UUID. It is the .platform logicalId Fabric expects when
    # an item is not from git, and the placeholder the model builder's tests
    # pass where a real database id would go. It identifies nothing, which is
    # the whole point of it.
    "00000000-0000-0000-0000-000000000000",
}

SCANNED_SUFFIXES = {".py", ".ipynb", ".md"}


def files_to_scan():
    for base in (VALIDATION, FABRIC):
        for path in sorted(base.rglob("*")):
            if path.is_file() and path.suffix in SCANNED_SUFFIXES:
                yield path


class TestNoTenantValuesCommitted(unittest.TestCase):
    def test_no_unexpected_guids(self) -> None:
        offenders = []
        for path in files_to_scan():
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in set(GUID.findall(text)):
                if match.lower() in ALLOWED_GUIDS:
                    continue
                offenders.append(f"{path.relative_to(ROOT)}: {match}")
        self.assertEqual(
            offenders, [],
            "GUIDs found in committed files. Workspace, lakehouse, notebook, "
            "data agent and KQL database ids are tenant facts and belong in "
            "environment variables. See validation/config.py.\n  "
            + "\n  ".join(offenders),
        )

    def test_no_kusto_hostnames(self) -> None:
        offenders = [
            f"{p.relative_to(ROOT)}: {m}"
            for p in files_to_scan()
            for m in set(KUSTO_HOST.findall(p.read_text(encoding="utf-8", errors="replace")))
        ]
        self.assertEqual(
            offenders, [],
            "Kusto cluster hostnames found. Use FABRIC_KUSTO_URI.\n  "
            + "\n  ".join(offenders),
        )

    def test_no_tenant_email_addresses(self) -> None:
        offenders = [
            f"{p.relative_to(ROOT)}: {m}"
            for p in files_to_scan()
            for m in set(TENANT_EMAIL.findall(p.read_text(encoding="utf-8", errors="replace")))
        ]
        self.assertEqual(
            offenders, [],
            "Tenant email addresses found. Use AGENT_ACCURACY_RECIPIENTS, and "
            "example.com in documentation.\n  " + "\n  ".join(offenders),
        )


class TestNotebooksCarryNoBinding(unittest.TestCase):
    """A committed notebook must not point at any workspace."""

    NOTEBOOKS = ("agent_eval.ipynb", "agent_remediate.ipynb")

    def notebooks(self):
        for name in self.NOTEBOOKS:
            path = FABRIC / name
            if path.exists():
                yield name, json.loads(path.read_text(encoding="utf-8"))

    def test_no_lakehouse_dependency_metadata(self) -> None:
        for name, nb in self.notebooks():
            with self.subTest(notebook=name):
                self.assertNotIn(
                    "dependencies", nb["metadata"],
                    "a committed lakehouse binding names a workspace and would "
                    "make the notebook run against it on import",
                )

    def test_deployment_parameters_are_empty(self) -> None:
        for name, nb in self.notebooks():
            code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
            params = "".join(
                "".join(c["source"]) for c in code_cells
                if "parameters" in c.get("metadata", {}).get("tags", [])
            )
            namespace: dict = {}
            exec(compile(params, "<params>", "exec"), namespace)  # noqa: S102
            for key in ("WORKSPACE_ID", "DATA_AGENT_ID", "KUSTO_URI"):
                if key in namespace:
                    with self.subTest(notebook=name, parameter=key):
                        self.assertEqual(
                            namespace[key], "",
                            f"{key} must be empty in source control and supplied "
                            "when the notebook is deployed",
                        )


class TestConfigFailsFast(unittest.TestCase):
    """A missing value must produce one clear error, not a confusing failure."""

    def setUp(self) -> None:
        import config

        self.config = config

    def test_require_names_every_missing_variable_at_once(self) -> None:
        original = dict(self.config._VALUES)
        try:
            self.config._VALUES.update(
                {"FABRIC_WORKSPACE_ID": "", "FABRIC_KUSTO_URI": ""}
            )
            with self.assertRaises(SystemExit) as caught:
                self.config.require("FABRIC_WORKSPACE_ID", "FABRIC_KUSTO_URI")
            message = str(caught.exception)
            self.assertIn("FABRIC_WORKSPACE_ID", message)
            self.assertIn("FABRIC_KUSTO_URI", message)
        finally:
            self.config._VALUES.clear()
            self.config._VALUES.update(original)

    def test_require_passes_when_values_are_present(self) -> None:
        original = dict(self.config._VALUES)
        try:
            self.config._VALUES["FABRIC_WORKSPACE_ID"] = "set"
            self.config.require("FABRIC_WORKSPACE_ID")
        finally:
            self.config._VALUES.clear()
            self.config._VALUES.update(original)

    def test_defaults_are_object_names_not_tenant_facts(self) -> None:
        # These are safe to default because a fork is expected to keep them.
        self.assertTrue(self.config.KUSTO_DATABASE_NAME)
        self.assertTrue(self.config.LAKEHOUSE_NAME)
        self.assertTrue(self.config.SEMANTIC_MODEL_NAME)

    def test_identifiers_have_no_committed_defaults(self) -> None:
        # Everything that identifies a tenant object must default to empty.
        import importlib
        import os

        saved = {k: os.environ.pop(k, None) for k in list(os.environ)
                 if k.startswith("FABRIC_") or k in
                 ("AGENT_ACCURACY_RECIPIENTS", "GITHUB_REPOSITORY")}
        try:
            fresh = importlib.reload(self.config)
            for name in ("WORKSPACE_ID", "KUSTO_URI", "KQL_DATABASE_ID",
                         "EVAL_NOTEBOOK_ID", "REMEDIATION_NOTEBOOK_ID",
                         "DATA_AGENT_ID", "LAKEHOUSE_ID", "GITHUB_REPOSITORY"):
                with self.subTest(setting=name):
                    self.assertEqual(getattr(fresh, name), "")
            self.assertEqual(fresh.RECIPIENTS, [])
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value
            importlib.reload(self.config)


class TestDeploymentScriptsRequireConfiguration(unittest.TestCase):
    """Every script that writes to Fabric has to check before it starts."""

    SCRIPTS = {
        "build_activator.py": ["FABRIC_WORKSPACE_ID", "FABRIC_KQL_DATABASE_ID"],
        "build_dashboard.py": ["FABRIC_WORKSPACE_ID", "FABRIC_KUSTO_URI"],
        "build_schedule.py": ["FABRIC_WORKSPACE_ID", "FABRIC_EVAL_NOTEBOOK_ID"],
        # No Key Vault variables any more. The approval function reaches its
        # store with a managed connection, so a workspace is all it needs.
        "build_approval_function.py": ["FABRIC_WORKSPACE_ID"],
        "build_sql_schema.py": ["FABRIC_WORKSPACE_ID"],
        "build_agentevals_model.py": ["FABRIC_WORKSPACE_ID"],
        "build_agentevals_report.py": ["FABRIC_WORKSPACE_ID"],
        "apply_schema.py": ["FABRIC_SQL_CONNECTION_STRING"],
        "approve.py": ["FABRIC_KUSTO_URI"],
        "file_issues.py": ["FABRIC_KUSTO_URI"],
    }

    def test_each_script_calls_require(self) -> None:
        for name, expected in self.SCRIPTS.items():
            source = (VALIDATION / name).read_text(encoding="utf-8")
            with self.subTest(script=name):
                self.assertIn("require(", source)
                for variable in expected:
                    self.assertIn(variable, source)

    def test_scripts_import_config_rather_than_defining_their_own(self) -> None:
        for name in self.SCRIPTS:
            source = (VALIDATION / name).read_text(encoding="utf-8")
            with self.subTest(script=name):
                self.assertIn("from config import", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
