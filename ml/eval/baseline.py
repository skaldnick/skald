"""
Run baseline inference on the base model (no fine-tuning) against test prompts.
Use this to establish what the model produces before training, so you have
something to compare fine-tuned outputs against.

Run: python ml/eval/baseline.py
Outputs: ml/eval/baseline_outputs.jsonl

Prerequisites: pip install mlx-lm
"""

import json
from pathlib import Path

TEST_PROMPTS = [
    "Write a concise briefing paragraph on the EU's progress toward open banking interoperability.",
    "Write a concise briefing paragraph on recent PSD3 regulatory developments.",
    "Write a concise briefing paragraph on instant payments adoption in Europe.",
]

MODEL = "Qwen/Qwen2.5-7B-Instruct"
OUTPUT_FILE = Path("ml/eval/baseline_outputs.jsonl")


def main():
    try:
        from mlx_lm import load, generate
    except ImportError:
        print("mlx-lm not installed. Run: pip install mlx-lm")
        return

    print(f"Loading {MODEL}...")
    model, tokenizer = load(MODEL)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        for prompt in TEST_PROMPTS:
            print(f"\nPrompt: {prompt[:60]}...")
            output = generate(model, tokenizer, prompt=prompt, max_tokens=400, verbose=False)
            print(f"Output: {output[:120]}...")
            f.write(json.dumps({"prompt": prompt, "output": output}) + "\n")

    print(f"\nBaseline outputs saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
