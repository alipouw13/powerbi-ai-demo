"""Pure evaluation logic for the data agent accuracy loop.

Standard library only, and deliberately free of any Fabric or Spark import, so
that every rule in here can be unit tested on a laptop with no capacity, no
workspace, and no network. The notebook in `fabric/agent_eval.ipynb` embeds
this module verbatim and supplies the parts that do need Fabric: the agent
call and the Delta writes.

What lives here:

* parsing the question bank, so the questions have one source of truth
* turning raw ground truth into machine-checkable expectations
* grading a free-text agent answer against an expectation
* classifying repeated attempts into stable pass, stable failure, or flake
* routing a confirmed defect to a fix class and an automation tier

What deliberately does not live here: anything that decides on its own to
change the model. This module proposes. A human disposes.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Grades
# --------------------------------------------------------------------------

CORRECT = "Correct"
PARTLY_CORRECT = "Partly correct"
WRONG = "Wrong"
REFUSED = "Refused"
ERRORED = "Errored"

STABLE_PASS = "stable_pass"
STABLE_FAILURE = "stable_failure"
FLAKE = "flake"
ERRORED_RUN = "errored"

SCORED = "scored"
PROBE = "probe"

# --------------------------------------------------------------------------
# Tolerances
# --------------------------------------------------------------------------
#
# These are the whole argument of the demo expressed as numbers, so they are
# worth stating plainly.
#
# The failure this demo exists to catch is a model answering with Gross Sales
# instead of Total Net Sales. On this dataset that is an error of roughly one
# to three percent. So the tolerance has to be tight enough to call that
# Wrong, and loose enough to accept an agent that rounds a large total to the
# nearest dollar. MONEY_REL_TOLERANCE of 0.0005 is 0.05 percent, which is two
# orders of magnitude below the error we are hunting.

MONEY_ABS_TOLERANCE = 0.51  # accepts rounding to the nearest dollar
MONEY_REL_TOLERANCE = 0.0005  # 0.05 percent
PERCENT_TOLERANCE = 0.06  # percentage points, accepts one decimal rounding
COUNT_TOLERANCE = 0  # units are integers, so be exact

REFUSAL_PATTERNS = [
    r"\bi (?:can|could)(?:no|n[o']?)t\b",
    r"\bcannot\b",
    r"\bcan't\b",
    r"\bunable to\b",
    r"\bdo(?:es)? not (?:contain|include|have)\b",
    r"\bdon'?t have\b",
    r"\bno data\b",
    r"\bnot available\b",
    r"\bhistorical data only\b",
    r"\bonly (?:contains|includes|has) historical\b",
    r"\bthere is no\b",
    r"\bdoes not exist\b",
    r"\bnot present in\b",
    r"\bnot a valid\b",
    r"\bis ?n[o']?t (?:a )?valid\b",
    r"\bno such\b",
    r"\bnot one of\b",
    r"\binvalid\b",
]

CLARIFY_PATTERNS = [
    r"\bdid you mean\b",
    r"\bdo you mean\b",
    r"\bcould you clarify\b",
    r"\bwhich (?:one|of these|do you)\b",
    r"\bambiguous\b",
    r"\bcan refer to\b",
    r"\btwo ways\b",
    r"\bassum(?:e|ed|ing)\b",
    r"\binterpret(?:ed)? (?:this|that|it) as\b",
    r"\bi used\b",
]

# Per-probe acceptance rules, written straight from the "good outcome" column
# of validation/question-bank.md. Generic refusal detection is not precise
# enough here: a probe can be answered well in prose that contains no refusal
# language at all, and a grader that cries wolf on a correct answer destroys
# trust in the alerting faster than a grader that misses one.
PROBE_ACCEPT = {
    # "Says the model contains historical data only, does not project"
    "F01": [
        r"\bhistorical\b",
        r"\bcannot (?:forecast|project|predict|provide a forecast)\b",
        r"\bno (?:forecast|projection|predictive)\b",
        r"\bdoes not (?:support|include) (?:forecast|projection)",
        *REFUSAL_PATTERNS,
    ],
    # "Asks whether you mean margin dollars or margin rate, or states that it
    # used margin dollars". A currency figure attached to a named margin
    # measure is a statement that it used margin dollars, so it counts. Naming
    # no measure at all does not.
    "F02": [
        r"margin.{0,160}(?:dollars?|rate|percent)",
        r"(?:dollars?|rate|percent).{0,160}margin",
        r"margin[^.]{0,120}[$£€]",
        r"[$£€][^.]{0,120}margin",
        *CLARIFY_PATTERNS,
    ],
    # "Says there is no Northwest region, and lists the three that exist"
    "F03": [
        r"\bnot a valid\b",
        r"\bis ?n[o']?t (?:a )?valid\b",
        r"\bno such\b",
        r"\bthere is no\b",
        r"\bdoes not exist\b",
        r"\bnot one of\b",
        r"\binvalid\b",
        r"\bnot (?:a )?region\b",
    ],
}

# Language that shows the model narrowed the time scope without being asked.
# Every one of these was observed in the wild on questions that carried no
# time filter at all.
TIME_NARROWING_PATTERNS = [
    r"\bmost recent\b",
    r"\blatest\b",
    r"\bcurrent (?:month|year|period)\b",
    r"\bfor the (?:last|past) (?:month|year|quarter)\b",
    r"\bin that period\b",
]

# The agent failing is not the model being wrong. Conflating the two puts
# infrastructure noise into a metric that is supposed to measure modelling,
# and a metric people learn to discount is worse than no metric.
AGENT_FAILURE_PATTERNS = [
    r"\bdata agent run failed\b",
    r"\bfailed before producing\b",
    r"\ban error occurred while\b",
    r"\binternal server error\b",
    r"\brequest (?:timed out|failed)\b",
    r"\bservice unavailable\b",
    r"\btry again later\b",
]

MONTH_NAMES = {
    "01": "January", "02": "February", "03": "March", "04": "April",
    "05": "May", "06": "June", "07": "July", "08": "August",
    "09": "September", "10": "October", "11": "November", "12": "December",
}


# --------------------------------------------------------------------------
# Question bank
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Question:
    id: str
    text: str
    tests: str
    kind: str  # SCORED or PROBE


_ROW = re.compile(r"^\|\s*(Q\d{2}|F\d{2})\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$")


def parse_question_bank(markdown: str) -> list[Question]:
    """Read the questions out of validation/question-bank.md.

    Parsing the markdown rather than duplicating the questions in code is the
    point. A question asked by the harness and a question printed in the docs
    that drift apart is a silent, and very confusing, failure.
    """
    questions: list[Question] = []
    seen: set[str] = set()

    for line in markdown.splitlines():
        match = _ROW.match(line.strip())
        if not match:
            continue
        qid, text, tests = match.group(1), match.group(2), match.group(3)
        if qid in seen:
            continue
        seen.add(qid)
        questions.append(
            Question(
                id=qid,
                text=text.strip(),
                tests=tests.strip(),
                kind=SCORED if qid.startswith("Q") else PROBE,
            )
        )

    return sorted(questions, key=lambda q: (q.kind != SCORED, q.id))


# --------------------------------------------------------------------------
# Expectations
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Expected:
    """One machine-checkable expectation.

    values: numbers that must all appear in the answer, as (number, kind).
    labels: groups of alternative strings. Every group must match at least one
            of its alternatives, which is how "June" and "2025-06" can both be
            accepted for the same answer.
    probe_kind: for F01 to F03, what good behaviour looks like.
    """

    id: str
    values: tuple[tuple[float, str], ...] = ()
    labels: tuple[tuple[str, ...], ...] = ()
    forbidden: tuple[str, ...] = ()
    probe_kind: str | None = None
    probe_accept: tuple[str, ...] = ()


def build_expectations(raw: dict) -> dict[str, Expected]:
    """Turn ground_truth.compute_raw() into expectations, per question."""
    top_store_name, top_store_value = raw["top_store"]
    top_product_name, top_product_value = raw["top_product"]
    best_month_key, best_month_value = raw["best_month_2025"]

    month_label = MONTH_NAMES.get(best_month_key.split("-")[1], best_month_key)

    def money_group(mapping: dict[str, float]) -> tuple:
        return tuple((value, "money") for value in mapping.values())

    def label_group(mapping: dict[str, float]) -> tuple:
        return tuple((key,) for key in mapping)

    expectations = {
        "Q01": Expected("Q01", ((raw["total_net"], "money"),)),
        "Q02": Expected("Q02", ((raw["total_margin"], "money"),)),
        "Q03": Expected("Q03", ((raw["margin_pct"] * 100, "percent"),)),
        "Q04": Expected("Q04", ((raw["total_units"], "count"),)),
        "Q05": Expected("Q05", ((raw["net_2024"], "money"),)),
        "Q06": Expected("Q06", ((raw["net_2025"], "money"),)),
        "Q07": Expected("Q07", ((raw["yoy_pct"] * 100, "percent"),)),
        "Q08": Expected(
            "Q08", ((top_store_value, "money"),), ((top_store_name,),)
        ),
        "Q09": Expected(
            "Q09", ((top_product_value, "money"),), ((top_product_name,),)
        ),
        "Q10": Expected(
            "Q10", money_group(raw["by_region"]), label_group(raw["by_region"])
        ),
        "Q11": Expected(
            "Q11", money_group(raw["by_category"]), label_group(raw["by_category"])
        ),
        "Q12": Expected(
            "Q12", money_group(raw["by_channel"]), label_group(raw["by_channel"])
        ),
        "Q13": Expected(
            "Q13",
            ((best_month_value, "money"),),
            ((best_month_key, month_label),),
        ),
        "Q14": Expected(
            "Q14",
            ((raw["weekend_net"], "money"), (raw["weekday_net"], "money")),
            (("weekend",), ("weekday",)),
        ),
        "Q15": Expected("Q15", ((raw["avg_order_line"], "money"),)),
        # The probes. A value here is a failure, not a success.
        "F01": Expected(
            "F01", probe_kind="refuse", probe_accept=tuple(PROBE_ACCEPT["F01"])
        ),
        "F02": Expected(
            "F02", probe_kind="clarify", probe_accept=tuple(PROBE_ACCEPT["F02"])
        ),
        "F03": Expected(
            "F03",
            probe_kind="refuse",
            forbidden=("northwest",),
            probe_accept=tuple(PROBE_ACCEPT["F03"]),
        ),
    }
    return expectations


# --------------------------------------------------------------------------
# Number extraction
# --------------------------------------------------------------------------

_NUMBER = re.compile(
    r"(?P<currency>[$£€])?\s*"
    r"(?P<number>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s*(?P<suffix>%|percent|percentage points?|pp|[KMB]\b)?",
    re.IGNORECASE,
)


def extract_numbers(text: str) -> list[tuple[float, str]]:
    """Pull every number out of free text, tagged as money, percent or bare.

    A number can be reported more than once with different tags. "$1.2M" is
    money 1200000. "5%" is percent 5. A bare "94,417" is tagged bare so that
    it can satisfy a count or, if nothing better matches, a money expectation.
    """
    found: list[tuple[float, str]] = []

    for match in _NUMBER.finditer(text or ""):
        raw = match.group("number").replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue

        currency = match.group("currency")
        suffix = (match.group("suffix") or "").lower()

        multiplier = 1.0
        if suffix == "k":
            multiplier = 1_000.0
        elif suffix == "m":
            multiplier = 1_000_000.0
        elif suffix == "b":
            multiplier = 1_000_000_000.0

        if suffix in {"%", "percent", "percentage point", "percentage points", "pp"}:
            found.append((value, "percent"))
        elif currency:
            found.append((value * multiplier, "money"))
        elif multiplier != 1.0:
            found.append((value * multiplier, "bare"))
        else:
            found.append((value, "bare"))

    return found


def matches_value(expected: float, kind: str, candidates: list[tuple[float, str]]) -> bool:
    """Is the expected number present in the extracted candidates."""
    for value, tag in candidates:
        if kind == "percent":
            if tag not in {"percent", "bare"}:
                continue
            if abs(value - expected) <= PERCENT_TOLERANCE:
                return True
        elif kind == "count":
            if tag not in {"bare", "money"}:
                continue
            if abs(value - expected) <= COUNT_TOLERANCE:
                return True
        else:  # money
            if tag == "percent":
                continue
            tolerance = max(MONEY_ABS_TOLERANCE, abs(expected) * MONEY_REL_TOLERANCE)
            if abs(value - expected) <= tolerance:
                return True
    return False


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).lower()


def _any_pattern(text: str, patterns: list[str]) -> bool:
    lowered = _normalise(text)
    return any(re.search(p, lowered) for p in patterns)


def looks_refused(text: str) -> bool:
    return _any_pattern(text, REFUSAL_PATTERNS)


def looks_clarifying(text: str) -> bool:
    return _any_pattern(text, CLARIFY_PATTERNS)


def looks_like_agent_failure(text: str) -> bool:
    """Did the agent itself fail, as opposed to answering badly."""
    return _any_pattern(text, AGENT_FAILURE_PATTERNS)


def looks_time_narrowed(text: str) -> bool:
    """Did the answer narrow the period on a question that set no period."""
    return _any_pattern(text, TIME_NARROWING_PATTERNS)


# --------------------------------------------------------------------------
# Grading
# --------------------------------------------------------------------------

@dataclass
class Attempt:
    question_id: str
    attempt: int
    answer: str
    grade: str
    detail: str = ""
    latency_ms: int = 0
    generated_dax: str = ""


def grade_answer(expected: Expected, answer: str) -> tuple[str, str]:
    """Grade one free-text answer. Returns (grade, human readable detail)."""
    text = answer or ""

    # An agent that fell over has told us nothing about the model.
    if looks_like_agent_failure(text):
        return ERRORED, "the agent failed to produce a result, not a model defect"

    if expected.probe_kind:
        return _grade_probe(expected, text)

    if not text.strip():
        return REFUSED, "empty response"

    candidates = extract_numbers(text)
    lowered = _normalise(text)

    missing_values = [
        f"{value:,.2f} ({kind})"
        for value, kind in expected.values
        if not matches_value(value, kind, candidates)
    ]
    missing_labels = [
        "/".join(group)
        for group in expected.labels
        if not any(alt.lower() in lowered for alt in group)
    ]

    if not missing_values and not missing_labels:
        return CORRECT, "all expected values and labels present"

    # No numbers at all, and the model said it could not answer.
    if not candidates and looks_refused(text):
        return REFUSED, "refused a question it should have answered"

    # Right labels but wrong numbers is a different defect from wrong labels.
    if missing_values and not missing_labels and expected.labels:
        return PARTLY_CORRECT, f"labels right, values missing: {', '.join(missing_values)}"

    if missing_labels and not missing_values:
        return PARTLY_CORRECT, f"values right, labels missing: {', '.join(missing_labels)}"

    detail_parts = []
    if missing_values:
        detail_parts.append(f"values missing: {', '.join(missing_values)}")
    if missing_labels:
        detail_parts.append(f"labels missing: {', '.join(missing_labels)}")
    return WRONG, "; ".join(detail_parts)


def _grade_probe(expected: Expected, text: str) -> tuple[str, str]:
    """Grade F01 to F03, where declining or disclosing is the correct outcome.

    Acceptance is driven by the per-probe rules in PROBE_ACCEPT, which are
    written from the "good outcome" column of the question bank. That matters
    because a well-behaved answer often contains no refusal language at all.
    "Northwest is not a valid region. The valid regions are Central, East and
    West" is the perfect answer and contains no "cannot" anywhere.
    """
    if not text.strip():
        return REFUSED, "empty response, which is not the same as a good refusal"

    lowered = _normalise(text)
    accepted = any(re.search(p, lowered) for p in expected.probe_accept)

    if accepted:
        # Naming the nonexistent thing in order to deny it is correct.
        return CORRECT, {
            "refuse": "declined and explained, which is the good outcome",
            "clarify": "clarified or disclosed its interpretation",
        }.get(expected.probe_kind, "behaved as expected")

    for word in expected.forbidden:
        if word in lowered:
            return WRONG, f"reported data for the nonexistent entity '{word}'"

    if expected.probe_kind == "refuse":
        return WRONG, "answered a question it should have declined"
    if expected.probe_kind == "clarify":
        return WRONG, "picked an interpretation silently"
    return WRONG, "unknown probe kind"


# --------------------------------------------------------------------------
# Classification across repetitions
# --------------------------------------------------------------------------

@dataclass
class QuestionResult:
    question_id: str
    kind: str
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def grades(self) -> list[str]:
        return [a.grade for a in self.attempts]

    @property
    def correct_count(self) -> int:
        return sum(1 for g in self.grades if g == CORRECT)

    @property
    def error_count(self) -> int:
        return sum(1 for g in self.grades if g == ERRORED)

    @property
    def classification(self) -> str:
        return classify_attempts(self.grades)

    @property
    def median_latency_ms(self) -> int:
        values = [a.latency_ms for a in self.attempts if a.latency_ms]
        return int(statistics.median(values)) if values else 0

    @property
    def is_defect(self) -> bool:
        return self.classification in {STABLE_FAILURE, FLAKE, ERRORED_RUN}


def classify_attempts(grades: list[str]) -> str:
    """Stable pass, stable failure, flake, or errored.

    Attempts where the agent itself fell over are excluded before judging the
    model. An infrastructure failure counted as a wrong answer would turn a
    healthy model into a false flake, and a metric people learn to discount is
    worse than no metric at all.

    A flake is the interesting case and it is why the harness repeats every
    question. A single run cannot tell a model that is wrong from a model that
    is ambiguous, and the second is worse in front of an audience because you
    cannot predict it or brief around it.
    """
    if not grades:
        return STABLE_FAILURE

    valid = [g for g in grades if g != ERRORED]
    if not valid:
        return ERRORED_RUN

    correct = sum(1 for g in valid if g == CORRECT)
    if correct == len(valid):
        return STABLE_PASS
    if correct == 0:
        return STABLE_FAILURE
    return FLAKE


def score_run(results: list[QuestionResult]) -> dict:
    """Summarise a run. Only scored questions count toward the /15."""
    scored = [r for r in results if r.kind == SCORED]
    probes = [r for r in results if r.kind == PROBE]

    passed = sum(1 for r in scored if r.classification == STABLE_PASS)
    flakes = [r.question_id for r in results if r.classification == FLAKE]
    failures = [r.question_id for r in results if r.classification == STABLE_FAILURE]
    errored = [r.question_id for r in results if r.classification == ERRORED_RUN]
    guardrails_lost = [
        r.question_id for r in probes if r.classification not in {STABLE_PASS, ERRORED_RUN}
    ]
    latencies = [r.median_latency_ms for r in results if r.median_latency_ms]
    attempt_count = sum(len(r.attempts) for r in results)
    error_attempts = sum(r.error_count for r in results)

    return {
        "score": passed,
        "max_score": len(scored),
        "flake_count": len(flakes),
        "flake_questions": flakes,
        "failure_questions": failures,
        "errored_questions": errored,
        "guardrails_lost": guardrails_lost,
        "median_latency_ms": int(statistics.median(latencies)) if latencies else 0,
        "attempt_count": attempt_count,
        "error_attempts": error_attempts,
        "error_rate": (error_attempts / attempt_count) if attempt_count else 0.0,
    }


# --------------------------------------------------------------------------
# Defect routing
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class FixProposal:
    question_id: str
    classification: str
    tier: int
    fix_target: str
    rationale: str
    automatable: bool
    # The literal text a human is asked to approve. Empty when the fix is not
    # an instruction change, because those cannot be applied by appending a
    # sentence and pretending the job is done.
    proposed_instruction: str = ""
    instruction_target: str = ""

    @property
    def auto_appliable(self) -> bool:
        """Can an approved fix be applied by the remediation notebook.

        Only additive instruction text qualifies. Everything else needs a
        person to open the model and think.
        """
        return bool(self.proposed_instruction) and self.tier == 1


# Where an instruction actually takes effect. This distinction is the whole
# reason the remediation notebook is not a one-liner.
#
# Agent-level instructions are NOT passed to the DAX generation step for a
# semantic model source. They shape the reply after the query has run. So a
# wrong number, a wrong filter, or an invented value can only be fixed in the
# model. Writing it in the agent box feels productive and does nothing.
TARGET_SEMANTIC_MODEL = "semantic_model"  # Prep data for AI, changes the DAX
TARGET_DATA_AGENT = "data_agent"  # response shape only

# Instructions that belong on the agent, kept apart from the model library so
# that nothing can accidentally send one to the wrong place.
#
# Everything here changes how an answer is *presented*. Nothing here can
# change a number, and that is the test for whether a line belongs in this
# dictionary rather than the one above. If a proposed agent instruction would
# only work by altering which rows were selected, it is in the wrong place and
# will do nothing at all once applied.
AGENT_INSTRUCTION_LIBRARY = {
    "label_every_group": (
        "When you answer a question that groups or breaks down a figure, name "
        "every group alongside its value. A list of numbers without the "
        "categories they belong to is not an answer to a 'by' question."
    ),
    "state_the_period": (
        "Whenever an answer covers a specific time period, say which period it "
        "covers before giving the number. If the question named no period, say "
        "that the answer covers all available data."
    ),
    "show_the_measure": (
        "Name the measure you used when you give a figure, for example "
        "\"Total Net Sales\". If two measures could plausibly answer the "
        "question, say which one you chose and why."
    ),
}


def agent_target_is_safe(detail: str) -> bool:
    """Whether an agent instruction could possibly fix this evidence.

    The rule that keeps the agent path honest. An agent instruction is applied
    after the query has run, so it can change how an answer reads and nothing
    else. If any expected *value* was missing, the query was wrong, and no
    amount of instruction about presentation will produce a number that was
    never computed.

    Getting this wrong is not a harmless mistake. It produces a fix that is
    approved, applied, verified as persisted, and changes nothing, which is
    the most expensive kind of wrong because it looks like progress.
    """
    lowered = (detail or "").lower()
    if "values missing" in lowered:
        return False
    return "values right" in lowered

# The literal sentences a human is asked to approve, per defect class. Kept
# here rather than generated, so the text is reviewable in a pull request
# rather than assembled at midnight by a scheduled job.
INSTRUCTION_LIBRARY = {
    "default_time_scope": (
        "When a question does not state a time period, answer using all available "
        "data from 1 January 2024 to 31 December 2025. Do not narrow to the most "
        "recent day, month, quarter or year unless the user asks for it. If you do "
        "apply a period, say so."
    ),
    "no_forecast": (
        "This model contains historical data only, from 1 January 2024 to "
        "31 December 2025. Never project, forecast or extrapolate beyond that range. "
        "If asked about a future period, say the data does not cover it and stop."
    ),
    "closed_region_list": (
        "The only valid regions are West, Central and East. If a user names any other "
        "region, say it does not exist, list the three valid ones, and do not "
        "substitute the closest match."
    ),
    "margin_ambiguity": (
        "Profitability is ambiguous. Gross Margin is dollars and Gross Margin % is a "
        "rate. Default to gross margin in dollars, and always state which one you used."
    ),
}


# Tier 0 is infrastructure and changes nothing about the model.
# Tier 1 is additive metadata only, and the bot may propose exact text.
# Tier 2 changes semantics or numbers, so a human writes the fix.
# Tier 3 is wording, or a verified answer, and is never automated at all.
TIER_ACTION = {
    0: "no model change, investigate the run itself",
    1: "bot proposes exact text, human approves, notebook applies it",
    2: "bot opens an issue with evidence, human writes the fix",
    3: "human only, never automated",
}


def route_defect(result: QuestionResult, expected: Expected) -> FixProposal:
    """Map an observed failure to a fix class and an automation tier.

    This is the guarded part of the loop. It never edits anything. It decides
    what kind of change would plausibly help and who is allowed to make it.
    """
    qid = result.question_id
    classification = result.classification
    grades = set(result.grades)
    detail = " ".join(a.detail for a in result.attempts).lower()
    answers = " ".join(a.answer for a in result.attempts).lower()

    # The agent fell over on every attempt. Nothing has been learned about the
    # model, so proposing a model change would be guessing.
    if classification == ERRORED_RUN:
        return FixProposal(
            qid, classification, 0,
            "no model change",
            "The agent failed to produce a result on every attempt. This is an "
            "infrastructure or capacity problem, not a modelling one. Re-run "
            "before drawing any conclusion.",
            automatable=False,
        )

    # A lost guardrail is the most serious outcome and it is invisible to the
    # score, because F01 to F03 sit outside the /15.
    if expected.probe_kind:
        key = {
            "F01": "no_forecast",
            "F02": "margin_ambiguity",
            "F03": "closed_region_list",
        }.get(qid, "")
        return FixProposal(
            qid, classification, 1,
            "semantic model AI instructions, guardrail",
            "A guardrail probe stopped behaving. Restore the constraint in the "
            "model, not the agent box, because substituting a value or inventing "
            "a projection happens when the query is built.",
            automatable=True,
            proposed_instruction=INSTRUCTION_LIBRARY.get(key, ""),
            instruction_target=TARGET_SEMANTIC_MODEL if key else "",
        )

    # The answer admits it narrowed the period on a question that set no
    # period. That is a missing default, which is additive metadata, and it
    # does not require anyone to change a measure.
    if classification != STABLE_PASS and looks_time_narrowed(answers):
        return FixProposal(
            qid, classification, 1,
            "semantic model AI instructions, default time scope",
            "Silently narrowed to the most recent period when the question "
            "carried no time filter. Add an instruction that a question "
            "without a stated period covers all available data.",
            automatable=True,
            proposed_instruction=INSTRUCTION_LIBRARY["default_time_scope"],
            instruction_target=TARGET_SEMANTIC_MODEL,
        )

    if classification == FLAKE:
        return FixProposal(
            qid, classification, 2,
            "semantic-model metadata, ambiguity",
            "Answered correctly on some attempts and not others. That is "
            "ambiguity rather than a wrong definition, and the usual cause is "
            "two plausible columns or measures with nothing to choose between "
            "them. Needs a human to decide which one is right.",
            automatable=False,
        )

    if REFUSED in grades:
        return FixProposal(
            qid, classification, 1,
            "AI data schema, inclusion",
            "Refused a question it should be able to answer. The usual cause "
            "is that the measure or column is not in the AI data schema.",
            automatable=True,
        )

    if PARTLY_CORRECT in grades and "labels right" in detail:
        return FixProposal(
            qid, classification, 2,
            "measure definition or filter context",
            "Grouped on the right thing and returned the wrong numbers. That "
            "is a measure or filter problem, so it changes a number and needs "
            "a human.",
            automatable=False,
        )

    # Every expected value was there and the labels were not. The query was
    # right and the answer was badly written, which is the one defect class an
    # agent instruction can actually fix: it shapes the reply after the query
    # has run.
    if PARTLY_CORRECT in grades and agent_target_is_safe(detail):
        return FixProposal(
            qid, classification, 1,
            "data agent instructions, answer shape",
            "Computed the right numbers and did not say what they were for. "
            "The query was correct, so this is presentation, and presentation "
            "is the only thing an agent instruction can change.",
            automatable=True,
            proposed_instruction=AGENT_INSTRUCTION_LIBRARY["label_every_group"],
            instruction_target=TARGET_DATA_AGENT,
        )

    if PARTLY_CORRECT in grades:
        return FixProposal(
            qid, classification, 1,
            "column and measure descriptions",
            "Found the right numbers under the wrong labels, which is usually "
            "a similarly named column chosen without a description to "
            "distinguish it.",
            automatable=True,
        )

    return FixProposal(
        qid, classification, 2,
        "measure selection, likely Gross Sales versus Total Net Sales",
        "Returned a confident wrong number. On this model the usual cause is "
        "the wrong revenue measure. Confirm against the generated DAX before "
        "changing anything.",
        automatable=False,
    )


def propose_fixes(
    results: list[QuestionResult],
    expectations: dict[str, Expected],
    applied_instructions: frozenset[str] = frozenset(),
) -> list[FixProposal]:
    """Propose a fix for every defect. Proposals are not changes.

    `applied_instructions` is the set of instruction lines already present in
    the model. If the router proposes one of those for a question that is
    still failing, the fix has already been tried and did not work, so the
    proposal is escalated to tier 2 instead of being offered again.

    Without this the loop has a stuck state that looks like progress: it
    proposes the same sentence every run, a human approves it every run, the
    merge is idempotent so nothing changes, and the defect never closes.
    """
    proposals = []
    for result in results:
        if not result.is_defect:
            continue
        expected = expectations.get(result.question_id)
        if expected is None:
            continue

        proposal = route_defect(result, expected)

        # A routing bug that sends a wrong-value defect to the agent would
        # produce a fix that is approved, applied, recorded as persisted, and
        # changes nothing, because agent instructions never reach the query.
        # Catch it here rather than discovering it three runs later when the
        # score has not moved.
        if proposal.instruction_target == TARGET_DATA_AGENT:
            detail = " ".join(a.detail for a in result.attempts)
            if not agent_target_is_safe(detail):
                proposal = FixProposal(
                    question_id=proposal.question_id,
                    classification=proposal.classification,
                    tier=2,
                    fix_target="mis-routed to the agent, needs a person",
                    rationale=(
                        "This defect was routed to the data agent, but its "
                        "evidence shows a missing or wrong value. An agent "
                        "instruction is applied after the query has run and "
                        "cannot produce a number that was never computed. "
                        f"Evidence: {detail}"
                    ),
                    automatable=False,
                )

        if proposal.proposed_instruction in applied_instructions:
            proposal = FixProposal(
                question_id=proposal.question_id,
                classification=proposal.classification,
                tier=2,
                fix_target="already instructed, needs a different kind of fix",
                rationale=(
                    "The instruction this defect would propose is already in the "
                    "model and the question is still failing. Adding it again "
                    "changes nothing. The cause is not a missing instruction, so "
                    "this needs a person to look at the measure, the metadata, or "
                    "the question itself."
                ),
                automatable=False,
            )

        proposals.append(proposal)
    return proposals


# --------------------------------------------------------------------------
# Applying an approved instruction
# --------------------------------------------------------------------------

REMEDIATION_HEADING = "## Automated remediation"


def instruction_present(existing: str, instruction: str) -> bool:
    """Is this exact instruction already one of the lines in the text.

    Deliberately a line match rather than a substring test. A shorter, more
    general sentence can easily be a substring of a longer one somebody wrote
    earlier, and treating that as "already present" would close an approval
    without the instruction ever having been added.
    """
    target = (instruction or "").strip()
    if not target:
        return False
    return any(line.strip() == target for line in (existing or "").splitlines())


def merge_instruction(existing: str, instruction: str) -> tuple[str, bool]:
    """Append an approved instruction under a stable heading.

    Returns the new text and whether anything changed. Append only, and
    idempotent: applying the same instruction twice is a no-op rather than a
    duplicate paragraph. Nothing a human wrote is ever rewritten, which is the
    difference between a remediation loop that is safe to leave running and
    one that quietly edits the model out from under its authors.
    """
    existing = existing or ""
    instruction = (instruction or "").strip()

    if not instruction:
        return existing, False
    if instruction_present(existing, instruction):
        return existing, False

    if REMEDIATION_HEADING in existing:
        return existing.rstrip() + "\n" + instruction + "\n", True

    separator = "\n\n" if existing.strip() else ""
    return (
        existing.rstrip()
        + separator
        + REMEDIATION_HEADING
        + "\n\n"
        + "Added by the evaluation loop after a human approved each line.\n\n"
        + instruction
        + "\n"
    ), True


# --------------------------------------------------------------------------
# Alert conditions
# --------------------------------------------------------------------------

def alert_conditions(summary: dict, previous_score: int | None) -> list[dict]:
    """Decide what, if anything, should wake somebody up.

    Returned in priority order. The notebook writes these into the Delta table
    that Activator watches, so the thresholds live here in testable code
    rather than being buried in a rule definition in the portal.
    """
    alerts: list[dict] = []

    if summary["guardrails_lost"]:
        alerts.append({
            "severity": "high",
            "condition": "guardrail_lost",
            "detail": (
                "Probes stopped refusing: "
                + ", ".join(summary["guardrails_lost"])
                + ". The model is answering questions it should decline, and "
                "no score threshold catches this because the probes sit "
                "outside the /15."
            ),
        })

    if previous_score is not None and summary["score"] <= previous_score - 2:
        alerts.append({
            "severity": "high",
            "condition": "score_regression",
            "detail": (
                f"Score fell from {previous_score} to {summary['score']}. "
                "Correlate with the most recent semantic model change."
            ),
        })

    if summary["failure_questions"]:
        alerts.append({
            "severity": "high",
            "condition": "stable_failure",
            "detail": "Reproducible failures: " + ", ".join(summary["failure_questions"]),
        })

    if summary["flake_questions"]:
        alerts.append({
            "severity": "high",
            "condition": "flake",
            "detail": (
                "Nondeterministic answers: "
                + ", ".join(summary["flake_questions"])
                + ". Ambiguity, not a wrong definition."
            ),
        })

    if summary["score"] < 13:
        alerts.append({
            "severity": "medium",
            "condition": "below_floor",
            "detail": f"Score {summary['score']} is below the agreed floor of 13.",
        })

    if summary.get("error_rate", 0) > 0.1:
        alerts.append({
            "severity": "medium",
            "condition": "agent_errors",
            "detail": (
                f"{summary['error_attempts']} of {summary['attempt_count']} "
                "attempts failed before producing a result. That is capacity or "
                "service health, not model quality, and it makes this run's "
                "score less trustworthy."
            ),
        })

    return alerts
