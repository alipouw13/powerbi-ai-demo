"""Run the question bank against a live Fabric data agent and score it.

This is the laptop version of the loop. It proves the harness against real
agent prose before any of it is trusted inside a notebook. The notebook does
the same work and adds the Delta writes and the alerting.

Usage:

    python validation/run_eval.py --workspace <id> --agent <id> --repeat 3

Requires the `mcp` package and either a Fabric notebook identity or an
Azure CLI login with access to the workspace.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_client as ac  # noqa: E402
import eval_harness as eh  # noqa: E402
import ground_truth as gt  # noqa: E402

BANK_PATH = Path(__file__).resolve().parent / "question-bank.md"


def run(
    workspace_id: str,
    agent_id: str,
    repeat: int,
    concurrency: int,
    only: list[str] | None = None,
) -> tuple[list[eh.QuestionResult], dict, list[eh.FixProposal]]:
    questions = eh.parse_question_bank(BANK_PATH.read_text(encoding="utf-8"))
    if only:
        wanted = {q.upper() for q in only}
        questions = [q for q in questions if q.id in wanted]

    expectations = eh.build_expectations(gt.compute_raw())
    client = ac.DataAgentClient(workspace_id, agent_id, concurrency=concurrency)

    results = {q.id: eh.QuestionResult(q.id, q.kind) for q in questions}

    for attempt in range(1, repeat + 1):
        print(f"\n--- attempt {attempt} of {repeat} ---", flush=True)
        replies = client.ask([q.text for q in questions])

        for question, reply in zip(questions, replies):
            expected = expectations[question.id]
            if reply.error:
                grade, detail = eh.ERRORED, f"transport error: {reply.error[:200]}"
            else:
                grade, detail = eh.grade_answer(expected, reply.answer)

            results[question.id].attempts.append(
                eh.Attempt(
                    question_id=question.id,
                    attempt=attempt,
                    answer=reply.answer,
                    grade=grade,
                    detail=detail,
                    latency_ms=reply.latency_ms,
                )
            )
            flag = "ok  " if grade == eh.CORRECT else "FAIL"
            print(f"  {flag} {question.id} {grade:<15} {detail[:90]}", flush=True)

    ordered = [results[q.id] for q in questions]
    summary = eh.score_run(ordered)
    proposals = eh.propose_fixes(ordered, expectations)
    return ordered, summary, proposals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--only", nargs="*", help="limit to specific question ids")
    parser.add_argument("--dump", help="write full results to this JSON path")
    args = parser.parse_args()

    results, summary, proposals = run(
        args.workspace, args.agent, args.repeat, args.concurrency, args.only
    )

    print("\n" + "=" * 70)
    print(f"score {summary['score']} / {summary['max_score']}")
    print(f"flakes            : {summary['flake_questions'] or 'none'}")
    print(f"stable failures   : {summary['failure_questions'] or 'none'}")
    print(f"errored questions : {summary['errored_questions'] or 'none'}")
    print(f"guardrails lost   : {summary['guardrails_lost'] or 'none'}")
    print(f"agent errors      : {summary['error_attempts']} / {summary['attempt_count']}")
    print(f"median latency ms : {summary['median_latency_ms']}")

    if proposals:
        print("\nproposed fixes, none of which are applied automatically:")
        for p in proposals:
            print(f"  {p.question_id} tier {p.tier} -> {p.fix_target}")
            print(f"      {p.rationale}")

    for alert in eh.alert_conditions(summary, None):
        print(f"\nALERT [{alert['severity']}] {alert['condition']}: {alert['detail']}")

    if args.dump:
        payload = {
            "summary": summary,
            "results": [
                {
                    "question_id": r.question_id,
                    "kind": r.kind,
                    "classification": r.classification,
                    "attempts": [
                        {
                            "attempt": a.attempt,
                            "grade": a.grade,
                            "detail": a.detail,
                            "latency_ms": a.latency_ms,
                            "answer": a.answer,
                        }
                        for a in r.attempts
                    ],
                }
                for r in results
            ],
        }
        Path(args.dump).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {args.dump}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
