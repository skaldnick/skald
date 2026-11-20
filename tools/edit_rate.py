"""
Edit-rate metrics: how much the human editor changes the AI draft, over time.

Usage:
    python tools/edit_rate.py                  # monthly table
    python tools/edit_rate.py --by week        # ISO weeks (2026-W37)
    python tools/edit_rate.py --format csv     # or json, for charting/publishing

Reads data/feedback/*.json (written by the dashboard's Save feedback / Publish).
Run tools/check_sync.sh first: the dashboard commits feedback straight to
origin/main, so a stale clone silently under-counts recent periods.

Per period, over approved stories only (rejected stories are never published,
so edits to them say nothing about the published output):
  approved     approved stories with a recorded draft
  touched      % with any change at all to headline/standfirst/body
  substantive  % with SUBSTANTIVE_WORDS or more words changed (filters out
               one-word fixes and typos)
  words        % of all draft words changed, inserted or deleted
  rejected     % of all drafted stories the editor rejected

What "original" means: the draft as the editor first saw it. Since 2026-07-23
that is *after* the automatic style-check and revise passes (generator/
style_check.py, generator/revise.py), so a falling edit rate reflects the prompt,
the learned style rules and the auto-correction pass together, not the prompt
alone.

Excluded from the edit figures:
  - Source lines: the editor can't edit them, and an old dashboard bug made them
    vanish on save, which would otherwise read as an edit.
  - Slot swaps (word similarity below SWAP_THRESHOLD): the draft and final text
    are different stories, because feedback is matched to the draft by position
    and stories occasionally shifted. Those are replacements, not edits, and are
    reported separately.
"""

import argparse
import csv
import difflib
import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

FEEDBACK_DIR = Path(__file__).resolve().parent.parent / "data" / "feedback"
SUBSTANTIVE_WORDS = 10
SWAP_THRESHOLD = 0.15

_SOURCES_LINE = re.compile(r"(?m)^\*Sources?:.*$")


def _words(text: str | None) -> list[str]:
    return _SOURCES_LINE.sub("", text or "").split()


def _period(date_str: str, by: str) -> str:
    if by == "month":
        return date_str[:7]
    year, week, _ = date.fromisoformat(date_str).isocalendar()
    return f"{year}-W{week:02d}"


def compute(by: str = "month") -> tuple[list[dict], int]:
    """Return (one row per period, number of slot swaps excluded)."""
    acc = defaultdict(lambda: defaultdict(int))
    swaps = 0
    for path in sorted(FEEDBACK_DIR.glob("*.json")):
        data = json.loads(path.read_text())
        a = acc[_period(data["date"], by)]
        for story in data.get("stories", []):
            a["drafted"] += 1
            if story.get("decision") == "Reject":
                a["rejected"] += 1
                continue
            if story.get("decision") != "Approve":
                continue
            orig, edited = _words(story.get("original")), _words(story.get("edited"))
            if not orig:
                continue
            sm = difflib.SequenceMatcher(None, orig, edited, autojunk=False)
            if sm.ratio() < SWAP_THRESHOLD:
                swaps += 1
                continue
            changed = sum(
                max(i2 - i1, j2 - j1)
                for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"
            )
            a["approved"] += 1
            a["touched"] += changed > 0
            a["substantive"] += changed >= SUBSTANTIVE_WORDS
            a["words_changed"] += changed
            a["words_total"] += len(orig)

    rows = []
    for period in sorted(acc):
        a = acc[period]
        n = a["approved"]
        pct = lambda x, d: round(100 * x / d, 1) if d else None
        rows.append({
            "period": period,
            "approved": n,
            "touched_pct": pct(a["touched"], n),
            "substantive_pct": pct(a["substantive"], n),
            "words_changed_pct": pct(a["words_changed"], a["words_total"]),
            "rejected_pct": pct(a["rejected"], a["drafted"]),
        })
    return rows, swaps


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--by", choices=["month", "week"], default="month")
    parser.add_argument("--format", choices=["table", "csv", "json"], default="table")
    args = parser.parse_args()

    rows, swaps = compute(args.by)
    if not rows:
        sys.exit(f"No feedback files found in {FEEDBACK_DIR}")

    if args.format == "json":
        print(json.dumps({"by": args.by, "slot_swaps_excluded": swaps, "rows": rows}, indent=2))
    elif args.format == "csv":
        writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    else:
        fmt = lambda v: "-" if v is None else f"{v:.1f}%"
        print(f"{'period':<10} {'approved':>8} {'touched':>8} {'10+ words':>10} {'words':>7} {'rejected':>9}")
        for r in rows:
            print(f"{r['period']:<10} {r['approved']:>8} {fmt(r['touched_pct']):>8} "
                  f"{fmt(r['substantive_pct']):>10} {fmt(r['words_changed_pct']):>7} "
                  f"{fmt(r['rejected_pct']):>9}")
        print(f"\nSlot swaps excluded (draft and final are different stories): {swaps}")


if __name__ == "__main__":
    main()
