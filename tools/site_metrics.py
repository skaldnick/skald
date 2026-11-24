"""
Monthly workflow metrics for the "How Skald works" page on vikingmedia.org.

Usage:
    python tools/site_metrics.py > ../vikingmedia-site/site/data/skald_metrics.json

Run tools/check_sync.sh first (see tools/edit_rate.py). Emits one JSON object
with three monthly series, one per stage of the workflow the page credits:

  edit_rate       tools/edit_rate.py's monthly rows (how much the editor changes
                  approved stories, and how many drafted stories are rejected)
  style_rules     house style rules in force at each month end, read from
                  prompts/payments/style_rules.yaml in git history (rules are
                  revised in place, so the file's own dates can't give this)
  auto_corrected  share of drafted stories that generator/revise.py rewrote or
                  replaced before the editor saw them, from output/payments/
"""

import calendar
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from edit_rate import compute  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = "prompts/payments/style_rules.yaml"
DRAFTS_DIR = ROOT / "output" / "payments"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def _rules_in_force(month: str) -> int:
    year, mon = map(int, month.split("-"))
    end = f"{month}-{calendar.monthrange(year, mon)[1]} 23:59"
    commit = _git("rev-list", "-1", f"--before={end}", "HEAD", "--", RULES_PATH).strip()
    if not commit:
        return 0
    rules = yaml.safe_load(_git("show", f"{commit}:{RULES_PATH}")) or []
    return len(rules)


def _auto_corrected() -> dict[str, dict]:
    counts: dict[str, Counter] = defaultdict(Counter)
    for path in sorted(DRAFTS_DIR.glob("*.yaml")):
        try:
            briefing = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError:
            continue
        month = path.stem[:7]
        for story in briefing.get("stories") or []:
            counts[month]["stories"] += 1
            revision = story.get("revision")
            if revision:
                counts[month]["replaced" if revision.get("replaced") else "rewritten"] += 1
    out = {}
    for month, c in counts.items():
        corrected = c["replaced"] + c["rewritten"]
        out[month] = {
            "stories": c["stories"],
            "rewritten": c["rewritten"],
            "replaced": c["replaced"],
            "pct": round(100 * corrected / c["stories"], 1) if c["stories"] else 0.0,
        }
    return out


def main() -> None:
    rows, swaps = compute("month")
    corrected = _auto_corrected()
    json.dump(
        {
            "generated": date.today().isoformat(),
            "slot_swaps_excluded": swaps,
            "feedback_days": len(list((ROOT / "data" / "feedback").glob("*.json"))),
            "months": [
                {
                    **r,
                    "style_rules": _rules_in_force(r["period"]),
                    "auto_corrected": corrected.get(r["period"], {"stories": 0, "rewritten": 0, "replaced": 0, "pct": 0.0}),
                }
                for r in rows
            ],
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
