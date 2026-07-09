"""
Post-session learning tool. Runs automatically on push to data/feedback/ via
.github/workflows/extract_learning.yml — can also be run manually after a session.

Usage:
    python tools/extract_learning.py              # most recent feedback file
    python tools/extract_learning.py --date 2026-04-14
    python tools/extract_learning.py --all        # all feedback files

What it does:
  1. Calls Claude to propose style rules from editorial diffs and notes.
  2. Appends new proposals (deduped against accepted and already-pending rules)
     to data/proposed_style_rules.yaml.

Proposals sit in that queue until reviewed in the dashboard's "Proposed style
rules" section, where they can be edited or dropped before being promoted into
prompts/payments/style_rules.yaml.

Note: recently_covered.yaml and recently_rejected.yaml are updated
automatically by the dashboard on publish. This tool focuses on style rules.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import anthropic
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
FEEDBACK_DIR = ROOT / "data" / "feedback"
STYLE_RULES_PATH = ROOT / "prompts" / "payments" / "style_rules.yaml"
PROPOSED_RULES_PATH = ROOT / "data" / "proposed_style_rules.yaml"


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


def load_proposed_rules() -> list[dict]:
    if not PROPOSED_RULES_PATH.exists():
        return []
    raw = yaml.safe_load(PROPOSED_RULES_PATH.read_text())
    return [r for r in (raw or []) if isinstance(r, dict)]


def _normalize(rule_text: str) -> str:
    return re.sub(r"\s+", " ", rule_text.strip().lower())


def _parse_proposed_yaml(text: str) -> list[dict]:
    """Parse Claude's raw YAML response into a list of {date, rule} dicts."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        raw = yaml.safe_load(cleaned)
    except yaml.YAMLError:
        return []
    return [r for r in (raw or []) if isinstance(r, dict) and r.get("rule")]


def append_proposed_rules(new_rules: list[dict]) -> int:
    """Dedupe new_rules against accepted and already-pending rules, then append
    the remainder to the proposed-rules queue. Returns the number actually added."""
    existing = load_style_rules()
    pending = load_proposed_rules()
    seen = {_normalize(r["rule"]) for r in existing + pending if r.get("rule")}

    added = []
    for r in new_rules:
        key = _normalize(r["rule"])
        if key in seen:
            continue
        seen.add(key)
        added.append({"date": r.get("date", ""), "rule": r["rule"]})

    if added:
        pending.extend(added)
        payload = (
            "# Proposed style rules awaiting editorial review.\n"
            "# Populated automatically by tools/extract_learning.py (via GitHub Actions on push\n"
            "# to data/feedback/). Review and promote/edit in the dashboard's 'Proposed style\n"
            "# rules' section — accepted rules move to prompts/payments/style_rules.yaml.\n"
            + yaml.dump(pending, allow_unicode=True, sort_keys=False)
        )
        PROPOSED_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROPOSED_RULES_PATH.write_text(payload)

    return len(added)


def propose_style_rules(feedback_list: list[dict]) -> str:
    """Call Claude to propose style rules from editorial diffs and notes. Returns raw YAML string."""
    diffs = []
    notes = []
    for feedback in feedback_list:
        for story in feedback["stories"]:
            if story["decision"] != "Approve":
                continue
            if story.get("diff"):
                diffs.append(f"[{feedback['date']}]\n{story['diff']}")
            if story.get("notes"):
                notes.append(f"[{feedback['date']}] {story['notes']}")

    if not diffs and not notes:
        return ""

    existing_rules = load_style_rules()
    pending_rules = load_proposed_rules()
    existing_text = (
        "\n".join(f"- {r['rule']}" for r in existing_rules)
        if existing_rules
        else "(none yet)"
    )
    pending_text = (
        "\n".join(f"- {r['rule']}" for r in pending_rules)
        if pending_rules
        else "(none)"
    )

    diffs_text = "\n\n".join(diffs) if diffs else "(none)"
    notes_text = "\n".join(notes) if notes else "(none)"
    prompt = "\n".join([
        "You are analysing editorial diffs and editor notes to extract style rules for a content",
        "generation system.",
        "",
        "The diffs below show how a human editor changed AI-generated content for a European payments",
        "industry briefing. The notes are the editor's own written explanation of what they changed and",
        "why, taken from the same review session — treat a note as a direct, authoritative statement of",
        "a rule, not something to infer. Where a note and a diff describe the same edit, prefer the",
        "note's wording of the rule over inferring it from the diff alone.",
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
        "- Rules already covered by the existing or pending lists below",
        "",
        f"Existing (accepted) rules:\n{existing_text}",
        "",
        f"Pending rules (already proposed, awaiting editor review — do not repropose these):\n{pending_text}",
        "",
        f"Editor notes to analyse:\n{notes_text}",
        "",
        f"Diffs to analyse:\n{diffs_text}",
        "",
        "Output a YAML list of proposed rules only, one per pattern observed. Format:",
        '- date: "YYYY-MM-DD"',
        '  rule: "..."',
        "",
        "Use the date of the note or diff the rule comes from. Be specific and actionable.",
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

    print("Proposing style rules from diffs and notes…\n")
    proposed_text = propose_style_rules(feedback_list)

    if not proposed_text:
        print("No new rules proposed (no diffs or notes found).")
        return

    parsed = _parse_proposed_yaml(proposed_text)
    if not parsed:
        print("Claude's response could not be parsed as YAML — nothing queued. Raw response:\n")
        print(proposed_text)
        sys.exit(1)

    added_count = append_proposed_rules(parsed)
    print(f"--- Claude proposed {len(parsed)} rule(s); {added_count} new (after dedup) queued to "
          f"{PROPOSED_RULES_PATH.relative_to(ROOT)} ---\n")
    print(proposed_text)
    print("\nReview in the dashboard's 'Proposed style rules' section.")


if __name__ == "__main__":
    main()
