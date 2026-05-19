"""
Export Skald editorial feedback as DPO preference pairs for mlx-lm training.

Reads from data/feedback/ and produces JSONL files in ml/data/pairs/:
  train.jsonl  — training split (~90%)
  valid.jsonl  — validation split (~10%)

Each record:
  {"prompt": "<system+user prompt>", "chosen": "<edited text>", "rejected": "<original draft>"}

Run: python ml/data/export_pairs.py
"""

import json
import random
from pathlib import Path

FEEDBACK_DIR = Path("data/feedback")
OUTPUT_DIR = Path("ml/data/pairs")
VALID_SPLIT = 0.1


def load_feedback_files():
    """Load all feedback records. Schema TBD — implement once feedback format is stable."""
    raise NotImplementedError(
        "Implement once data/feedback/ schema is confirmed. "
        "Each record needs: original_draft, edited_draft, approved (bool), prompt."
    )


def to_dpo_pair(record: dict) -> dict | None:
    """Convert a feedback record to a DPO (prompt, chosen, rejected) triple."""
    if not record.get("approved"):
        return None
    original = record["original_draft"].strip()
    edited = record["edited_draft"].strip()
    if original == edited:
        return None  # no edit = no signal
    return {
        "prompt": record["prompt"],
        "chosen": edited,
        "rejected": original,
    }


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    records = load_feedback_files()
    pairs = [p for r in records if (p := to_dpo_pair(r)) is not None]

    if not pairs:
        print("No pairs found. Check feedback data and to_dpo_pair() logic.")
        return

    random.shuffle(pairs)
    split = max(1, int(len(pairs) * VALID_SPLIT))
    valid, train = pairs[:split], pairs[split:]

    for name, data in [("train", train), ("valid", valid)]:
        path = OUTPUT_DIR / f"{name}.jsonl"
        with open(path, "w") as f:
            for pair in data:
                f.write(json.dumps(pair) + "\n")
        print(f"Wrote {len(data)} pairs → {path}")


if __name__ == "__main__":
    main()
