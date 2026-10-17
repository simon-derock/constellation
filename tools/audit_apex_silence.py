import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from constellation.brain.absence import check_absence
from constellation.ingest.apex import raw_events

# checks absence detection against EpistemicBench SILENCE keys: the answer and the search space; never tuning input


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="audit Apex absence detection")
    parser.add_argument("--raw", type=Path, default=Path("data/raw/apex"))
    args = parser.parse_args(argv)
    events = raw_events(args.raw / "corpus/corpus-00000.parquet")
    by_id = {e.mongo_id: e for e in events}
    lines = (args.raw / "questions/eval_questions.jsonl").read_text().splitlines()
    questions = [q for q in map(json.loads, lines) if q["question_type"] == "SILENCE"]
    answers = spaces = 0
    for q in questions:
        gt = q["ground_truth"]
        got = check_absence(events, by_id[q["trigger_event_id"]], q["expected_response_type"])
        answers += got.responded == gt["answer"]
        spaces += set(got.search_space) >= set(q["expected_search_space"])
        if got.responded != gt["answer"] or not set(got.search_space) >= set(q["expected_search_space"]):
            print(f"  differs {q['question_id']}: key={gt['answer']} got={got.responded}")
    total = len(questions)
    print(f"answer agreement {answers}/{total} · search space covers the key's {spaces}/{total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
