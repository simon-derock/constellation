import argparse
import json
import os
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from falkordb import FalkorDB

from constellation.agents.epistemic import Question
from constellation.agents.llm import ModelLock, WorkersAI
from constellation.agents.planner import solve
from constellation.agents.toolbox import Perspective, Toolbox
from constellation.brain.roles import roles_from_config
from constellation.eval.epistemic import score, summarize, trajectory
from constellation.graph.read import ReadPort


def question_for_agent(raw: Mapping[str, Any]) -> Question:
    # exactly what the official harness shows an agent: the text, plus the actor frame for PERSPECTIVE
    if raw["question_type"] == "PERSPECTIVE":
        return Question(
            qid=raw["question_id"],
            qtype="PERSPECTIVE",
            text=raw["question_text"],
            actor=raw["actor"],
            day=int(raw["as_of_day"]),
            subsystems=tuple(raw.get("subsystem_access", [])),
        )
    return Question(qid=raw["question_id"], qtype=raw["question_type"], text=raw["question_text"])


def run_one(
    llm: WorkersAI, port: ReadPort, graph: str, raw: Mapping[str, Any], roles: Mapping[str, str]
) -> dict[str, Any]:
    q = question_for_agent(raw)
    perspective = Perspective(q.actor, roles.get(q.actor, "external"), q.day) if q.qtype == "PERSPECTIVE" else None
    tools = Toolbox(port, graph, perspective)
    before = len(llm.usage)
    start = time.perf_counter()
    agent_run = solve(llm, tools, q)
    cone = tools._cone()[0] if perspective else None
    traj = trajectory(raw, tools.calls, agent_run, cone)
    usage = llm.usage[before:]
    return {
        **score(raw, traj, cone),
        "answer": agent_run.answer,
        "stop_reason": agent_run.stop_reason,
        "strategy_changes": agent_run.strategy_changes,
        "llm_calls": len(usage),
        "prompt_tokens": sum(u.prompt_tokens for u in usage),
        "completion_tokens": sum(u.completion_tokens for u in usage),
        "latency_s": round(time.perf_counter() - start, 2),
        "tools": [
            {"tool": c.tool, "args": dict(c.args), "ids": len(c.result_ids), "proofs": list(c.proofs)}
            for c in tools.calls
        ],
    }


def load_completed(ledger: Path) -> list[dict[str, Any]]:
    # a truncated last line is what a killed run leaves behind; it is dropped, never trusted
    rows: list[dict[str, Any]] = []
    for line in ledger.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            break
    return rows


def remaining(questions: Sequence[Mapping[str, Any]], done: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    finished = {r["question_id"] for r in done}
    return [q for q in questions if q["question_id"] not in finished]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="run EpistemicBench on Constellation and score it with the official scorers"
    )
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=6379)
    parser.add_argument("--graph", default="brain:apex")
    parser.add_argument("--model", default="@cf/openai/gpt-oss-20b")
    parser.add_argument("--questions", type=Path, default=Path("data/raw/apex/questions/eval_questions.jsonl"))
    parser.add_argument("--only", nargs="*", default=[], help="question ids to run")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", type=Path, default=Path("results/raw"))
    parser.add_argument("--resume", type=Path, help="continue an interrupted run from its ledger")
    args = parser.parse_args(argv)
    lock = ModelLock(model=args.model, temperature=0.0, max_tokens=1_024)
    llm = WorkersAI(os.environ["CLOUDFLARE_ACCOUNT_ID"], os.environ["CLOUDFLARE_API_TOKEN"], lock)
    port = ReadPort(FalkorDB(host=args.host, port=args.port))
    roles = roles_from_config(Path("third_party/orgforge/config.yaml"))
    questions = [json.loads(line) for line in args.questions.read_text().splitlines()]
    if args.only:
        questions = [q for q in questions if q["question_id"] in set(args.only)]
    if args.limit:
        questions = questions[: args.limit]
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    ledger = args.resume or args.out / f"epistemic-{stamp}.jsonl"
    rows = load_completed(ledger) if args.resume else []
    questions = remaining(questions, rows)
    with ledger.open("w") as out:
        # rewritten from the good rows only: a killed run's torn last line must not swallow the next row
        for kept in rows:
            out.write(json.dumps(kept) + "\n")
        out.flush()
        for raw in questions:
            row = run_one(llm, port, args.graph, raw, roles)
            rows.append(row)
            # flushed per question: an interrupted run keeps every completed measurement
            out.write(json.dumps(row) + "\n")
            out.flush()
            print(f"{row['question_id'][:60]:60} answer={row['answer_correct']!s:5} combined={row['combined_score']}")
    summary = {"model_lock": lock.sha256, "model": lock.model, "ledger": str(ledger), **summarize(rows)}
    ledger.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
