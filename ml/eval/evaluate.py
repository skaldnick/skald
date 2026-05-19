"""
Compare fine-tuned model outputs against baseline on the same test prompts.
Run after training to see what changed.

Run: python ml/eval/evaluate.py
Outputs: ml/eval/comparison.jsonl  (baseline vs. fine-tuned, side by side)

Prerequisites:
  pip install mlx-lm
  ml/eval/baseline_outputs.jsonl must exist (run baseline.py first)
  ml/models/adapters must exist (run training/train.sh first)
"""

import json
from pathlib import Path

MODEL = "Qwen/Qwen2.5-7B-Instruct"
ADAPTER_PATH = "ml/models/adapters"
BASELINE_FILE = Path("ml/eval/baseline_outputs.jsonl")
OUTPUT_FILE = Path("ml/eval/comparison.jsonl")


def main():
    try:
        from mlx_lm import load, generate
    except ImportError:
        print("mlx-lm not installed. Run: pip install mlx-lm")
        return

    if not BASELINE_FILE.exists():
        print(f"{BASELINE_FILE} not found. Run baseline.py first.")
        return

    baseline = [json.loads(l) for l in BASELINE_FILE.read_text().splitlines()]

    print(f"Loading fine-tuned model ({MODEL} + {ADAPTER_PATH})...")
    model, tokenizer = load(MODEL, adapter_path=ADAPTER_PATH)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        for record in baseline:
            prompt = record["prompt"]
            print(f"\nPrompt: {prompt[:60]}...")
            finetuned = generate(model, tokenizer, prompt=prompt, max_tokens=400, verbose=False)
            row = {
                "prompt": prompt,
                "baseline": record["output"],
                "finetuned": finetuned,
            }
            f.write(json.dumps(row) + "\n")
            print(f"  Baseline:  {record['output'][:100]}...")
            print(f"  Fine-tuned: {finetuned[:100]}...")

    print(f"\nComparison saved to {OUTPUT_FILE}")
    print("Review manually and score each pair to measure improvement.")


if __name__ == "__main__":
    main()
