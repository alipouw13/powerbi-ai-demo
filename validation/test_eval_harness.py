"""Unit tests for the evaluation harness.

Standard library only. Run with:

    python -m unittest discover -s validation -p "test_*.py" -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import eval_harness as eh  # noqa: E402
import ground_truth as gt  # noqa: E402

BANK = (Path(__file__).resolve().parent / "question-bank.md").read_text(encoding="utf-8")


class TestQuestionBankParsing(unittest.TestCase):
    def setUp(self) -> None:
        self.questions = eh.parse_question_bank(BANK)

    def test_finds_fifteen_scored_and_three_probes(self) -> None:
        scored = [q for q in self.questions if q.kind == eh.SCORED]
        probes = [q for q in self.questions if q.kind == eh.PROBE]
        self.assertEqual(len(scored), 15)
        self.assertEqual(len(probes), 3)

    def test_ids_are_contiguous(self) -> None:
        scored = [q.id for q in self.questions if q.kind == eh.SCORED]
        self.assertEqual(scored, [f"Q{i:02d}" for i in range(1, 16)])

    def test_question_text_matches_the_doc_verbatim(self) -> None:
        by_id = {q.id: q.text for q in self.questions}
        self.assertEqual(by_id["Q01"], "What is our total net revenue?")
        self.assertEqual(by_id["Q14"], "Compare weekend and weekday net revenue.")
        self.assertEqual(by_id["F03"], "Show me sales for the Northwest region.")

    def test_ignores_the_scoring_table(self) -> None:
        # The "How to score" table has rows like | Correct | ... | which must
        # not be mistaken for questions.
        ids = {q.id for q in self.questions}
        self.assertTrue(all(i[0] in {"Q", "F"} for i in ids))


class TestNumberExtraction(unittest.TestCase):
    def test_currency_with_separators(self) -> None:
        found = eh.extract_numbers("Total is $412,918.50 for the period.")
        self.assertIn((412918.50, "money"), found)

    def test_percent(self) -> None:
        found = eh.extract_numbers("Margin was 68.65%.")
        self.assertIn((68.65, "percent"), found)

    def test_written_percent(self) -> None:
        found = eh.extract_numbers("Growth of 4.9 percent year over year.")
        self.assertIn((4.9, "percent"), found)

    def test_abbreviated_millions(self) -> None:
        found = eh.extract_numbers("Roughly $1.2M in revenue.")
        self.assertIn((1_200_000.0, "money"), found)

    def test_bare_count(self) -> None:
        found = eh.extract_numbers("We sold 94,417 units.")
        self.assertIn((94417.0, "bare"), found)

    def test_empty_text_is_safe(self) -> None:
        self.assertEqual(eh.extract_numbers(""), [])
        self.assertEqual(eh.extract_numbers(None), [])


class TestTolerance(unittest.TestCase):
    def test_exact_money_matches(self) -> None:
        c = eh.extract_numbers("$412,918.50")
        self.assertTrue(eh.matches_value(412918.50, "money", c))

    def test_rounding_to_the_nearest_dollar_is_accepted(self) -> None:
        c = eh.extract_numbers("$412,919")
        self.assertTrue(eh.matches_value(412918.50, "money", c))

    def test_one_percent_error_is_rejected(self) -> None:
        # This is the Gross Sales versus Total Net Sales failure. It must fail.
        c = eh.extract_numbers("$417,047.69")
        self.assertFalse(eh.matches_value(412918.50, "money", c))

    def test_percent_accepts_one_decimal_rounding(self) -> None:
        c = eh.extract_numbers("68.7%")
        self.assertTrue(eh.matches_value(68.65, "percent", c))

    def test_percent_rejects_a_point_five_error(self) -> None:
        c = eh.extract_numbers("69.2%")
        self.assertFalse(eh.matches_value(68.65, "percent", c))

    def test_counts_are_exact(self) -> None:
        c = eh.extract_numbers("94,418 units")
        self.assertFalse(eh.matches_value(94417, "count", c))

    def test_percent_does_not_satisfy_money(self) -> None:
        c = eh.extract_numbers("68.65%")
        self.assertFalse(eh.matches_value(68.65, "money", c))


class TestGrading(unittest.TestCase):
    def setUp(self) -> None:
        self.raw = gt.compute_raw()
        self.expectations = eh.build_expectations(self.raw)

    def test_real_agent_answer_grades_correct(self) -> None:
        # Captured verbatim from the deployed data agent over its MCP endpoint.
        answer = (
            "The total net revenue for Contoso Coffee across all available data "
            "(January 1, 2024 to December 31, 2025) is $412,918.50."
        )
        grade, detail = eh.grade_answer(self.expectations["Q01"], answer)
        self.assertEqual(grade, eh.CORRECT, detail)

    def test_gross_instead_of_net_is_wrong(self) -> None:
        answer = "Total revenue is $417,047.69."
        grade, _ = eh.grade_answer(self.expectations["Q01"], answer)
        self.assertEqual(grade, eh.WRONG)

    def test_empty_answer_is_refused(self) -> None:
        grade, _ = eh.grade_answer(self.expectations["Q01"], "")
        self.assertEqual(grade, eh.REFUSED)

    def test_refusal_of_an_answerable_question_is_refused(self) -> None:
        answer = "I cannot answer that with the data available."
        grade, _ = eh.grade_answer(self.expectations["Q01"], answer)
        self.assertEqual(grade, eh.REFUSED)

    def test_grouping_question_needs_every_member(self) -> None:
        regions = self.raw["by_region"]
        full = ". ".join(f"{k} was ${v:,.2f}" for k, v in regions.items())
        grade, detail = eh.grade_answer(self.expectations["Q10"], full)
        self.assertEqual(grade, eh.CORRECT, detail)

        partial = f"West was ${regions['West']:,.2f}"
        grade, _ = eh.grade_answer(self.expectations["Q10"], partial)
        self.assertNotEqual(grade, eh.CORRECT)

    def test_right_label_wrong_value_is_partly_correct(self) -> None:
        name, _ = self.raw["top_store"]
        grade, _ = eh.grade_answer(
            self.expectations["Q08"], f"{name} leads with $1.00."
        )
        self.assertEqual(grade, eh.PARTLY_CORRECT)

    def test_month_accepts_name_or_key(self) -> None:
        key, value = self.raw["best_month_2025"]
        month = eh.MONTH_NAMES[key.split("-")[1]]
        for label in (key, month):
            grade, detail = eh.grade_answer(
                self.expectations["Q13"], f"{label} 2025 was the best at ${value:,.2f}."
            )
            self.assertEqual(grade, eh.CORRECT, f"{label}: {detail}")

    def test_all_fifteen_expectations_exist(self) -> None:
        for i in range(1, 16):
            self.assertIn(f"Q{i:02d}", self.expectations)


class TestProbes(unittest.TestCase):
    def setUp(self) -> None:
        self.expectations = eh.build_expectations(gt.compute_raw())

    def test_forecast_refusal_is_correct(self) -> None:
        answer = "The model contains historical data only, so I cannot project next quarter."
        grade, _ = eh.grade_answer(self.expectations["F01"], answer)
        self.assertEqual(grade, eh.CORRECT)

    def test_inventing_a_forecast_is_wrong(self) -> None:
        answer = "Next quarter revenue will be $120,000.00."
        grade, _ = eh.grade_answer(self.expectations["F01"], answer)
        self.assertEqual(grade, eh.WRONG)

    def test_stating_the_interpretation_satisfies_the_clarify_probe(self) -> None:
        answer = "I used margin dollars rather than margin rate. Contoso Midtown leads."
        grade, _ = eh.grade_answer(self.expectations["F02"], answer)
        self.assertEqual(grade, eh.CORRECT)

    def test_silent_interpretation_is_wrong(self) -> None:
        answer = "Contoso Midtown is the most profitable store at $52,000.00."
        grade, _ = eh.grade_answer(self.expectations["F02"], answer)
        self.assertEqual(grade, eh.WRONG)

    def test_denying_the_missing_region_is_correct(self) -> None:
        answer = "There is no Northwest region. The regions are West, Central and East."
        grade, _ = eh.grade_answer(self.expectations["F03"], answer)
        self.assertEqual(grade, eh.CORRECT)

    def test_substituting_data_for_the_missing_region_is_wrong(self) -> None:
        answer = "Northwest region sales were $178,256.56."
        grade, _ = eh.grade_answer(self.expectations["F03"], answer)
        self.assertEqual(grade, eh.WRONG)


class TestProbesAgainstRealAnswers(unittest.TestCase):
    """Verbatim replies captured from the deployed agent.

    These exist because the first version of the grader marked all three of
    these as failures. Two of them were correct answers and the grader was
    wrong. A grader that cries wolf on a good answer is worse than no grader,
    because people stop reading the alerts.
    """

    def setUp(self) -> None:
        self.expectations = eh.build_expectations(gt.compute_raw())

    def test_real_f01_reply_is_correct(self) -> None:
        answer = (
            "I can't provide a forecast for next quarter's revenue. The data "
            "available covers historical sales only, through December 2025."
        )
        grade, detail = eh.grade_answer(self.expectations["F01"], answer)
        self.assertEqual(grade, eh.CORRECT, detail)

    def test_real_f02_reply_discloses_and_is_correct(self) -> None:
        answer = (
            "Contoso Midtown is the most profitable store, with a gross margin "
            "of $26,490.21 for the most recent full year available (2025).\n\n"
            "This ranking is based on gross margin in dollars, which best "
            "reflects profitability."
        )
        grade, detail = eh.grade_answer(self.expectations["F02"], answer)
        self.assertEqual(grade, eh.CORRECT, detail)

    def test_real_f03_reply_denies_cleanly_and_is_correct(self) -> None:
        answer = (
            "Northwest is not a valid region in the Contoso Coffee sales data. "
            "The valid regions are Central, East, and West. If you would like "
            "sales data for one of these regions, please specify which one."
        )
        grade, detail = eh.grade_answer(self.expectations["F03"], answer)
        self.assertEqual(grade, eh.CORRECT, detail)

    def test_reporting_a_value_for_northwest_is_still_wrong(self) -> None:
        answer = "Northwest region sales totalled $178,256.56 for the period."
        grade, _ = eh.grade_answer(self.expectations["F03"], answer)
        self.assertEqual(grade, eh.WRONG)

    def test_silent_forecast_is_still_wrong(self) -> None:
        answer = "Next quarter revenue is projected at $115,000.00."
        grade, _ = eh.grade_answer(self.expectations["F01"], answer)
        self.assertEqual(grade, eh.WRONG)

    def test_named_margin_measure_with_currency_counts_as_disclosure(self) -> None:
        # Captured verbatim. The agent names the measure and gives it in
        # dollars, which is what the question bank accepts.
        answer = (
            "Contoso Midtown is the most profitable store based on gross "
            "margin, earning $51,976.03 from January 1, 2024 to December 31, 2025."
        )
        grade, detail = eh.grade_answer(self.expectations["F02"], answer)
        self.assertEqual(grade, eh.CORRECT, detail)

    def test_a_bare_figure_with_no_named_measure_is_still_wrong(self) -> None:
        # The discrimination that keeps the probe meaningful.
        answer = "Contoso Midtown is the most profitable store at $52,000.00."
        grade, _ = eh.grade_answer(self.expectations["F02"], answer)
        self.assertEqual(grade, eh.WRONG)
        answer = "Next quarter revenue is projected at $115,000.00."
        grade, _ = eh.grade_answer(self.expectations["F01"], answer)
        self.assertEqual(grade, eh.WRONG)


class TestUnrequestedTimeFilter(unittest.TestCase):
    """The genuine defect this loop found on its first live run.

    Q11 carries no time filter, so the expected answer covers all data. The
    agent answered for the most recent month only and reported December 2025
    figures as though they were the whole picture.
    """

    def setUp(self) -> None:
        self.raw = gt.compute_raw()
        self.expectations = eh.build_expectations(self.raw)
        self.real_answer = (
            "For the most recent period available, net revenue by product "
            "category is as follows:\n"
            "- Beverage: $15,218.10\n- Food: $4,039.37\n- Retail: $1,984.00\n\n"
            "This covers all product categories in the latest data."
        )

    def test_it_grades_as_partly_correct_not_correct(self) -> None:
        grade, detail = eh.grade_answer(self.expectations["Q11"], self.real_answer)
        self.assertEqual(grade, eh.PARTLY_CORRECT, detail)
        self.assertIn("labels right", detail)

    def test_the_narrowed_total_is_the_latest_month(self) -> None:
        # Confirms the diagnosis rather than assuming it.
        narrowed_total = 15218.10 + 4039.37 + 1984.00
        _, best_month_value = self.raw["best_month_2025"]
        self.assertAlmostEqual(narrowed_total, best_month_value, places=2)

    def test_router_sends_it_to_ai_instructions_as_tier_one(self) -> None:
        result = eh.QuestionResult(
            "Q11", eh.SCORED,
            [
                eh.Attempt("Q11", i, self.real_answer, eh.PARTLY_CORRECT,
                           detail="labels right, values missing")
                for i in range(3)
            ],
        )
        proposal = eh.route_defect(result, self.expectations["Q11"])
        self.assertEqual(proposal.tier, 1)
        self.assertIn("time scope", proposal.fix_target)
        self.assertTrue(proposal.automatable)
        self.assertTrue(proposal.auto_appliable)

    def test_without_narrowing_language_it_stays_tier_two(self) -> None:
        result = eh.QuestionResult(
            "Q11", eh.SCORED,
            [
                eh.Attempt("Q11", i, "Beverage: $1.00", eh.PARTLY_CORRECT,
                           detail="labels right, values missing")
                for i in range(3)
            ],
        )
        proposal = eh.route_defect(result, self.expectations["Q11"])
        self.assertEqual(proposal.tier, 2)
        self.assertFalse(proposal.automatable)


class TestAgentFailuresAreNotModelDefects(unittest.TestCase):
    """Captured from a live run: one attempt returned an agent error string.

    Counting that as a wrong answer turned a healthy question into a false
    flake, which is exactly the kind of noise that teaches people to ignore
    an alert.
    """

    def setUp(self) -> None:
        self.expectations = eh.build_expectations(gt.compute_raw())

    def test_agent_failure_text_grades_as_errored(self) -> None:
        answer = "The Data Agent run failed before producing a result."
        grade, detail = eh.grade_answer(self.expectations["Q01"], answer)
        self.assertEqual(grade, eh.ERRORED, detail)

    def test_errored_attempts_do_not_create_a_flake(self) -> None:
        grades = [eh.CORRECT, eh.CORRECT, eh.ERRORED]
        self.assertEqual(eh.classify_attempts(grades), eh.STABLE_PASS)

    def test_all_errored_is_its_own_classification(self) -> None:
        self.assertEqual(
            eh.classify_attempts([eh.ERRORED] * 3), eh.ERRORED_RUN
        )

    def test_errors_do_not_mask_a_real_failure(self) -> None:
        grades = [eh.WRONG, eh.ERRORED, eh.WRONG]
        self.assertEqual(eh.classify_attempts(grades), eh.STABLE_FAILURE)

    def test_all_errored_routes_to_tier_zero_infrastructure(self) -> None:
        result = _result("Q01", [eh.ERRORED] * 3)
        proposal = eh.route_defect(result, self.expectations["Q01"])
        self.assertEqual(proposal.tier, 0)
        self.assertFalse(proposal.automatable)
        self.assertIn("no model change", proposal.fix_target)

    def test_high_error_rate_alerts(self) -> None:
        summary = {
            "score": 15, "max_score": 15, "flake_count": 0,
            "flake_questions": [], "failure_questions": [],
            "errored_questions": [], "guardrails_lost": [],
            "median_latency_ms": 900, "attempt_count": 54,
            "error_attempts": 12, "error_rate": 12 / 54,
        }
        alerts = eh.alert_conditions(summary, 15)
        self.assertTrue(any(a["condition"] == "agent_errors" for a in alerts))


class TestTimeNarrowingPhrasings(unittest.TestCase):
    """Every phrasing here was produced by the live agent.

    The first version of the detector only matched "most recent", so Q10 and
    Q12 were routed to a human as ambiguity when they were in fact the same
    missing-default defect as Q11.
    """

    def setUp(self) -> None:
        self.expectations = eh.build_expectations(gt.compute_raw())

    def test_observed_phrasings_are_detected(self) -> None:
        for phrase in (
            "For the latest full year available, total net revenue by region is",
            "For the latest available full year (2025), total net sales by channel",
            "For the most recent period available, net revenue by product category",
            "the most recent available period, December 2025, is 68.3%",
            "This reflects all reported revenue by region in that period.",
        ):
            with self.subTest(phrase=phrase[:40]):
                self.assertTrue(eh.looks_time_narrowed(phrase))

    def test_a_full_range_answer_is_not_flagged(self) -> None:
        answer = (
            "From January 1, 2024 to December 31, 2025, net revenue by sales "
            "channel is as follows: In Store $256,105.03."
        )
        self.assertFalse(eh.looks_time_narrowed(answer))

    def test_narrowing_routes_to_tier_one_even_without_labels(self) -> None:
        # Q03 has no labels at all, only a percentage, so the earlier rule
        # that keyed off "labels right" could never fire for it.
        result = eh.QuestionResult(
            "Q03", eh.SCORED,
            [
                eh.Attempt(
                    "Q03", 1,
                    "The overall gross margin percentage for the most recent "
                    "available period, December 2025, is 68.3%.",
                    eh.WRONG, detail="values missing",
                )
            ],
        )
        proposal = eh.route_defect(result, self.expectations["Q03"])
        self.assertEqual(proposal.tier, 1)
        self.assertIn("time scope", proposal.fix_target)

    def test_a_passing_question_is_never_routed(self) -> None:
        result = _result("Q10", [eh.CORRECT] * 3)
        self.assertFalse(result.is_defect)


class TestProposedInstructions(unittest.TestCase):
    """Every tier 1 proposal must carry the literal text a human approves."""

    def setUp(self) -> None:
        self.expectations = eh.build_expectations(gt.compute_raw())

    def _proposal(self, qid, grades, answer="", kind=eh.SCORED, detail=""):
        result = eh.QuestionResult(
            qid, kind,
            [eh.Attempt(qid, i, answer, g, detail=detail) for i, g in enumerate(grades)],
        )
        return eh.route_defect(result, self.expectations[qid])

    def test_time_scope_proposal_has_concrete_text(self) -> None:
        p = self._proposal(
            "Q10", [eh.PARTLY_CORRECT] * 3,
            answer="For the latest full year available, net revenue by region is",
            detail="labels right",
        )
        self.assertEqual(p.tier, 1)
        self.assertIn("all available data", p.proposed_instruction)
        self.assertEqual(p.instruction_target, eh.TARGET_SEMANTIC_MODEL)
        self.assertTrue(p.auto_appliable)

    def test_forecast_guardrail_proposes_the_no_forecast_line(self) -> None:
        p = self._proposal("F01", [eh.WRONG] * 3, kind=eh.PROBE)
        self.assertIn("historical data only", p.proposed_instruction)
        self.assertTrue(p.auto_appliable)

    def test_region_guardrail_lists_the_three_regions(self) -> None:
        p = self._proposal("F03", [eh.WRONG] * 3, kind=eh.PROBE)
        for region in ("West", "Central", "East"):
            self.assertIn(region, p.proposed_instruction)

    def test_margin_guardrail_names_both_measures(self) -> None:
        p = self._proposal("F02", [eh.WRONG] * 3, kind=eh.PROBE)
        self.assertIn("Gross Margin", p.proposed_instruction)
        self.assertIn("rate", p.proposed_instruction)

    def test_instructions_always_target_the_model_not_the_agent(self) -> None:
        # Agent instructions are not passed to DAX generation, so an
        # instruction that is meant to change a number must go to the model.
        for p in (
            self._proposal("F01", [eh.WRONG] * 3, kind=eh.PROBE),
            self._proposal("F03", [eh.WRONG] * 3, kind=eh.PROBE),
            self._proposal("Q10", [eh.PARTLY_CORRECT] * 3,
                           answer="for the most recent period", detail="labels right"),
        ):
            self.assertEqual(p.instruction_target, eh.TARGET_SEMANTIC_MODEL)

    def test_tier_two_carries_no_auto_applicable_text(self) -> None:
        p = self._proposal("Q01", [eh.WRONG] * 3)
        self.assertEqual(p.tier, 2)
        self.assertEqual(p.proposed_instruction, "")
        self.assertFalse(p.auto_appliable)

    def test_infrastructure_failure_is_never_auto_appliable(self) -> None:
        p = self._proposal("Q01", [eh.ERRORED] * 3)
        self.assertEqual(p.tier, 0)
        self.assertFalse(p.auto_appliable)

    def test_no_proposed_instruction_mentions_verified_answers(self) -> None:
        for text in eh.INSTRUCTION_LIBRARY.values():
            self.assertNotIn("verified answer", text.lower())


class TestInstructionMerge(unittest.TestCase):
    """Appending an approved instruction must be safe to run repeatedly."""

    LINE = "When a question does not state a time period, use all available data."

    def test_appends_under_a_heading(self) -> None:
        merged, changed = eh.merge_instruction("Existing model guidance.", self.LINE)
        self.assertTrue(changed)
        self.assertIn(eh.REMEDIATION_HEADING, merged)
        self.assertIn(self.LINE, merged)
        self.assertTrue(merged.startswith("Existing model guidance."))

    def test_is_idempotent(self) -> None:
        once, _ = eh.merge_instruction("Existing.", self.LINE)
        twice, changed = eh.merge_instruction(once, self.LINE)
        self.assertFalse(changed)
        self.assertEqual(once, twice)
        self.assertEqual(twice.count(self.LINE), 1)

    def test_second_instruction_reuses_the_same_heading(self) -> None:
        first, _ = eh.merge_instruction("Existing.", self.LINE)
        second, changed = eh.merge_instruction(first, "Another approved line.")
        self.assertTrue(changed)
        self.assertEqual(second.count(eh.REMEDIATION_HEADING), 1)
        self.assertIn(self.LINE, second)
        self.assertIn("Another approved line.", second)

    def test_never_removes_existing_text(self) -> None:
        original = "Line one.\nLine two.\nLine three."
        merged, _ = eh.merge_instruction(original, self.LINE)
        for line in original.splitlines():
            self.assertIn(line, merged)

    def test_a_substring_of_another_line_is_not_already_present(self) -> None:
        # The bug this replaced: a raw substring test would report "already
        # present" for a short sentence contained in a longer one, closing an
        # approval for an instruction the model never received.
        longer = (
            "When a question does not state a time period, use all available data "
            "and also mention the currency."
        )
        shorter = "When a question does not state a time period, use all available data"
        self.assertFalse(eh.instruction_present(longer, shorter))
        merged, changed = eh.merge_instruction(longer, shorter)
        self.assertTrue(changed, "a distinct instruction must still be added")
        self.assertIn(shorter, merged)

    def test_exact_line_match_is_still_idempotent(self) -> None:
        once, _ = eh.merge_instruction("Existing.", self.LINE)
        twice, changed = eh.merge_instruction(once, self.LINE)
        self.assertFalse(changed)
        self.assertEqual(once, twice)

    def test_instruction_present_matches_whole_lines_only(self) -> None:
        text = "Alpha beta gamma.\nDelta epsilon."
        self.assertTrue(eh.instruction_present(text, "Delta epsilon."))
        self.assertTrue(eh.instruction_present(text, "  Delta epsilon.  "))
        self.assertFalse(eh.instruction_present(text, "beta"))
        self.assertFalse(eh.instruction_present(text, ""))

    def test_empty_instruction_changes_nothing(self) -> None:
        merged, changed = eh.merge_instruction("Existing.", "")
        self.assertFalse(changed)
        self.assertEqual(merged, "Existing.")

    def test_handles_empty_existing_text(self) -> None:
        merged, changed = eh.merge_instruction("", self.LINE)
        self.assertTrue(changed)
        self.assertIn(self.LINE, merged)


class TestEscalationWhenTheFixWasAlreadyTried(unittest.TestCase):
    """The loop must not offer a fix it has already applied.

    This came from a real run. The time-scope instruction was approved and
    applied, the score moved, but Q10 still failed. Without escalation the
    loop proposes the same sentence forever, a human approves it forever, the
    merge is idempotent so nothing changes, and the defect never closes.
    """

    def setUp(self) -> None:
        self.expectations = eh.build_expectations(gt.compute_raw())
        self.narrowed = "For the latest full year available, revenue by region is"
        self.result = eh.QuestionResult(
            "Q10", eh.SCORED,
            [
                eh.Attempt("Q10", i, self.narrowed, eh.PARTLY_CORRECT,
                           detail="labels right, values missing")
                for i in range(3)
            ],
        )

    def test_first_time_it_proposes_the_instruction(self) -> None:
        proposals = eh.propose_fixes([self.result], self.expectations)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].tier, 1)
        self.assertTrue(proposals[0].auto_appliable)

    def test_second_time_it_escalates_to_a_human(self) -> None:
        already = frozenset({eh.INSTRUCTION_LIBRARY["default_time_scope"]})
        proposals = eh.propose_fixes([self.result], self.expectations, already)
        self.assertEqual(len(proposals), 1)
        proposal = proposals[0]
        self.assertEqual(proposal.tier, 2)
        self.assertFalse(proposal.auto_appliable)
        self.assertFalse(proposal.automatable)
        self.assertIn("already in the model", proposal.rationale)

    def test_an_unrelated_applied_instruction_does_not_escalate(self) -> None:
        already = frozenset({eh.INSTRUCTION_LIBRARY["no_forecast"]})
        proposals = eh.propose_fixes([self.result], self.expectations, already)
        self.assertEqual(proposals[0].tier, 1)

    def test_a_passing_question_is_never_escalated(self) -> None:
        passing = eh.QuestionResult(
            "Q10", eh.SCORED,
            [eh.Attempt("Q10", i, "", eh.CORRECT) for i in range(3)],
        )
        already = frozenset({eh.INSTRUCTION_LIBRARY["default_time_scope"]})
        self.assertEqual(eh.propose_fixes([passing], self.expectations, already), [])


class TestClassification(unittest.TestCase):
    def test_all_correct_is_stable_pass(self) -> None:
        self.assertEqual(
            eh.classify_attempts([eh.CORRECT] * 5), eh.STABLE_PASS
        )

    def test_none_correct_is_stable_failure(self) -> None:
        self.assertEqual(
            eh.classify_attempts([eh.WRONG] * 5), eh.STABLE_FAILURE
        )

    def test_mixed_is_a_flake(self) -> None:
        grades = [eh.CORRECT, eh.CORRECT, eh.WRONG, eh.CORRECT, eh.REFUSED]
        self.assertEqual(eh.classify_attempts(grades), eh.FLAKE)

    def test_no_attempts_is_a_failure_not_a_pass(self) -> None:
        self.assertEqual(eh.classify_attempts([]), eh.STABLE_FAILURE)


def _result(qid, grades, kind=eh.SCORED, detail=""):
    return eh.QuestionResult(
        question_id=qid,
        kind=kind,
        attempts=[
            eh.Attempt(qid, i, "", g, detail=detail, latency_ms=1000)
            for i, g in enumerate(grades)
        ],
    )


class TestScoring(unittest.TestCase):
    def test_only_scored_questions_count(self) -> None:
        results = [_result(f"Q{i:02d}", [eh.CORRECT] * 3) for i in range(1, 16)]
        results.append(_result("F01", [eh.WRONG] * 3, kind=eh.PROBE))
        summary = eh.score_run(results)
        self.assertEqual(summary["score"], 15)
        self.assertEqual(summary["max_score"], 15)
        self.assertEqual(summary["guardrails_lost"], ["F01"])

    def test_a_flake_does_not_count_as_a_pass(self) -> None:
        results = [_result("Q01", [eh.CORRECT, eh.WRONG, eh.CORRECT])]
        summary = eh.score_run(results)
        self.assertEqual(summary["score"], 0)
        self.assertEqual(summary["flake_questions"], ["Q01"])


class TestAlerts(unittest.TestCase):
    def _summary(self, **over):
        base = {
            "score": 15, "max_score": 15, "flake_count": 0,
            "flake_questions": [], "failure_questions": [],
            "errored_questions": [], "guardrails_lost": [],
            "median_latency_ms": 900, "attempt_count": 54,
            "error_attempts": 0, "error_rate": 0.0,
        }
        base.update(over)
        return base

    def test_clean_run_raises_nothing(self) -> None:
        self.assertEqual(eh.alert_conditions(self._summary(), 15), [])

    def test_lost_guardrail_alerts_even_at_full_score(self) -> None:
        alerts = eh.alert_conditions(self._summary(guardrails_lost=["F01"]), 15)
        self.assertEqual(alerts[0]["condition"], "guardrail_lost")
        self.assertEqual(alerts[0]["severity"], "high")

    def test_two_point_drop_alerts(self) -> None:
        alerts = eh.alert_conditions(self._summary(score=13), 15)
        self.assertTrue(any(a["condition"] == "score_regression" for a in alerts))

    def test_one_point_drop_does_not_alert_on_regression(self) -> None:
        alerts = eh.alert_conditions(self._summary(score=14), 15)
        self.assertFalse(any(a["condition"] == "score_regression" for a in alerts))

    def test_no_previous_score_skips_regression(self) -> None:
        alerts = eh.alert_conditions(self._summary(score=15), None)
        self.assertEqual(alerts, [])

    def test_below_floor_alerts(self) -> None:
        alerts = eh.alert_conditions(self._summary(score=12), 12)
        self.assertTrue(any(a["condition"] == "below_floor" for a in alerts))


class TestDefectRouting(unittest.TestCase):
    def setUp(self) -> None:
        self.expectations = eh.build_expectations(gt.compute_raw())

    def test_a_flake_is_never_automatable(self) -> None:
        result = _result("Q01", [eh.CORRECT, eh.WRONG, eh.CORRECT])
        proposal = eh.route_defect(result, self.expectations["Q01"])
        self.assertEqual(proposal.tier, 2)
        self.assertFalse(proposal.automatable)

    def test_a_wrong_number_is_never_automatable(self) -> None:
        result = _result("Q01", [eh.WRONG] * 3)
        proposal = eh.route_defect(result, self.expectations["Q01"])
        self.assertEqual(proposal.tier, 2)
        self.assertFalse(proposal.automatable)

    def test_a_refusal_routes_to_the_ai_data_schema(self) -> None:
        result = _result("Q02", [eh.REFUSED] * 3)
        proposal = eh.route_defect(result, self.expectations["Q02"])
        self.assertEqual(proposal.tier, 1)
        self.assertIn("AI data schema", proposal.fix_target)

    def test_a_lost_guardrail_routes_to_ai_instructions(self) -> None:
        result = _result("F01", [eh.WRONG] * 3, kind=eh.PROBE)
        proposal = eh.route_defect(result, self.expectations["F01"])
        self.assertEqual(proposal.tier, 1)
        self.assertIn("AI instructions", proposal.fix_target)
        self.assertEqual(proposal.instruction_target, eh.TARGET_SEMANTIC_MODEL)

    def test_no_proposal_ever_writes_a_verified_answer(self) -> None:
        # Principle 1.2 of the spec. A loop that can pin a verified answer will
        # optimise its own score over a model that is still wrong.
        results = [
            _result("Q01", [eh.WRONG] * 3),
            _result("Q02", [eh.REFUSED] * 3),
            _result("Q08", [eh.PARTLY_CORRECT] * 3, detail="labels right"),
            _result("Q10", [eh.CORRECT, eh.WRONG, eh.CORRECT]),
            _result("F01", [eh.WRONG] * 3, kind=eh.PROBE),
        ]
        proposals = eh.propose_fixes(results, self.expectations)
        self.assertEqual(len(proposals), 5)
        for proposal in proposals:
            self.assertNotIn("verified answer", proposal.fix_target.lower())
            self.assertNotIn("verified answer", proposal.rationale.lower())

    def test_passing_questions_produce_no_proposals(self) -> None:
        results = [_result("Q01", [eh.CORRECT] * 3)]
        self.assertEqual(eh.propose_fixes(results, self.expectations), [])

    def test_every_tier_one_proposal_is_additive_metadata(self) -> None:
        allowed = ("AI instructions", "AI data schema", "descriptions",
                   "data agent instructions")
        results = [
            _result("Q02", [eh.REFUSED] * 3),
            _result("F01", [eh.WRONG] * 3, kind=eh.PROBE),
            _result("Q08", [eh.PARTLY_CORRECT] * 3, detail="values right"),
        ]
        for proposal in eh.propose_fixes(results, self.expectations):
            if proposal.tier == 1:
                self.assertTrue(
                    any(a in proposal.fix_target for a in allowed),
                    f"tier 1 target not additive: {proposal.fix_target}",
                )

    def test_an_agent_proposal_only_ever_follows_agent_safe_evidence(self) -> None:
        """The invariant the whitelist above was really protecting.

        An agent instruction is applied after the query has run. Proposing one
        for a defect whose evidence is a missing value produces a fix that is
        approved, applied, recorded as persisted, and changes nothing.
        """
        results = [
            _result("Q08", [eh.PARTLY_CORRECT] * 3, detail="values right, labels missing: East"),
            _result("Q09", [eh.PARTLY_CORRECT] * 3, detail="labels right, values missing: 1,234.00"),
            _result("Q02", [eh.WRONG] * 3, detail="values missing: 99.00"),
            _result("Q10", [eh.REFUSED] * 3),
        ]
        for proposal in eh.propose_fixes(results, self.expectations):
            if proposal.instruction_target == eh.TARGET_DATA_AGENT:
                evidence = " ".join(
                    a.detail
                    for r in results if r.question_id == proposal.question_id
                    for a in r.attempts
                )
                self.assertTrue(
                    eh.agent_target_is_safe(evidence),
                    f"{proposal.question_id} was routed to the agent on "
                    f"evidence an agent instruction cannot fix: {evidence}",
                )

    def test_a_values_missing_defect_never_reaches_the_agent(self) -> None:
        results = [_result("Q08", [eh.PARTLY_CORRECT] * 3,
                           detail="labels right, values missing: 1,234.00")]
        proposal = eh.propose_fixes(results, self.expectations)[0]
        self.assertNotEqual(proposal.instruction_target, eh.TARGET_DATA_AGENT)

    def test_a_presentation_defect_is_offered_as_an_agent_fix(self) -> None:
        results = [_result("Q08", [eh.PARTLY_CORRECT] * 3,
                           detail="values right, labels missing: East")]
        proposal = eh.propose_fixes(results, self.expectations)[0]
        self.assertEqual(proposal.instruction_target, eh.TARGET_DATA_AGENT)
        self.assertTrue(proposal.auto_appliable)
        self.assertIn(proposal.proposed_instruction,
                      eh.AGENT_INSTRUCTION_LIBRARY.values())

    def test_the_two_instruction_libraries_do_not_overlap(self) -> None:
        # A sentence in both would be applied to whichever target the router
        # happened to pick, which is how a model fix ends up in the agent box
        # doing nothing.
        self.assertEqual(
            set(eh.INSTRUCTION_LIBRARY.values())
            & set(eh.AGENT_INSTRUCTION_LIBRARY.values()),
            set(),
        )

    def test_agent_target_is_safe_rejects_missing_values(self) -> None:
        self.assertFalse(eh.agent_target_is_safe("labels right, values missing: 1.00"))
        self.assertFalse(eh.agent_target_is_safe("values missing: 1.00"))
        self.assertFalse(eh.agent_target_is_safe(""))
        self.assertTrue(eh.agent_target_is_safe("values right, labels missing: East"))


class TestGroundTruthContract(unittest.TestCase):
    def test_raw_and_formatted_agree(self) -> None:
        raw = gt.compute_raw()
        formatted = gt.compute()
        self.assertEqual(
            formatted["Q01 total net revenue (all time)"],
            f"${raw['total_net']:,.2f}",
        )
        self.assertEqual(
            formatted["Q03 gross margin percent"], f"{raw['margin_pct']:.2%}"
        )

    def test_regions_are_the_three_we_claim(self) -> None:
        self.assertEqual(
            set(gt.compute_raw()["by_region"]), {"West", "Central", "East"}
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
