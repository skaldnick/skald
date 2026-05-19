# ml/ — Fine-tuning pipeline

Experimental: fine-tuning an open-weights model on Skald's editorial feedback data
to produce a local model that writes in Skald's house style.

This is separate from the live briefing pipeline. Nothing here affects production
until explicitly wired into `generator/client.py`.

## Approach

- **Model:** Qwen2.5-7B-Instruct (start here on 16GB M3) or Qwen2.5-14B-Instruct
- **Method:** LoRA fine-tuning via [mlx-lm](https://github.com/ml-explore/mlx-lm) (Apple Silicon)
- **Training signal:** DPO (Direct Preference Optimization) on (preferred, rejected) pairs
  derived from Skald's editorial diffs and approve/reject decisions

## Data source

Skald's editorial sessions produce two signals usable as preference pairs:
- **Edit diffs** — original AI draft vs. editor-revised version (implicit preferred/rejected)
- **Approve/reject** — whole-story accept or reject decisions

`data/export_pairs.py` converts these into the JSONL format mlx-lm expects.

## Status

Not yet started. Prerequisite: accumulate ~500 preference pairs through sustained
editorial use of the dashboard (roughly 6–12 months at Mon–Fri cadence).

Near-term goal: get baseline inference running so outputs can be compared once
training data is ready.

## Directory layout

```
data/        Scripts to export feedback → DPO pairs; exported JSONL files (gitignored)
training/    mlx-lm config and training scripts
eval/        Evaluation scripts and held-out test prompts
models/      Local model weights and LoRA adapters (gitignored)
```

## Setup

```bash
pip install mlx-lm
```

## Quickstart — baseline inference

```bash
python ml/eval/baseline.py
```

## Training (when data is ready)

```bash
# 1. Export preference pairs from feedback data
python ml/data/export_pairs.py

# 2. Fine-tune
mlx_lm.lora \
  --model Qwen/Qwen2.5-7B-Instruct \
  --train \
  --data ml/data/pairs/ \
  --batch-size 1 \
  --num-iterations 1000 \
  --adapter-path ml/models/adapters

# 3. Evaluate
python ml/eval/evaluate.py
```
