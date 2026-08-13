"""Make the AgentEvals semantic model readable by a person and by Copilot.

The SQL database in Fabric is now the loop's operational store, and a Direct
Lake semantic model called `AgentEvals` sits on top of it. Fabric generates
that model automatically, and what it generates is a faithful copy of the
database: seven tables named `runs`, `answers`, `defects`, snake_case columns,
no relationships, no measures, no descriptions, and every integer column set
to sum.

That is fine for a database and useless for AI. Copilot reads names,
descriptions, relationships and measures, and this model gives it none of
them, so:

* `SUM(runs[score])` across ten runs returns 140 out of 15, which reads as a
  number rather than as nonsense.
* "How did question Q7 do?" cannot be answered, because nothing joins
  `answers` to `questions`.
* `question_id`, `run_id` and `approval_id` are offered as things to group by,
  and a GUID is never an answer.

This script fixes all of that in one place, declaratively. It is the model
equivalent of `build_sql_schema.py`: the spec below is the source of truth,
the TMDL is generated from it, and the generated TMDL is not committed because
it carries the workspace and database ids.

Three rules shape the spec, and they are the same three from
`semantic-model/ai-instructions.md`:

1. **Rename in the model, never in the source.** `dbo.runs` stays `dbo.runs`.
   The model calls it `Evaluation Runs` because that is what a person says.
2. **Hide anything that must not be aggregated or grouped by.** Every key, and
   every raw count that has a measure over it. A visible numeric column is an
   invitation to sum it.
3. **Every visible object gets a description.** Copilot reads the first ~200
   characters, so the meaning comes first and the caveat comes last.

Run:
    python validation/build_agentevals_model.py            # write TMDL locally
    python validation/build_agentevals_model.py --apply    # push it to Fabric
    python validation/build_agentevals_model.py --docs     # refresh measures.dax
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (  # noqa: E402
    AGENTEVALS_MODEL_NAME,
    FABRIC_API,
    SQL_DATABASE_NAME,
    WORKSPACE_ID,
    require,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "semantic-model" / "agentevals"
DEFINITION = OUT / "definition"
MEASURES_DOC = OUT / "measures.dax"

# The same namespace build_dashboard.py uses. lineageTags have to be stable
# across runs or every apply looks like a new column to anything that
# references it, and a verified answer that points at a renamed lineage
# silently stops matching.
NAMESPACE = uuid.UUID("6f1d3f5a-0c7f-4f2e-9c8a-5b1e7d2a4c30")

EXPRESSION_NAME = f"DirectLake - {SQL_DATABASE_NAME}"


def stable_id(label: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"agentevals/{label}"))


# --------------------------------------------------------------------------
# Spec
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Column:
    source: str
    name: str
    dtype: str
    description: str = ""
    hidden: bool = False
    format_string: str = ""
    folder: str = ""

    @property
    def summarize_by(self) -> str:
        # Never sum a column in this model. Every number that is worth adding
        # up has a measure, and the ones that are not worth adding up are
        # per-run values where a sum is meaningless.
        return "none"


@dataclass(frozen=True)
class Table:
    source: str
    name: str
    description: str
    columns: list[Column]


@dataclass(frozen=True)
class Relationship:
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    active: bool = True
    why: str = ""


@dataclass(frozen=True)
class Measure:
    table: str
    name: str
    expression: str
    description: str
    format_string: str = "0"
    folder: str = ""


TEXT = "string"
INT = "int64"
TIME = "dateTime"
BOOL = "boolean"


TABLES: list[Table] = [
    Table(
        source="questions",
        name="Questions",
        description=(
            "The question bank: the fixed set of questions every evaluation "
            "run asks. One row per question. Authored in version control and "
            "published here, so the wording cannot change without a reviewed "
            "commit."
        ),
        columns=[
            Column("question_id", "Question ID", TEXT,
                   "Short identifier for a question, such as Q7. This is how "
                   "people refer to a question in conversation."),
            Column("kind", "Question Kind", TEXT,
                   "Whether a question counts toward the score. 'scored' "
                   "questions make up the score out of 15. 'probe' questions "
                   "test a guardrail and are reported separately."),
            Column("ordinal", "Question Number", INT,
                   "The question's position in the bank. Use it to sort "
                   "questions into their asked order.", format_string="0"),
            Column("prompt", "Question Text", TEXT,
                   "The exact wording asked of the AI surface. Rewording a "
                   "question would change what is being measured, so this "
                   "text is treated as fixed."),
            Column("tests", "What It Tests", TEXT,
                   "The behaviour this question is designed to catch, in "
                   "plain language."),
            Column("good_outcome", "Good Outcome", TEXT,
                   "For probe questions only: what a correct refusal or "
                   "caveat looks like. Blank for scored questions."),
            Column("bank_sha", "Bank Version", TEXT,
                   "Git hash of the question bank this row was published "
                   "from.", hidden=True),
            Column("published_ts", "Published", TIME,
                   "When this version of the question was published to the "
                   "database.", format_string="General Date"),
        ],
    ),
    Table(
        source="runs",
        name="Evaluation Runs",
        description=(
            "One row per evaluation run. A run asks every question in the "
            "bank several times against one AI surface and records a score "
            "out of the number of scored questions. Scores belong to a single "
            "run and must never be added together across runs."
        ),
        columns=[
            Column("run_id", "Run ID", TEXT,
                   "Unique identifier for a run.", hidden=True),
            Column("run_ts", "Run Time", TIME,
                   "When the run started. This is the date to use for any "
                   "question about trend or 'latest'.",
                   format_string="General Date"),
            Column("surface", "Surface", TEXT,
                   "Which AI surface was tested: the Copilot pane, the "
                   "standalone Copilot experience, or the Fabric data agent. "
                   "Two surfaces are not comparable to each other."),
            Column("bank_sha", "Question Bank Version", TEXT,
                   "Git hash of the question bank used. Two runs with "
                   "different values were not asked the same questions and "
                   "their scores are not comparable."),
            Column("score", "Run Score", INT,
                   "Scored questions this run answered correctly every time.",
                   hidden=True, format_string="0"),
            Column("max_score", "Run Max Score", INT,
                   "How many scored questions the bank had.", hidden=True,
                   format_string="0"),
            Column("previous_score", "Run Previous Score", INT,
                   "The score of the run before this one.", hidden=True,
                   format_string="0"),
            Column("flake_count", "Run Flake Count", INT,
                   "Questions answered correctly sometimes and not others.",
                   hidden=True, format_string="0"),
            Column("failure_count", "Run Failure Count", INT,
                   "Questions answered wrongly every time.", hidden=True,
                   format_string="0"),
            Column("guardrails_lost_count", "Run Guardrails Lost Count", INT,
                   "Probe questions where the surface answered instead of "
                   "refusing.", hidden=True, format_string="0"),
            Column("errored_count", "Run Errored Count", INT,
                   "Questions where the surface itself failed.", hidden=True,
                   format_string="0"),
            Column("alert_severity", "Alert Severity", TEXT,
                   "Worst alert this run raised: 'high', 'medium' or 'none'. "
                   "Only 'high' notifies a person."),
            Column("alert_detail", "Alert Detail", TEXT,
                   "Why the run alerted, in plain language."),
        ],
    ),
    Table(
        source="answers",
        name="Answers",
        description=(
            "One row per attempt, not per question. Every question is asked "
            "several times in a run on purpose: a question answered correctly "
            "twice out of three is the finding, and a single attempt cannot "
            "tell a wrong model from an unstable one."
        ),
        columns=[
            Column("run_id", "Run ID", TEXT, "The run this attempt belongs to.",
                   hidden=True),
            Column("question_id", "Question ID", TEXT,
                   "The question that was asked.", hidden=True),
            Column("attempt", "Attempt Number", INT,
                   "Which repeat this was within the run, starting at 1.",
                   format_string="0"),
            Column("grade", "Grade", TEXT,
                   "How this single attempt was graded: 'Correct', 'Partly "
                   "correct', 'Wrong', 'Refused' or 'Errored'. 'Errored' "
                   "means the surface failed, not that the answer was wrong."),
            Column("classification", "Question Outcome", TEXT,
                   "The verdict across every attempt of this question in this "
                   "run: 'stable_pass', 'stable_failure', 'flake' or "
                   "'errored'. It repeats on each attempt row."),
            Column("detail", "Grader Detail", TEXT,
                   "Why the grader gave this grade."),
            Column("latency_ms", "Response Time (ms)", INT,
                   "How long the surface took to answer, in milliseconds.",
                   hidden=True, format_string="0"),
            Column("answer", "Answer Text", TEXT,
                   "The answer the surface gave, verbatim."),
        ],
    ),
    Table(
        source="defects",
        name="Defects",
        description=(
            "One row per question per run that did not pass cleanly, with the "
            "fix the harness proposes. A defect is a proposal, not a change: "
            "nothing here has been applied to any model."
        ),
        columns=[
            Column("run_id", "Run ID", TEXT, "The run that found the defect.",
                   hidden=True),
            Column("question_id", "Question ID", TEXT,
                   "The question that exposed the defect.", hidden=True),
            Column("classification", "Defect Outcome", TEXT,
                   "What the question did: 'stable_failure', 'flake' or "
                   "'errored'."),
            Column("tier", "Fix Tier", INT,
                   "How confident the harness is in the proposed fix. 1 is "
                   "safe to apply, 2 needs judgement, 3 is a human decision.",
                   format_string="0"),
            Column("fix_target", "Fix Target", TEXT,
                   "What has to change, in plain language."),
            Column("instruction_target", "Instruction Target", TEXT,
                   "Where an approved instruction would be written: "
                   "'semantic_model', 'data_agent', or blank when the fix is "
                   "not an instruction at all."),
            Column("proposed_instruction", "Proposed Instruction", TEXT,
                   "The exact sentence a person is being asked to approve. "
                   "Blank when the fix needs a model change rather than an "
                   "instruction."),
            Column("rationale", "Rationale", TEXT,
                   "Why this fix is proposed for this defect."),
            Column("auto_appliable", "Auto Appliable", BOOL,
                   "True when the loop could apply this fix without a person. "
                   "It still does not: approval is always required."),
        ],
    ),
    Table(
        source="approvals",
        name="Approvals",
        description=(
            "One human decision about one proposed instruction. An approval "
            "records the sentence that was agreed, copied rather than "
            "referenced, because the proposal can change on the next run and "
            "what was agreed cannot."
        ),
        columns=[
            Column("approval_id", "Approval ID", TEXT,
                   "Unique identifier for a decision.", hidden=True),
            Column("approved_ts", "Decision Time", TIME,
                   "When the decision was made.", format_string="General Date"),
            Column("question_id", "Question ID", TEXT,
                   "The question the decision is about.", hidden=True),
            Column("instruction_target", "Instruction Target", TEXT,
                   "Where the instruction goes: 'semantic_model' or "
                   "'data_agent'."),
            Column("proposed_instruction", "Approved Instruction", TEXT,
                   "The exact text that was approved or rejected."),
            Column("decision", "Decision", TEXT,
                   "'approved' or 'rejected'. Only 'approved' causes anything "
                   "to happen."),
            Column("approved_by", "Decided By", TEXT,
                   "The person who decided, read from their sign-in token "
                   "rather than typed, so it cannot be someone else's name."),
            Column("approver_oid", "Approver Object ID", TEXT,
                   "Entra object id of the approver.", hidden=True),
            Column("source", "Decision Source", TEXT,
                   "Where the decision was made: 'report', 'card' for the "
                   "approval email, or 'cli'."),
            Column("note", "Decision Note", TEXT,
                   "Free text the approver added."),
            Column("mirrored_ts", "Mirrored Time", TIME,
                   "When the approval reached the eventhouse that triggers "
                   "the remediation notebook. Blank means the trigger has not "
                   "fired yet.", format_string="General Date"),
        ],
    ),
    Table(
        source="feedback",
        name="Feedback",
        description=(
            "A report reader saying an answer looked wrong. Feedback is "
            "evidence that a defect may exist. It is never an approval and "
            "can never become one on its own, or the loop would agree with "
            "whoever complained most recently."
        ),
        columns=[
            Column("feedback_id", "Feedback ID", TEXT,
                   "Unique identifier.", hidden=True),
            Column("created_ts", "Feedback Time", TIME,
                   "When the feedback was submitted.",
                   format_string="General Date"),
            Column("created_by", "Submitted By", TEXT,
                   "The person who submitted it, read from their sign-in "
                   "token. Feedback is not anonymous."),
            Column("created_oid", "Submitter Object ID", TEXT,
                   "Entra object id of the submitter.", hidden=True),
            Column("run_id", "Run ID", TEXT,
                   "The run being commented on, when there is one.",
                   hidden=True),
            Column("question_id", "Question ID", TEXT,
                   "The question being commented on.", hidden=True),
            Column("verdict", "Verdict", TEXT,
                   "What the reader thought: 'wrong', 'misleading' or "
                   "'right'."),
            Column("comment", "Comment", TEXT, "What the reader wrote."),
            Column("status", "Triage Status", TEXT,
                   "How far the feedback has been triaged: 'new', 'triaged' "
                   "or 'dismissed'."),
        ],
    ),
    Table(
        source="remediations",
        name="Remediations",
        description=(
            "An approved instruction that was actually written to a semantic "
            "model or data agent. This is the only table in the model that "
            "records a change to the thing being measured."
        ),
        columns=[
            Column("remediation_id", "Remediation ID", TEXT,
                   "Unique identifier.", hidden=True),
            Column("recorded_ts", "Recorded Time", TIME,
                   "When the remediation was recorded.",
                   format_string="General Date"),
            Column("applied_ts", "Applied Time", TIME,
                   "When the instruction was written. Blank if it was never "
                   "applied.", format_string="General Date"),
            Column("approval_id", "Approval ID", TEXT,
                   "The decision that authorised this.", hidden=True),
            Column("question_id", "Question ID", TEXT,
                   "The question this was meant to fix.", hidden=True),
            Column("instruction_target", "Instruction Target", TEXT,
                   "What was changed: 'semantic_model' or 'data_agent'."),
            Column("instruction", "Applied Instruction", TEXT,
                   "The exact text that was written."),
            Column("approved_by", "Approved By", TEXT,
                   "Who approved it."),
            Column("applied_by", "Applied By", TEXT,
                   "What applied it, usually the remediation notebook."),
            Column("dry_run", "Dry Run", BOOL,
                   "True when the notebook only rehearsed the change. A dry "
                   "run changes nothing."),
            Column("persisted", "Persisted", BOOL,
                   "True when the instruction was really written. This, not "
                   "approval, is what makes a fix real."),
            Column("verified", "Verified", BOOL,
                   "True when a later run re-asked the question and it "
                   "passed. An applied fix that was never verified is not "
                   "yet known to have worked."),
            Column("verified_ts", "Verified Time", TIME,
                   "When verification happened.", format_string="General Date"),
            Column("verified_run_id", "Verified Run ID", TEXT,
                   "The run that verified it.", hidden=True),
        ],
    ),
]


RELATIONSHIPS: list[Relationship] = [
    Relationship("Answers", "Question ID", "Questions", "Question ID",
                 why="every attempt is an attempt at one question"),
    Relationship("Defects", "Question ID", "Questions", "Question ID",
                 why="a defect is always about one question"),
    Relationship("Approvals", "Question ID", "Questions", "Question ID",
                 why="a decision is always about one question"),
    Relationship("Feedback", "Question ID", "Questions", "Question ID",
                 why="feedback is always about one question"),
    Relationship("Answers", "Run ID", "Evaluation Runs", "Run ID",
                 why="attempts belong to the run that made them"),
    Relationship("Defects", "Run ID", "Evaluation Runs", "Run ID",
                 why="a defect is found by a run"),
    Relationship("Feedback", "Run ID", "Evaluation Runs", "Run ID",
                 why="feedback may name the run it is about"),
    Relationship("Remediations", "Approval ID", "Approvals", "Approval ID",
                 why="a remediation exists because a decision authorised it"),
    # Inactive on purpose. Questions already reaches Remediations through
    # Approvals, and a second live path would make the filter ambiguous, which
    # Power BI rejects outright. Kept so USERELATIONSHIP can reach it if a
    # remediation ever lands without an approval.
    Relationship("Remediations", "Question ID", "Questions", "Question ID",
                 active=False,
                 why="second path to Questions; Approvals is the live one"),
]


# --------------------------------------------------------------------------
# Measures
# --------------------------------------------------------------------------
#
# "The latest run" is the phrase everybody uses and the thing this model is
# hardest to get right, so it is written the same way every time: take the one
# row with the highest Run Time, break ties on Run ID, then read a column off
# it. Repetition beats a shared helper here, because each measure has to stay
# correct when Copilot drops it into a filter context nobody predicted.

LATEST = (
    "VAR LatestRun =\n"
    "    TOPN (\n"
    "        1,\n"
    "        'Evaluation Runs',\n"
    "        'Evaluation Runs'[Run Time], DESC,\n"
    "        'Evaluation Runs'[Run ID], ASC\n"
    "    )\n"
)

SCORE = "Score"
QUALITY = "Answer quality"
DEFECTS = "Defects"
APPROVALS = "Approvals"
REMEDIATION = "Remediation"
FEEDBACK = "Feedback"


def latest_of(column: str) -> str:
    return LATEST + f"RETURN\n    SUMX ( LatestRun, 'Evaluation Runs'[{column}] )"


MEASURES: list[Measure] = [
    # ---- Score -----------------------------------------------------------
    Measure(
        "Evaluation Runs", "Runs Evaluated",
        "COUNTROWS ( 'Evaluation Runs' )",
        "Counts evaluation runs in the current filter context. Use it to ask "
        "how often the loop has run, not how well it did.",
        "#,##0", SCORE,
    ),
    Measure(
        "Evaluation Runs", "Latest Run Time",
        "MAX ( 'Evaluation Runs'[Run Time] )",
        "The most recent run time in the current filter context. Every "
        "'latest' measure in this model reports the run this points at.",
        "General Date", SCORE,
    ),
    Measure(
        "Evaluation Runs", "Latest Score",
        latest_of("Run Score"),
        "Scored questions the most recent run answered correctly on every "
        "attempt. This is the headline accuracy number. Scores belong to one "
        "run, so this reads the latest rather than adding runs together.",
        "0", SCORE,
    ),
    Measure(
        "Evaluation Runs", "Questions Scored",
        latest_of("Run Max Score"),
        "How many scored questions the most recent run had to answer. This is "
        "the denominator of the score, and it changes only when the question "
        "bank changes.",
        "0", SCORE,
    ),
    Measure(
        "Evaluation Runs", "Score %",
        "DIVIDE ( [Latest Score], [Questions Scored] )",
        "The most recent score as a percentage of the questions available. "
        "Use this when comparing runs that used different question banks.",
        "0.0%", SCORE,
    ),
    Measure(
        "Evaluation Runs", "Previous Score",
        latest_of("Run Previous Score"),
        "The score of the run immediately before the most recent one. Blank "
        "on the first ever run.",
        "0", SCORE,
    ),
    Measure(
        "Evaluation Runs", "Score Change",
        "VAR ThisRun = [Latest Score]\n"
        "VAR PriorRun = [Previous Score]\n"
        "RETURN\n"
        "    IF ( NOT ISBLANK ( PriorRun ), ThisRun - PriorRun )",
        "Change in score from the previous run to the latest one. Negative is "
        "a regression and is what the alerting watches for. Blank when there "
        "is no previous run to compare against.",
        "+0;-0;0", SCORE,
    ),
    Measure(
        "Evaluation Runs", "Score Headline",
        'FORMAT ( [Latest Score], "0" ) & " / " & FORMAT ( [Questions Scored], "0" )',
        "The score written the way people say it out loud, such as 13 / 15. "
        "Use it for a card or a sentence rather than for arithmetic.",
        "", SCORE,
    ),
    Measure(
        "Evaluation Runs", "Latest Alert Severity",
        LATEST + "RETURN\n"
                 "    MAXX ( LatestRun, 'Evaluation Runs'[Alert Severity] )",
        "Worst alert raised by the most recent run: high, medium or none. "
        "Only high notifies a person.",
        "", SCORE,
    ),
    Measure(
        "Evaluation Runs", "Flaky Questions",
        latest_of("Run Flake Count"),
        "Questions the most recent run answered correctly sometimes and "
        "wrongly other times. A flake is worse than a steady failure in front "
        "of an audience, because it cannot be predicted or briefed around.",
        "0", SCORE,
    ),
    Measure(
        "Evaluation Runs", "Failing Questions",
        latest_of("Run Failure Count"),
        "Questions the most recent run answered wrongly on every attempt.",
        "0", SCORE,
    ),
    Measure(
        "Evaluation Runs", "Guardrails Lost",
        latest_of("Run Guardrails Lost Count"),
        "Probe questions where the most recent run answered instead of "
        "refusing. Any value above zero means the model invented something it "
        "should have declined to say.",
        "0", SCORE,
    ),
    Measure(
        "Evaluation Runs", "Errored Questions",
        latest_of("Run Errored Count"),
        "Questions where the AI surface itself failed in the most recent run. "
        "These are infrastructure failures and are excluded from the score, "
        "so a high value makes the score less trustworthy rather than lower.",
        "0", SCORE,
    ),

    # ---- Answer quality --------------------------------------------------
    Measure(
        "Answers", "Attempts",
        "COUNTROWS ( 'Answers' )",
        "Counts individual attempts. Every question is asked several times "
        "per run, so this is larger than the number of questions.",
        "#,##0", QUALITY,
    ),
    Measure(
        "Answers", "Correct Attempts",
        'CALCULATE ( [Attempts], \'Answers\'[Grade] = "Correct" )',
        "Attempts graded fully correct. Partly correct does not count.",
        "#,##0", QUALITY,
    ),
    Measure(
        "Answers", "Correct Attempt %",
        "DIVIDE ( [Correct Attempts], [Attempts] )",
        "Share of attempts graded fully correct. This is a softer number than "
        "Score %, which only credits a question when every attempt was right.",
        "0.0%", QUALITY,
    ),
    Measure(
        "Answers", "Errored Attempts",
        'CALCULATE ( [Attempts], \'Answers\'[Grade] = "Errored" )',
        "Attempts where the AI surface failed to answer at all. These are "
        "excluded from grading, because counting an outage as a wrong answer "
        "turns a healthy model into a false failure.",
        "#,##0", QUALITY,
    ),
    Measure(
        "Answers", "Questions Asked",
        "DISTINCTCOUNT ( 'Answers'[Question ID] )",
        "How many distinct questions were asked, regardless of how many times "
        "each was repeated.",
        "0", QUALITY,
    ),
    Measure(
        "Answers", "Median Response Time (s)",
        "DIVIDE ( MEDIANX ( 'Answers', 'Answers'[Response Time (ms)] ), 1000 )",
        "Typical time the AI surface took to answer, in seconds. Median "
        "rather than average, because one timeout would drag an average "
        "somewhere misleading.",
        "0.0", QUALITY,
    ),
    Measure(
        "Answers", "Slowest Response Time (s)",
        "DIVIDE ( MAX ( 'Answers'[Response Time (ms)] ), 1000 )",
        "The slowest single answer, in seconds. Useful for spotting the "
        "timeouts the median hides.",
        "0.0", QUALITY,
    ),

    # ---- Defects ---------------------------------------------------------
    Measure(
        "Defects", "Defects Found",
        "COUNTROWS ( 'Defects' )",
        "Questions that did not pass cleanly and produced a proposed fix. A "
        "defect is a proposal, not a change.",
        "#,##0", DEFECTS,
    ),
    Measure(
        "Defects", "Defects In Latest Run",
        "VAR LatestRunID =\n"
        "    MAXX (\n"
        "        TOPN (\n"
        "            1,\n"
        "            'Evaluation Runs',\n"
        "            'Evaluation Runs'[Run Time], DESC,\n"
        "            'Evaluation Runs'[Run ID], ASC\n"
        "        ),\n"
        "        'Evaluation Runs'[Run ID]\n"
        "    )\n"
        "RETURN\n"
        "    CALCULATE ( [Defects Found], 'Evaluation Runs'[Run ID] = LatestRunID )",
        "Defects found by the most recent run only. Use this rather than "
        "Defects Found when asking what is wrong now, because Defects Found "
        "counts the same recurring problem once per run.",
        "#,##0", DEFECTS,
    ),
    Measure(
        "Defects", "Auto Appliable Defects",
        "CALCULATE ( [Defects Found], 'Defects'[Auto Appliable] = TRUE () )",
        "Defects whose proposed fix is safe enough to apply automatically. "
        "The loop still asks a person first; this only says it could not.",
        "#,##0", DEFECTS,
    ),

    # ---- Approvals -------------------------------------------------------
    Measure(
        "Approvals", "Decisions Made",
        "COUNTROWS ( 'Approvals' )",
        "Human decisions recorded, approvals and rejections together.",
        "#,##0", APPROVALS,
    ),
    Measure(
        "Approvals", "Approved",
        'CALCULATE ( [Decisions Made], \'Approvals\'[Decision] = "approved" )',
        "Instructions a person agreed to. An approval authorises a change; it "
        "is not the change itself.",
        "#,##0", APPROVALS,
    ),
    Measure(
        "Approvals", "Rejected",
        'CALCULATE ( [Decisions Made], \'Approvals\'[Decision] = "rejected" )',
        "Proposed instructions a person turned down.",
        "#,##0", APPROVALS,
    ),
    Measure(
        "Approvals", "Approval Rate",
        "DIVIDE ( [Approved], [Decisions Made] )",
        "Share of decisions that were approvals. A rate near 100% usually "
        "means the proposals are being rubber-stamped rather than read.",
        "0.0%", APPROVALS,
    ),
    Measure(
        "Approvals", "Awaiting Mirror",
        "CALCULATE ( [Approved], ISBLANK ( 'Approvals'[Mirrored Time] ) )",
        "Approvals that have not yet reached the eventhouse that triggers the "
        "remediation notebook. Anything here older than a few minutes means "
        "the mirror is not running, so the decision never fired.",
        "#,##0", APPROVALS,
    ),
    Measure(
        "Approvals", "Awaiting Apply",
        "VAR ApprovedDecisions =\n"
        '    CALCULATETABLE ( \'Approvals\', \'Approvals\'[Decision] = "approved" )\n'
        "RETURN\n"
        "    COUNTROWS (\n"
        "        FILTER (\n"
        "            ApprovedDecisions,\n"
        "            COALESCE (\n"
        "                CALCULATE (\n"
        "                    COUNTROWS ( 'Remediations' ),\n"
        "                    'Remediations'[Persisted] = TRUE ()\n"
        "                ),\n"
        "                0\n"
        "            ) = 0\n"
        "        )\n"
        "    )",
        "Approved instructions that have not been written anywhere yet. This "
        "is the work queue, and it is derived rather than stored so it cannot "
        "disagree with what actually happened.",
        "#,##0", APPROVALS,
    ),

    # ---- Remediation -----------------------------------------------------
    Measure(
        "Remediations", "Remediations Applied",
        "CALCULATE ( COUNTROWS ( 'Remediations' ), 'Remediations'[Persisted] = TRUE () )",
        "Approved instructions that were really written to a semantic model "
        "or data agent. Rehearsals are excluded.",
        "#,##0", REMEDIATION,
    ),
    Measure(
        "Remediations", "Remediations Verified",
        "CALCULATE (\n"
        "    COUNTROWS ( 'Remediations' ),\n"
        "    'Remediations'[Persisted] = TRUE (),\n"
        "    'Remediations'[Verified] = TRUE ()\n"
        ")",
        "Applied fixes that a later run re-asked and confirmed. This is the "
        "only measure in the model that says a fix worked.",
        "#,##0", REMEDIATION,
    ),
    Measure(
        "Remediations", "Verified Fix %",
        "DIVIDE ( [Remediations Verified], [Remediations Applied] )",
        "Share of applied fixes that a later run proved worked. A low value "
        "means the loop is changing things without evidence that it helped.",
        "0.0%", REMEDIATION,
    ),

    # ---- Feedback --------------------------------------------------------
    Measure(
        "Feedback", "Feedback Items",
        "COUNTROWS ( 'Feedback' )",
        "Comments left by report readers about an answer.",
        "#,##0", FEEDBACK,
    ),
    Measure(
        "Feedback", "Negative Feedback",
        'CALCULATE ( [Feedback Items], \'Feedback\'[Verdict] IN { "wrong", "misleading" } )',
        "Feedback saying an answer was wrong or misleading. This is evidence "
        "a defect may exist, never an approval to change anything.",
        "#,##0", FEEDBACK,
    ),
    Measure(
        "Feedback", "Untriaged Feedback",
        'CALCULATE ( [Feedback Items], \'Feedback\'[Triage Status] = "new" )',
        "Feedback nobody has looked at yet.",
        "#,##0", FEEDBACK,
    ),

    # ---- Report bindings -------------------------------------------------
    #
    # The approval button passes the selected question to the user data
    # function. Binding to the Question ID column would need an aggregation
    # like First or Max, which silently picks one row out of however many are
    # selected and records a decision against a question the approver did not
    # mean. SELECTEDVALUE returns blank unless exactly one question is in
    # context, so an ambiguous selection cannot be approved at all.
    #
    # It sits at the root of the Questions table rather than in a display
    # folder, on purpose. It was in one called "Report bindings", which is
    # tidier and put the one field somebody needs in the middle of a portal
    # dialog one expand deeper than the columns they were already looking at.
    # Findability wins over tidiness for a field that has exactly one job.
    Measure(
        "Questions", "Selected Question ID",
        "SELECTEDVALUE ( 'Questions'[Question ID] )",
        "The question currently selected in the approval queue, so the "
        "approval button can pass it to the user data function. Blank unless "
        "exactly one question is selected, which stops a decision being "
        "recorded against an ambiguous selection. This is report plumbing "
        "rather than an analysis measure.",
        "", "",
    ),
]


# --------------------------------------------------------------------------
# TMDL
# --------------------------------------------------------------------------

def quote(name: str) -> str:
    """TMDL quotes an object name only when it is not a bare identifier."""
    if name and all(c.isalnum() or c == "_" for c in name) and not name[0].isdigit():
        return name
    return f"'{name}'"


def described(text: str, indent: str) -> list[str]:
    """TMDL writes a description as /// lines above the declaration.

    Not as a `description:` property. Fabric rejects the property form with
    "description is not a supported property in the current context", which is
    a confusing way to say the wrong syntax was used.
    """
    return [f"{indent}/// {line}" for line in wrap(text, 90)] if text else []


def column_tmdl(table: Table, column: Column) -> list[str]:
    lines = described(column.description, "\t")
    lines.append(f"\tcolumn {quote(column.name)}")
    lines.append(f"\t\tdataType: {column.dtype}")
    if column.hidden:
        lines.append("\t\tisHidden")
    if column.format_string:
        lines.append(f"\t\tformatString: {column.format_string}")
    lines.append(f"\t\tlineageTag: {stable_id(f'{table.source}/{column.source}')}")
    lines.append(f"\t\tsourceLineageTag: {column.source}")
    lines.append(f"\t\tsummarizeBy: {column.summarize_by}")
    lines.append(f"\t\tsourceColumn: {column.source}")
    if column.folder:
        lines.append(f"\t\tdisplayFolder: {column.folder}")
    lines.append("")
    lines.append("\t\tannotation SummarizationSetBy = User")
    lines.append("")
    return lines


def measure_tmdl(measure: Measure) -> list[str]:
    body = measure.expression.strip().splitlines()
    lines = described(measure.description, "\t")
    lines.append(f"\tmeasure {quote(measure.name)} =")
    lines += [f"\t\t\t{line}" if line.strip() else "" for line in body]
    if measure.format_string:
        lines.append(f"\t\tformatString: {measure.format_string}")
    lines.append(f"\t\tlineageTag: {stable_id('measure/' + measure.name)}")
    if measure.folder:
        lines.append(f"\t\tdisplayFolder: {measure.folder}")
    lines.append("")
    return lines


def table_tmdl(table: Table) -> str:
    lines = described(table.description, "")
    lines.append(f"table {quote(table.name)}")
    lines.append(f"\tlineageTag: {stable_id('table/' + table.source)}")
    lines.append(f"\tsourceLineageTag: [dbo].[{table.source}]")
    lines.append("")

    for measure in [m for m in MEASURES if m.table == table.name]:
        lines += measure_tmdl(measure)

    for column in table.columns:
        lines += column_tmdl(table, column)

    lines.append(f"\tpartition {quote(table.name)} = entity")
    lines.append("\t\tmode: directLake")
    lines.append("\t\tsource")
    lines.append(f"\t\t\tentityName: {table.source}")
    lines.append("\t\t\tschemaName: dbo")
    lines.append(f"\t\t\texpressionSource: {quote(EXPRESSION_NAME)}")
    lines.append("")
    return "\n".join(lines)


def relationships_tmdl() -> str:
    lines: list[str] = []
    for rel in RELATIONSHIPS:
        name = stable_id(
            f"rel/{rel.from_table}.{rel.from_column}->{rel.to_table}.{rel.to_column}"
        )
        lines.append(f"relationship {name}")
        if not rel.active:
            lines.append("\tisActive: false")
        lines.append(
            f"\tfromColumn: {quote(rel.from_table)}.{quote(rel.from_column)}"
        )
        lines.append(f"\ttoColumn: {quote(rel.to_table)}.{quote(rel.to_column)}")
        lines.append("")
    return "\n".join(lines)


def model_tmdl() -> str:
    lines = [
        "model Model",
        "\tculture: en-US",
        "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tsourceQueryCulture: en-US",
        # discourageImplicitMeasures is deliberately NOT set here.
        #
        # It was, and it broke the thing this model exists to enable. A
        # translytical task flow binds a data function parameter through
        # conditional formatting, which needs an aggregation, and the flag
        # switches implicit aggregations off model-wide. Every column greys
        # out in the picker and Power BI says "a measure is required here",
        # which is true and unhelpful.
        #
        # What it was protecting against is already handled better. The danger
        # is summing a per-run score across runs, and every one of those
        # columns is hidden, so nobody can drag it onto anything. The visible
        # numeric columns are Question Number, Attempt Number and Fix Tier;
        # summing those is meaningless rather than misleading.
        #
        # So the flag was buying almost nothing and costing the report's main
        # interaction. Selected Question ID remains the better binding and is
        # right there at the top of the Questions table.
        "\tdataAccessOptions",
        "\t\tlegacyRedirects",
        "\t\treturnErrorValuesAsNull",
        "",
        f"annotation PBI_QueryOrder = [\"{EXPRESSION_NAME}\"]",
        "",
        "annotation PBI_ProTooling = [\"DirectLakeOnOneLakeInWeb\"]",
        "",
    ]
    for table in TABLES:
        lines.append(f"ref table {quote(table.name)}")
    lines.append("")
    return "\n".join(lines)


def expressions_tmdl(sql_database_id: str) -> str:
    url = (
        "https://onelake.dfs.fabric.microsoft.com/"
        f"{WORKSPACE_ID}/{sql_database_id}"
    )
    return "\n".join([
        f"expression {quote(EXPRESSION_NAME)} =",
        "\t\tlet",
        f'\t\t    Source = AzureStorage.DataLake("{url}", '
        "[HierarchicalNavigation=true])",
        "\t\tin",
        "\t\t    Source",
        f"\tlineageTag: {stable_id('expression/directlake')}",
        "",
        "\tannotation PBI_IncludeFutureArtifacts = False",
        "",
    ])


PBISM = {
    "$schema": (
        "https://developer.microsoft.com/json-schemas/fabric/item/"
        "semanticModel/definitionProperties/1.0.0/schema.json"
    ),
    "version": "4.2",
    "settings": {},
}

# updateMetadata=True is what lets this set the item's description, and Fabric
# rejects that flag unless the .platform part comes with it.
PLATFORM = {
    "$schema": (
        "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/"
        "platformProperties/2.0.0/schema.json"
    ),
    "metadata": {
        "type": "SemanticModel",
        "displayName": AGENTEVALS_MODEL_NAME,
        "description": (
            "How accurate the Contoso Coffee AI surfaces are, and what is "
            "being done about it. Reads the SQL database that holds the "
            "evaluation loop's state: the question bank, every run and "
            "attempt, the defects found, the approvals given and the fixes "
            "applied."
        ),
    },
    "config": {
        "version": "2.0",
        "logicalId": "00000000-0000-0000-0000-000000000000",
    },
}


def build(sql_database_id: str) -> dict[str, str]:
    """Every TMDL part, as path -> text."""
    parts = {
        ".platform": json.dumps(PLATFORM, indent=2),
        "definition.pbism": json.dumps(PBISM, indent=2),
        "definition/database.tmdl": "database\n\tcompatibilityLevel: 1606\n",
        "definition/model.tmdl": model_tmdl(),
        "definition/relationships.tmdl": relationships_tmdl(),
        "definition/expressions.tmdl": expressions_tmdl(sql_database_id),
    }
    for table in TABLES:
        parts[f"definition/tables/{table.name}.tmdl"] = table_tmdl(table)
    return parts


# --------------------------------------------------------------------------
# measures.dax, for people rather than for Fabric
# --------------------------------------------------------------------------

def build_measures_doc() -> str:
    lines = [
        "// AgentEvals - DAX measures for the agent accuracy semantic model",
        "//",
        "// GENERATED by validation/build_agentevals_model.py. Do not edit.",
        "//",
        "// Table and column names are the model names, not the SQL names. The",
        "// database still has dbo.runs with a score column; the model calls it",
        "// Evaluation Runs and hides the raw column behind these measures, so",
        "// that nothing can sum a per-run score across runs.",
        "//",
        "// Every measure has a description. Copilot reads the first 200",
        f"// characters, so the business meaning comes first. {len(MEASURES)} measures.",
        "",
    ]
    for folder in (SCORE, QUALITY, DEFECTS, APPROVALS, REMEDIATION, FEEDBACK):
        members = [m for m in MEASURES if m.folder == folder]
        if not members:
            continue
        lines.append("// " + "-" * 73)
        lines.append(f"// {folder}")
        lines.append("// " + "-" * 73)
        lines.append("")
        for measure in members:
            for chunk in wrap(f"Description: {measure.description}"):
                lines.append(f"// {chunk}")
            lines.append(f"{measure.name} =")
            lines += measure.expression.strip().splitlines()
            lines.append("")

    # Measures deliberately left at the root of their table, so that a person
    # hunting for one in a portal dialog does not have to expand a folder.
    rootless = [m for m in MEASURES if not m.folder]
    if rootless:
        lines.append("// " + "-" * 73)
        lines.append("// Report bindings, at the root of their table on purpose")
        lines.append("// " + "-" * 73)
        lines.append("")
        for measure in rootless:
            for chunk in wrap(f"Description: {measure.description}"):
                lines.append(f"// {chunk}")
            lines.append(f"{measure.name} =")
            lines += measure.expression.strip().splitlines()
            lines.append("")
    return "\n".join(lines) + "\n"


def wrap(text: str, width: int = 74) -> list[str]:
    words, out, line = text.split(), [], ""
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out


# --------------------------------------------------------------------------
# Fabric REST
# --------------------------------------------------------------------------

def token() -> str:
    result = subprocess.run(
        ["az", "account", "get-access-token", "--resource", FABRIC_API,
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, shell=True, check=True,
    )
    return result.stdout.strip()


def call(method: str, url: str, body: dict | None = None) -> tuple[int, dict, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {token()}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            raw = response.read().decode("utf-8")
            parsed = json.loads(raw) if raw.strip() else {}
            return response.status, (parsed or {}), dict(response.headers)
    except urllib.error.HTTPError as exc:
        raise SystemExit(
            f"HTTP {exc.code} {method} {url}\n"
            + exc.read().decode("utf-8", errors="replace")[:1500]
        ) from None


def find_item(item_type: str, name: str) -> str | None:
    _, payload, _ = call(
        "GET", f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/items?type={item_type}"
    )
    for item in payload.get("value", []):
        if item.get("displayName") == name:
            return item["id"]
    return None


def wait(headers: dict) -> None:
    operation_id = headers.get("x-ms-operation-id")
    if not operation_id:
        return
    for _ in range(60):
        _, state, _ = call("GET", f"{FABRIC_API}/v1/operations/{operation_id}")
        status = state.get("status")
        if status == "Succeeded":
            return
        if status in {"Failed", "Undetermined"}:
            raise SystemExit(f"update failed: {state}")
        time.sleep(5)
    raise SystemExit("timed out waiting for the update to finish")


def apply(parts: dict[str, str]) -> int:
    model_id = find_item("SemanticModel", AGENTEVALS_MODEL_NAME)
    if not model_id:
        raise SystemExit(
            f"no semantic model called {AGENTEVALS_MODEL_NAME} in this "
            "workspace. Create it from the SQL database first, or set "
            "FABRIC_AGENTEVALS_MODEL_NAME."
        )

    print(f"updating {AGENTEVALS_MODEL_NAME} ({model_id}) with {len(parts)} parts")
    _, _, headers = call(
        "POST",
        f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/semanticModels/"
        f"{model_id}/updateDefinition?updateMetadata=True",
        {"definition": {
            "format": "TMDL",
            "parts": [
                {"path": path,
                 "payload": base64.b64encode(text.encode("utf-8")).decode("ascii"),
                 "payloadType": "InlineBase64"}
                for path, text in parts.items()
            ],
        }},
    )
    wait(headers)
    print("applied")
    reframe(model_id)
    return verify(model_id)


def reframe(model_id: str) -> None:
    """Make the new definition the one the query engine actually serves.

    updateDefinition changes the stored model immediately and the running one
    not at all. Until the model is reframed, DAX still resolves the old names:
    'Evaluation Runs' comes back as "cannot find table" while the metadata
    already lists it. That looks exactly like a broken deployment and is not
    one, so this is done here rather than left as a step to remember.
    """
    print("reframing")
    request = urllib.request.Request(
        f"{POWERBI_API}/v1.0/myorg/groups/{WORKSPACE_ID}"
        f"/datasets/{model_id}/refreshes",
        data=json.dumps({"type": "full"}).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {powerbi_token()}",
                 "Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(request, timeout=180).close()
    except urllib.error.HTTPError as exc:
        raise SystemExit(
            f"could not reframe the model: HTTP {exc.code}\n"
            + exc.read().decode("utf-8", errors="replace")[:400]
        ) from None
    time.sleep(15)


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------
#
# A definition that imports cleanly is not a definition that works. Fabric
# accepts a measure whose DAX does not compile and leaves it in an error
# state, where it is invisible until somebody drops it on a visual. Two real
# ones got through the first apply of this file: a VAR called `Current`, which
# is a reserved word, and a table VAR referenced as if it were a table.
#
# So the script evaluates every measure afterwards. Evaluating is a stronger
# check than reading a state flag, and it is the only one available: the
# executeQueries endpoint refuses INFO.MEASURES and friends, so the model
# cannot be asked to describe itself over REST. The structural properties
# those DMVs would have shown, descriptions and summarizeBy, are asserted
# offline instead by test_agentevals_model.py, which reads the same spec.

POWERBI_API = "https://api.powerbi.com"

# The Power BI REST audience is not the same string as its hostname. Asking
# for a token for https://api.powerbi.com fails outright.
POWERBI_SCOPE = "https://analysis.windows.net/powerbi/api"


def powerbi_token() -> str:
    if not _TOKEN_CACHE:
        result = subprocess.run(
            ["az", "account", "get-access-token", "--resource", POWERBI_SCOPE,
             "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, shell=True, check=True,
        )
        _TOKEN_CACHE.append(result.stdout.strip())
    return _TOKEN_CACHE[0]


_TOKEN_CACHE: list[str] = []


def query(model_id: str, dax: str) -> tuple[list[dict], str]:
    """Run one DAX query. Returns (rows, error), never raises."""
    body = {"queries": [{"query": dax}],
            "serializerSettings": {"includeNulls": True}}
    request = urllib.request.Request(
        f"{POWERBI_API}/v1.0/myorg/groups/{WORKSPACE_ID}"
        f"/datasets/{model_id}/executeQueries",
        data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {powerbi_token()}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload["results"][0]["tables"][0]["rows"], ""
    except urllib.error.HTTPError as exc:
        return [], exc.read().decode("utf-8", errors="replace")[:400]


def verify(model_id: str) -> int:
    """Check the deployed model, from the outside, the way a report sees it."""
    print()
    problems = 0

    # Table names first, and they are not a formality.
    #
    # A Direct Lake schema sync can reset table names to the source names,
    # turning 'Evaluation Runs' back into 'runs'. When that happened, Fabric
    # rewrote every measure to match, so all 36 still evaluated and this
    # function reported a clean model while every visual in the report showed
    # "Something's wrong with one or more fields". A report binds by name, and
    # nothing else here was checking the names.
    columns = ", ".join(
        f"\"{table.name}\", COUNTROWS ( '{table.name}' )" for table in TABLES
    )
    _, error = query(model_id, f"EVALUATE ROW ( {columns} )")
    if error:
        print("at least one table name does not resolve. Checking each.")
        for table in TABLES:
            _, failure = query(
                model_id, f"EVALUATE ROW ( \"n\", COUNTROWS ( '{table.name}' ) )")
            if failure:
                problems += 1
                print(f"  {table.name} is missing. The source name is "
                      f"{table.source}, so a schema sync has probably reset "
                      "it. Re-run this script with --apply.")
    else:
        print(f"all {len(TABLES)} table names resolve")

    # Then the measures. Evaluating is a stronger check than reading a state
    # flag, and it is the only one available: the executeQueries endpoint
    # refuses INFO.MEASURES, so the model cannot be asked to describe itself.
    everything = ", ".join(f'"{m.name}", [{m.name}]' for m in MEASURES)
    _, error = query(model_id, f"EVALUATE ROW ( {everything} )")
    if not error:
        print(f"all {len(MEASURES)} measures evaluate")
        return 1 if problems else 0

    print("at least one measure failed. Checking them one at a time.")
    for measure in MEASURES:
        _, failure = query(model_id, f'EVALUATE ROW ( "v", [{measure.name}] )')
        if failure:
            problems += 1
            print(f"  {measure.name}")
    if problems:
        print(f"\n{problems} problem(s). Fix the spec and re-run with --apply.")
        return 1
    print("no single measure failed, so the combined query is the problem:")
    print(f"  {error}")
    return 1


def write_local(parts: dict[str, str]) -> None:
    for path, text in parts.items():
        target = OUT / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    print(f"wrote {len(parts)} parts to {DEFINITION.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="push the definition to the model in Fabric")
    parser.add_argument("--verify", action="store_true",
                        help="check the deployed model, change nothing")
    parser.add_argument("--docs", action="store_true",
                        help="write semantic-model/agentevals/measures.dax only")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    MEASURES_DOC.write_text(build_measures_doc(), encoding="utf-8")
    print(f"wrote {MEASURES_DOC.relative_to(ROOT)} ({len(MEASURES)} measures)")
    if args.docs:
        return 0

    require("FABRIC_WORKSPACE_ID")

    if args.verify:
        model_id = find_item("SemanticModel", AGENTEVALS_MODEL_NAME)
        if not model_id:
            raise SystemExit(f"no model called {AGENTEVALS_MODEL_NAME}")
        return verify(model_id)

    sql_database_id = find_item("SQLDatabase", SQL_DATABASE_NAME)
    if not sql_database_id:
        raise SystemExit(
            f"no SQL database called {SQL_DATABASE_NAME} in this workspace. "
            "Run python validation/build_sql_schema.py --create first."
        )

    parts = build(sql_database_id)
    write_local(parts)
    return apply(parts) if args.apply else 0


if __name__ == "__main__":
    sys.exit(main())
