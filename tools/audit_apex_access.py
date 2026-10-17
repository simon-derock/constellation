import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from constellation.brain.access import born_days, could_have_known
from constellation.ingest.apex import load_apex

# checks the ported access model against EpistemicBench PERSPECTIVE keys; never a tuning loop


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="audit the ported Apex access model")
    parser.add_argument("--raw", type=Path, default=Path("data/raw/apex"))
    parser.add_argument("--config", type=Path, default=Path("third_party/orgforge/config.yaml"))
    args = parser.parse_args(argv)
    apex = load_apex(args.raw / "corpus/corpus-00000.parquet", args.config)
    born = born_days(apex.events)
    by_id = {e.event_id: e for e in apex.events}
    corpus_ids = frozenset(a.doc_id for a in apex.artifacts)
    questions = [json.loads(line) for line in (args.raw / "questions/eval_questions.jsonl").read_text().splitlines()]
    perspective = [q for q in questions if q["question_type"] == "PERSPECTIVE"]
    disagreements = [
        q["question_id"]
        for q in perspective
        if could_have_known(
            apex.events,
            born,
            q["actor"],
            apex.roles.get(q["actor"], "external"),
            by_id[q["event_id"]],
            q["as_of_day"],
            corpus_ids,
        )
        != q["ground_truth"]["could_actor_have_known"]
    ]
    print(f"agreement {len(perspective) - len(disagreements)}/{len(perspective)}")
    for qid in disagreements:
        print(f"  disagrees: {qid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
