"""The activator graph and the approval contract.

These are the two pieces nobody can test in the portal. An Activator rule is
a base64 blob inside an item definition, and by the time it is wrong the only
symptom is silence: no email arrives and nothing says why.

The tests that matter here are the ones about *when a rule can fire at all*.
An Activator KQL source only sees rows whose event time falls inside the
window it is polling, so a query whose event time is an aggregate over history
compiles, deploys, shows as Running, and never fires once.
"""

from __future__ import annotations

import json
import os
import re
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# build_activator reads deployment values at import time. Fill them with
# throwaway values so the module imports without a tenant.
os.environ.setdefault("FABRIC_WORKSPACE_ID", str(uuid.uuid4()))
os.environ.setdefault("FABRIC_KQL_DATABASE_ID", str(uuid.uuid4()))
os.environ.setdefault("FABRIC_REMEDIATION_NOTEBOOK_ID", str(uuid.uuid4()))
os.environ.setdefault("AGENT_ACCURACY_RECIPIENTS", "someone@example.com")

import approval_card  # noqa: E402
import build_activator as activator  # noqa: E402


def rules(entities: list[dict]) -> dict[str, dict]:
    out = {}
    for entity in entities:
        definition = entity["payload"].get("definition", {})
        if definition.get("type") == "Rule":
            out[entity["payload"]["name"]] = json.loads(definition["instance"])
    return out


def sources(entities: list[dict]) -> dict[str, dict]:
    return {
        e["payload"]["name"]: e["payload"]
        for e in entities
        if e["type"] == "kqlSource-v1"
    }


def step(rule: dict, name: str) -> dict:
    for candidate in rule["steps"]:
        if candidate["name"] == name:
            return candidate
    raise AssertionError(f"no {name} in rule")


class TestActivatorEntities(unittest.TestCase):
    def setUp(self) -> None:
        self.entities = activator.build_entities()

    def test_every_entity_has_a_unique_identifier(self) -> None:
        ids = [e["uniqueIdentifier"] for e in self.entities]
        self.assertEqual(len(ids), len(set(ids)))
        for value in ids:
            uuid.UUID(value)

    def test_every_reference_points_at_an_entity_in_the_payload(self) -> None:
        known = {e["uniqueIdentifier"] for e in self.entities}
        # A reference that resolves to nothing still deploys. The item loads,
        # the rule shows in the tree, and it is wired to nothing.
        for entity in self.entities:
            parent = entity["payload"].get("parentContainer", {})
            if parent:
                self.assertIn(parent["targetUniqueIdentifier"], known)
        for rule in rules(self.entities).values():
            selector = step(rule, "FieldsDefaultsStep")["rows"][0]
            entity_id = selector["arguments"][0]["arguments"][0]["value"]
            self.assertIn(entity_id, known)

    def test_all_three_rules_are_present_and_running(self) -> None:
        names = {
            e["payload"]["name"]: e["payload"]["definition"]["settings"]
            for e in self.entities
            if e["payload"].get("definition", {}).get("type") == "Rule"
        }
        self.assertEqual(
            set(names),
            {
                "High severity accuracy alert",
                "Remediation queue waiting for approval",
                "Approved remediation, apply it",
            },
        )
        for name, settings in names.items():
            with self.subTest(rule=name):
                self.assertTrue(settings["shouldRun"], f"{name} would deploy stopped")


class TestPendingApprovalRule(unittest.TestCase):
    """The rule that answers "is anything waiting for me"."""

    def setUp(self) -> None:
        self.entities = activator.build_entities()
        self.rule = rules(self.entities)["Remediation queue waiting for approval"]
        self.source = sources(self.entities)["Remediation queue"]
        self.query = self.source["query"]["queryString"]

    def test_event_time_is_the_run_timestamp(self) -> None:
        # The whole point. An aggregate such as max(run_ts) over all history,
        # or a stored "queue last emptied" time, sits outside every polling
        # window, so the rule never fires and looks healthy while doing it.
        self.assertEqual(self.source["eventTimeSettings"]["timeFieldName"], "run_ts")
        self.assertIn("by run_ts", self.query)
        self.assertNotIn("max(run_ts)", self.query)

    def test_query_filters_to_the_polling_window(self) -> None:
        self.assertIn("where run_ts between (startTime .. endTime)", self.query)
        self.assertIn("declare query_parameters", self.query)

    def test_it_ignores_defects_somebody_already_decided(self) -> None:
        self.assertIn("distinct question_id", self.query)
        self.assertIn("eval_approvals", self.query)
        self.assertIn("join kind=leftanti", self.query)

    def test_it_only_names_columns_the_eval_notebook_writes(self) -> None:
        # A typo here deploys fine and fails at query time, which shows up as
        # a rule that never fires rather than as an error anyone sees.
        written = {
            "run_id", "run_ts", "question_id", "classification", "tier",
            "fix_target", "rationale", "proposed_instruction",
            "instruction_target", "auto_appliable", "automatable", "action",
            "status",
        }
        derived = {
            "route", "pending_count", "approvable_count", "needs_human_count",
            "questions", "queue_state", "startTime", "endTime",
        }
        referenced = set(re.findall(r"\b[a-z][a-z0-9_]{2,}\b", self.query))
        operators = {
            "declare", "query_parameters", "datetime", "eval_defects",
            "eval_approvals", "where", "between", "join", "kind", "leftanti",
            "distinct", "extend", "iff", "and", "isnotempty", "summarize",
            "count", "countif", "strcat_array", "make_list", "true", "project",
            "order", "asc", "approve", "human", "pending", "by", "on",
        }
        self.assertEqual(referenced - written - derived - operators, set())

    def test_it_counts_the_work_a_person_cannot_automate_too(self) -> None:
        # "What about the other remediations" is the question this answers.
        # Tier 2 defects never reach approve.py, so if the digest only counted
        # approvable ones they would be invisible everywhere but the dashboard.
        self.assertIn("needs_human_count", self.query)
        self.assertIn("approvable_count", self.query)

    def test_one_email_per_run_not_one_per_defect(self) -> None:
        self.assertIn("summarize", self.query)
        self.assertIn("pending_count = count()", self.query)

    def test_the_threshold_lives_in_the_query_not_the_portal(self) -> None:
        self.assertIn("where pending_count > 0", self.query)
        detect = step(self.rule, "EventDetectStep")
        self.assertEqual(detect["rows"][0]["arguments"][0]["value"], "queue_state")
        self.assertEqual(detect["rows"][1]["arguments"][1]["value"], "pending")

    def test_it_emails_the_configured_recipients(self) -> None:
        act = step(self.rule, "ActStep")["rows"][0]
        self.assertEqual(act["kind"], "EmailMessage")
        arguments = {a["name"]: a for a in act["arguments"]}
        sent_to = [v["value"] for v in arguments["sentTo"]["values"]]
        self.assertEqual(sent_to, activator.RECIPIENTS)
        self.assertTrue(arguments["subject"]["values"][0]["value"])

    def test_the_email_names_the_questions_and_how_to_approve(self) -> None:
        act = step(self.rule, "ActStep")["rows"][0]
        arguments = {a["name"]: a for a in act["arguments"]}
        body = json.dumps(arguments["optionalMessage"])
        self.assertIn("approve.py", body)
        self.assertIn("questions", body)

    def test_it_polls_often_enough_to_be_useful(self) -> None:
        self.assertLessEqual(self.source["runSettings"]["executionIntervalInSeconds"], 900)


class TestSeverityRuleUnchanged(unittest.TestCase):
    def setUp(self) -> None:
        self.entities = activator.build_entities()
        self.rule = rules(self.entities)["High severity accuracy alert"]

    def test_it_still_only_wakes_somebody_for_high(self) -> None:
        detect = step(self.rule, "EventDetectStep")
        self.assertEqual(detect["rows"][0]["arguments"][0]["value"], "alert_severity")
        self.assertEqual(detect["rows"][1]["arguments"][1]["value"], "high")


class TestApprovalRule(unittest.TestCase):
    def setUp(self) -> None:
        self.entities = activator.build_entities()
        self.rule = rules(self.entities)["Approved remediation, apply it"]

    def test_it_reacts_to_a_decision_not_to_a_proposal(self) -> None:
        detect = step(self.rule, "EventDetectStep")
        self.assertEqual(detect["rows"][0]["arguments"][0]["value"], "decision")
        self.assertEqual(detect["rows"][1]["arguments"][1]["value"], "approved")

    def test_it_runs_the_remediation_notebook_for_real(self) -> None:
        act = step(self.rule, "ActStep")["rows"][0]
        arguments = {a["name"]: a for a in act["arguments"]}
        parameters = {
            p["arguments"][0]["value"]: p["arguments"][2]["values"][0]["value"]
            for p in arguments["parameters"]["values"]
        }
        self.assertEqual(parameters["DRY_RUN"], "false")
        self.assertEqual(parameters["QUESTION_ID"], "")
        self.assertTrue(parameters["APPROVED_BY"])


class TestApprovalCommand(unittest.TestCase):
    """One builder for the row, whoever writes it."""

    BASE = dict(
        question_id="Q10",
        instruction_target="semantic_model",
        proposed_instruction="When a question does not state a time period, use all data.",
        approved_by="someone@example.com",
    )

    def test_it_appends_rather_than_replacing(self) -> None:
        command = approval_card.approval_command(**self.BASE)
        self.assertTrue(command.startswith(".set-or-append eval_approvals"))
        self.assertNotIn(".set eval_approvals", command)

    def test_it_copies_the_sentence_into_the_approval(self) -> None:
        command = approval_card.approval_command(**self.BASE)
        self.assertIn(self.BASE["proposed_instruction"], command)

    def test_it_refuses_an_anonymous_approval(self) -> None:
        payload = dict(self.BASE, approved_by="  ")
        with self.assertRaises(ValueError):
            approval_card.approval_command(**payload)

    def test_it_refuses_to_approve_an_empty_instruction(self) -> None:
        payload = dict(self.BASE, proposed_instruction="")
        with self.assertRaises(ValueError):
            approval_card.approval_command(**payload)

    def test_a_rejection_needs_no_instruction(self) -> None:
        payload = dict(self.BASE, proposed_instruction="", decision="rejected")
        self.assertIn('decision="rejected"', approval_card.approval_command(**payload))

    def test_it_refuses_a_decision_it_does_not_know(self) -> None:
        with self.assertRaises(ValueError):
            approval_card.approval_command(**dict(self.BASE, decision="maybe"))

    def test_quotes_and_backslashes_cannot_end_the_literal(self) -> None:
        payload = dict(
            self.BASE,
            proposed_instruction='Use "Total Net Sales", never a path like C:\\x',
            note='he said "no"',
        )
        command = approval_card.approval_command(**payload)
        self.assertIn('\\"Total Net Sales\\"', command)
        self.assertIn("C:\\\\x", command)
        # A literal that terminated early would leave an odd number of
        # unescaped quotes behind.
        self.assertEqual(command.count('"') % 2, 0)

    def test_the_timestamp_is_utc_and_explicit(self) -> None:
        stamp = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        command = approval_card.approval_command(**self.BASE, approved_ts=stamp)
        self.assertIn("approved_ts=datetime(2026-01-02T03:04:05.000000Z)", command)

    def test_every_approval_gets_its_own_id(self) -> None:
        first = approval_card.approval_command(**self.BASE)
        second = approval_card.approval_command(**self.BASE)
        self.assertNotEqual(first.split(",")[0], second.split(",")[0])


class TestApprovalCard(unittest.TestCase):
    def test_the_template_carries_flow_bindings(self) -> None:
        card = approval_card.adaptive_card()
        blob = json.dumps(card)
        self.assertIn("items('Apply_to_each')?['proposed_instruction']", blob)

    def test_a_rendered_card_shows_the_sentence_itself(self) -> None:
        card = approval_card.adaptive_card(
            question_id="Q10",
            classification="flake",
            proposed_instruction="Answer using all available data.",
            rationale="Silently narrowed to the most recent period.",
        )
        blob = json.dumps(card)
        self.assertIn("Answer using all available data.", blob)
        self.assertNotIn("Apply_to_each", blob)

    def test_both_decisions_are_offered(self) -> None:
        decisions = {a["data"]["decision"] for a in approval_card.adaptive_card()["actions"]}
        self.assertEqual(decisions, {"approved", "rejected"})

    def test_there_is_no_approve_all(self) -> None:
        # One card per defect. A single button over a list of model changes is
        # how a governed model gets edited by somebody who read the first line.
        titles = [a["title"].lower() for a in approval_card.adaptive_card()["actions"]]
        self.assertNotIn("approve all", titles)


if __name__ == "__main__":
    unittest.main()
