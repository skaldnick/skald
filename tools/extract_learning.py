"""
Post-session learning tool. Run after each editorial session.

Usage:
    python tools/extract_learning.py              # most recent feedback file
    python tools/extract_learning.py --date 2026-04-14
    python tools/extract_learning.py --all        # all feedback files

What it does:
  1. Automatically updates data/recently_covered.yaml with approved stories.
  2. Calls Claude to propose style rules from editorial diffs and prints them.

Proposed rules are printed to stdout — review them, then add any worth keeping
to prompts/payments/style_rules.yaml and commit.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import anthropic
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
FEEDBACK_DIR = ROOT / "data" / "feedback"
RECENTLY_COVERED_PATH = ROOT / "data" / "recently_covered.yaml"
STYLE_RULES_PATH = ROOT / "prompts" / "payments" / "style_rules.yaml"


def extract_headline(story_text: str) -> str:
    match = re.search(r"\*\*(.+?)\*\*", story_text)
    return match.group(1) if match else story_text[:80].strip()


def load_recently_covered() -> list[dict]:
    if not RECENTLY_COVERED_PATH.exists():
        return []
    raw = yaml.safe_load(RECENTLY_COVERED_PATH.read_text())
    return [e for e in (raw or []) if isinstance(e, dict)]


def save_recently_covered(entries: list[dict]) -> None:
    header = (
        "# Stories approved and published. Updated automatically by tools/extract_learning.py.\n"
        "# Used by the generator to avoid covering the same ground twice.\n"
    )
    RECENTLY_COVERED_PATH.write_text(header + yaml.dump(entries, allow_unicode=True, sort_keys=False))


def update_recently_covered(feedback: dict) -> int:
    """Append approved stories from feedback to recently_covered.yaml. Returns count added."""
    entries = load_recently_covered()
    existing_dates = {e["date"] for e in entries}
    date_str = feedback["date"]
    if date_str in existing_dates:
        return 0

    approved = [
        extract_headline(s["edited"])
        for s in feedback["stories"]
        if s["decision"] == "Approve" and s["edited"].strip()
    ]
    if not approved:
        return 0

    entries.append({"date": date_str, "stories": approved})
    entries.sort(key=lambda e: e["date"])
    save_recently_covered(entries)
    return len(approved)


def load_style_rules() -> list[dict]:
    if not STYLE_RULES_PATH.exists():
        return []
    raw = yaml.safe_load(STYLE_RULES_PATH.read_text())
    return [r for r in (raw or []) if isinstance(r, dict)]


def propose_style_rules(feedback_list: list[dict]) -> str:
    """Call Claude to propose style rules from editorial diffs. Returns raw YAML string."""
    diffs = []
    for feedback in feedback_list:
        for story in feedback["stories"]:
            if story.get("diff") and story["decision"] == "Approve":
                diffs.append(f"[{feedback['date']}]\n{story['diff']}")

    if not diffs:
        return ""

    existing_rules = load_style_rules()
    existing_text = (
        "\n".join(f"- {r['rule']}" for r in existing_rules)
        if existing_rules
        else "(none yet)"
    )

    diffs_text = "\n\n".join(diffs)
    prompt = "\n".join([
        "You are analysing editorial diffs to extract style rules for a content generation system.",
        "",
        "The diffs below show how a human editor changed AI-generated content for a European payments",
        "industry briefing. Identify patterns that represent consistent stylistic preferences — rules",
        "specific enough that, if followed, would reduce the need for future edits.",
        "",
        "Focus on:",
        '- Vocabulary or phrasing substitutions (e.g. "X" -> "Y")',
        "- Structural patterns (e.g. how standfirsts lead)",
        "- Punctuation preferences",
        "- Voice or register choices",
        "",
        "Ignore:",
        "- One-off factual corrections",
        "- Changes that are just different, not demonstrably better",
        "- Rules already covered by the existing list below",
        "",
        f"Existing rules:\n{existing_text}",
        "",
        f"Diffs to analyse:\n{diffs_text}",
        "",
        "Output a YAML list of proposed rules only, one per pattern observed. Format:",
        '- date: "YYYY-MM-DD"',
        '  rule: "..."',
        "",
        "Use the date of the diff the rule comes from. Be specific and actionable.",
        "Output only the YAML, no explanation.",
    ])

    load_dotenv(ROOT / ".env", override=True)
    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def main():
    parser = argparse.ArgumentParser(description="Extract learning from editorial feedback")
    parser.add_argument("--date", help="Process a specific date (YYYY-MM-DD)")
    parser.add_argument("--all", action="store_true", help="Process all feedback files")
    args = parser.parse_args()

    if args.all:
        feedback_files = sorted(FEEDBACK_DIR.glob("*.json"))
    elif args.date:
        feedback_files = [FEEDBACK_DIR / f"{args.date}.json"]
    else:
        feedback_files = sorted(FEEDBACK_DIR.glob("*.json"))[-1:]

    if not feedback_files:
        print("No feedback files found.", file=sys.stderr)
        sys.exit(1)

    feedback_list = []
    for path in feedback_files:
        if not path.exists():
            print(f"Not found: {path}", file=sys.stderr)
            continue
        feedback = json.loads(path.read_text())
        feedback_list.append(feedback)
        n = update_recently_covered(feedback)
        if n:
            print(f"recently_covered.yaml: added {n} stories from {feedback['date']}")
        else:
            print(f"recently_covered.yaml: {feedback['date']} already recorded")

    print("\nProposing style rules from diffs...\n")
    proposed = propose_style_rules(feedback_list)

    if proposed:
        print("--- Proposed rules (review, then add to prompts/payments/style_rules.yaml) ---\n")
        print(proposed)
    else:
        print("No new rules proposed (no meaningful diffs found).")


if __name__ == "__main__":
    main()
