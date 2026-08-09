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
        self.assertIn("ai-instructions", proposal.fix_target)

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
        allowed = ("ai-instructions", "AI data schema", "descriptions")
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
