"""
Post-session learning tool. Run after each editorial session.

Usage:
    python tools/extract_learning.py              # most recent feedback file
    python tools/extract_learning.py --date 2026-04-14
    python tools/extract_learning.py --all        # all feedback files

What it does:
  1. Calls Claude to propose style rules from editorial diffs and prints them.

Proposed rules are printed to stdout — review them, then add any worth keeping
to prompts/payments/style_rules.yaml and commit.

Note: recently_covered.yaml and recently_rejected.yaml are now updated
automatically by the dashboard on publish. This tool focuses on style rules.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import anthropic
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
FEEDBACK_DIR = ROOT / "data" / "feedback"
STYLE_RULES_PATH = ROOT / "prompts" / "payments" / "style_rules.yaml"


def _try_github_feedback(date_str: str) -> dict | None:
    """Fetch a feedback file from the GitHub pipeline repo, if available."""
    load_dotenv(ROOT / ".env", override=True)
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return None
    try:
        import base64
        import requests
        pipeline_repo = os.environ.get("GITHUB_PIPELINE_REPO", "skaldnick/skald")
        branch = os.environ.get("GITHUB_BRANCH", "main")
        url = f"https://api.github.com/repos/{pipeline_repo}/contents/data/feedback/{date_str}.json"
        resp = requests.get(url, headers={"Authorization": f"token {token}"}, params={"ref": branch})
        if resp.status_code == 200:
            content = base64.b64decode(resp.json()["content"]).decode()
            return json.loads(content)
    except Exception as e:
        print(f"GitHub fetch failed: {e}", file=sys.stderr)
    return None


def load_feedback_file(path: Path) -> dict | None:
    """Load a feedback JSON from local path, falling back to GitHub."""
    if path.exists():
        return json.loads(path.read_text())
    date_str = path.stem  # filename without extension
    print(f"Local file not found: {path} — trying GitHub…", file=sys.stderr)
    return _try_github_feedback(date_str)


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
        # Default: most recent local file, or yesterday/today if none found
        local_files = sorted(FEEDBACK_DIR.glob("*.json"))
        feedback_files = local_files[-1:] if local_files else []

    if not feedback_files:
        print("No local feedback files found. Specify --date YYYY-MM-DD to fetch from GitHub.", file=sys.stderr)
        sys.exit(1)

    feedback_list = []
    for path in feedback_files:
        feedback = load_feedback_file(path)
        if feedback is None:
            print(f"Not found locally or on GitHub: {path.stem}", file=sys.stderr)
            continue
        feedback_list.append(feedback)
        print(f"Loaded feedback for {feedback['date']} ({len(feedback.get('stories', []))} stories)")

    if not feedback_list:
        print("No feedback loaded.", file=sys.stderr)
        sys.exit(1)

    print("\nNote: recently_covered.yaml and recently_rejected.yaml are updated automatically")
    print("by the dashboard on publish. Skipping that step here.\n")

    print("Proposing style rules from diffs…\n")
    proposed = propose_style_rules(feedback_list)

    if proposed:
        print("--- Proposed rules (review, then add to prompts/payments/style_rules.yaml) ---\n")
        print(proposed)
    else:
        print("No new rules proposed (no meaningful diffs found).")


if __name__ == "__main__":
    main()
