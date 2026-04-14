import os
import yaml
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

ROOT = Path(__file__).parent.parent
MODEL = "claude-opus-4-6"
MAX_TOKENS = 4096


def load_prompts(beat_name: str) -> tuple[str, str]:
    """Load system and story prompts for a beat. Returns (system, story)."""
    prompts_dir = ROOT / "prompts" / beat_name
    with open(prompts_dir / "system.yaml") as f:
        system = yaml.safe_load(f)
    with open(prompts_dir / "story.yaml") as f:
        story = yaml.safe_load(f)
    return system, story


def load_style_rules(beat_name: str) -> list[dict]:
    """Load accumulated style rules for a beat."""
    path = ROOT / "prompts" / beat_name / "style_rules.yaml"
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text())
    return [r for r in (raw or []) if isinstance(r, dict)]


def load_recently_covered(days: int = 7) -> list[dict]:
    """Load recently covered stories within the last N days."""
    path = ROOT / "data" / "recently_covered.yaml"
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text())
    entries = [e for e in (raw or []) if isinstance(e, dict)]
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return [e for e in entries if e["date"] >= cutoff]


def build_system_prompt(system: dict, style_rules: list[dict]) -> str:
    parts = [
        system["role"],
        system["voice"],
        system["style"],
        system["structure"],
        system["editorial_stance"],
    ]
    if style_rules:
        rules_text = "\n".join(f"- {r['rule']}" for r in style_rules)
        parts.append(f"## House style rules from editorial feedback\n{rules_text}")
    return "\n\n".join(parts)


def build_user_prompt(story: dict, entries: list[dict], recently_covered: list[dict]) -> str:
    stories_text = "\n\n".join([
        f"Source: {e['source']}\nTitle: {e['title']}\nURL: {e['url']}\nSummary: {e['summary']}\nPublished: {e['published']}"
        for e in entries
    ])
    date_str = datetime.now().strftime("%B %-d, %Y")

    covered_section = ""
    if recently_covered:
        lines = [
            f"- {e['date']}: {headline}"
            for e in recently_covered
            for headline in e["stories"]
        ]
        covered_section = (
            "\n\n## Recently covered — avoid unless there is a genuinely new angle\n"
            + "\n".join(lines)
        )

    return (
        story["task"]
        + "\n\n"
        + story["selection_criteria"]
        + covered_section
        + "\n\n"
        + story["output_format"].replace("{date}", date_str)
        + "\n\n"
        + story["input"].replace("{stories}", stories_text)
    )


def generate_briefing(beat_name: str, entries: list[dict]) -> str:
    """Call the Claude API and return the generated briefing as a string."""
    system, story = load_prompts(beat_name)
    style_rules = load_style_rules(beat_name)
    recently_covered = load_recently_covered()
    system_prompt = build_system_prompt(system, style_rules)
    user_prompt = build_user_prompt(story, entries, recently_covered)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return message.content[0].text


def save_draft(beat_name: str, content: str) -> Path:
    """Write the draft to /output/{beat_name}/{date}.md"""
    output_dir = Path(__file__).parent.parent / "output" / beat_name
    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = output_dir / f"{date_str}.md"
    path.write_text(content)
    return path


if __name__ == "__main__":
    from ingester.fetcher import fetch_beat, filter_recent, filter_keywords

    print("Fetching feeds...")
    entries = fetch_beat("payments")
    print(f"{len(entries)} entries fetched")
    entries = filter_recent(entries)
    print(f"{len(entries)} entries after recency filter")
    entries = filter_keywords(entries, "payments")
    print(f"{len(entries)} entries after keyword filter")

    print("Generating briefing...")
    briefing = generate_briefing("payments", entries)

    path = save_draft("payments", briefing)
    print(f"Draft saved to {path}")
    print("\n" + "=" * 60 + "\n")
    print(briefing)
