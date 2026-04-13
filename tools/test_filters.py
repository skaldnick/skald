"""
Test keyword filter configs against a cached raw snapshot.
Shows per-source pass/cut counts and the actual titles that are cut,
so you can judge whether the filter is too aggressive or too loose.

Usage:
    python tools/test_filters.py [path/to/raw.json] [path/to/filter_config.yaml]

Defaults:
    raw snapshot: data/raw/payments/{today}.json
    filter config: tools/filter_config.yaml (edit this file to iterate)

Filter config format:
    # Sources listed here have keyword filtering applied.
    # Sources not listed pass all entries through.
    # At least one keyword must match in the title or summary (case-insensitive).
    sources:
      Finextra:
        keywords: [open banking, PSD2, PSD3, PSR, instant payments, SEPA, open finance, payment regulation]
      ECB:
        keywords: [payment, open banking, instant payment, SEPA, digital euro]
      EBA:
        keywords: [payment, PSD2, PSD3, open banking, open finance]
      PYMNTS:
        keywords: [UK, EU, Europe, FCA, EBA, ECB, PSD, SEPA, open banking, open finance]
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent

# --- Resolve paths ---
date_str = datetime.now().strftime("%Y-%m-%d")
default_raw = ROOT / "data" / "raw" / "payments" / f"{date_str}.json"
default_config = ROOT / "beats" / "payments_filters.yaml"

raw_path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_raw
config_path = Path(sys.argv[2]) if len(sys.argv) > 2 else default_config

if not raw_path.exists():
    print(f"No raw snapshot found at {raw_path}")
    print("Run:  python tools/fetch_raw.py")
    sys.exit(1)

if not config_path.exists():
    print(f"No filter config found at {config_path}")
    sys.exit(1)

with open(raw_path) as f:
    data = json.load(f)
with open(config_path) as f:
    config = yaml.safe_load(f)

entries = data["entries"]
global_keywords = [kw.lower() for kw in config.get("global", {}).get("keywords", [])]
source_configs = config.get("sources", {})

print(f"Snapshot: {raw_path.name}  ({len(entries)} entries)")
print(f"Config:   {config_path.name}")
print(f"Global keywords: {', '.join(global_keywords)}\n")

# Group by source
by_source: dict[str, list] = {}
for e in entries:
    by_source.setdefault(e["source"], []).append(e)

total_pass = total_cut = 0

for source, source_entries in sorted(by_source.items()):
    src_cfg = source_configs.get(source, {})

    if src_cfg.get("passthrough"):
        print(f"  {source} ({len(source_entries)})  [passthrough — all pass]")
        total_pass += len(source_entries)
        continue

    extra = [kw.lower() for kw in src_cfg.get("keywords", [])]
    keywords = global_keywords + extra
    include_pattern = re.compile("|".join(re.escape(kw) for kw in keywords), re.IGNORECASE)

    global_exclude = [kw.lower() for kw in config.get("global", {}).get("exclude", [])]
    src_exclude = [kw.lower() for kw in src_cfg.get("exclude", [])]
    all_exclude = global_exclude + src_exclude
    exclude_pattern = re.compile("|".join(re.escape(kw) for kw in all_exclude), re.IGNORECASE) if all_exclude else None

    passed, cut = [], []
    for e in source_entries:
        text = f"{e['title']} {e['summary']}"
        if not include_pattern.search(text):
            cut.append(("no keyword match", e))
        elif exclude_pattern and exclude_pattern.search(text):
            cut.append(("excluded: " + exclude_pattern.search(text).group(), e))
        else:
            passed.append(e)

    total_pass += len(passed)
    total_cut += len(cut)
    pct_cut = 100 * len(cut) // len(source_entries) if source_entries else 0

    print(f"  {source} ({len(source_entries)})  pass: {len(passed)}  cut: {len(cut)} ({pct_cut}%)")
    if cut:
        print("    Cut:")
        for reason, e in cut:
            print(f"      - [{reason}] {e['title'][:80]}")
    if passed:
        print("    Pass:")
        for e in passed:
            print(f"      + {e['title'][:90]}")
    print()

print(f"Total — pass: {total_pass}  cut: {total_cut}  ({100 * total_cut // (total_pass + total_cut) if (total_pass + total_cut) else 0}% reduction)")
