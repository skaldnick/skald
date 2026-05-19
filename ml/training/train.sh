#!/usr/bin/env bash
# LoRA fine-tuning via mlx-lm.
# Run from repo root: bash ml/training/train.sh
#
# Prerequisites:
#   pip install mlx-lm
#   python ml/data/export_pairs.py   (produces ml/data/pairs/train.jsonl + valid.jsonl)

set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen2.5-7B-Instruct}"   # override: MODEL=Qwen/Qwen2.5-14B-Instruct
ADAPTER_PATH="ml/models/adapters"
DATA_DIR="ml/data/pairs"

echo "Model:    $MODEL"
echo "Data:     $DATA_DIR"
echo "Adapters: $ADAPTER_PATH"
echo ""

mlx_lm.lora \
  --model "$MODEL" \
  --train \
  --data "$DATA_DIR" \
  --batch-size 1 \
  --num-iterations 1000 \
  --val-batches 10 \
  --learning-rate 1e-5 \
  --lora-layers 8 \
  --adapter-path "$ADAPTER_PATH" \
  --save-every 100

echo ""
echo "Done. Adapters saved to $ADAPTER_PATH"
echo "Run evaluation: python ml/eval/evaluate.py"
