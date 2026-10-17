import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from constellation.brain.causality import counterfactual, index_causal_links
from constellation.ingest.apex import raw_events

# checks the causal index against EpistemicBench COUNTERFACTUAL keys; disagreements are evidence, never tuning input


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="audit the Apex causal index")
    parser.add_argument("--raw", type=Path, default=Path("data/raw/apex"))
    args = parser.parse_args(argv)
    edges = index_causal_links(raw_events(args.raw / "corpus/corpus-00000.parquet"))
    keys = {(e.link_type, e.cause, e.effect) for e in edges}
    lines = (args.raw / "questions/eval_questions.jsonl").read_text().splitlines()
    questions = [q for q in map(json.loads, lines) if q["question_type"] == "COUNTERFACTUAL"]
    present = agree = 0
    for q in questions:
        gt = q["ground_truth"]
        mech, cause, effect = gt["causal_mechanism"], gt["cause_event_id"], gt["effect_event_id"]
        present += (mech, cause, effect) in keys
        answer = counterfactual(edges, mech, cause, effect)
        if answer.changed == gt["outcome_changed"]:
            agree += 1
            continue
        sample = ", ".join(answer.alternatives[:3])
        print(
            f"  disputes {q['question_id']}: key changed={gt['outcome_changed']}; index has "
            f"{len(answer.alternatives)} same-mechanism alternatives ({sample})"
        )
    print(
        f"edges {len(edges)} · questioned links present {present}/{len(questions)} · "
        f"outcome agreement {agree}/{len(questions)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
