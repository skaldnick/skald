import os
import re
import time
import yaml
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from ingester.fetcher import filter_already_covered

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

ROOT = Path(__file__).parent.parent
MODEL = "claude-opus-4-6"
MAX_TOKENS = 8192
MAX_PARSE_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 5


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


def load_recently_covered() -> list[dict]:
    """Load all previously covered stories. Aggregators resurface old stories with
    fresh publish dates, so a duplicate can be months old — there's no safe recency
    cutoff for this check, and the file is small enough to inject in full."""
    path = ROOT / "data" / "recently_covered.yaml"
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text())
    return [e for e in (raw or []) if isinstance(e, dict)]


def load_recently_rejected(days: int = 28) -> list[dict]:
    """Load editorially rejected stories within the last N days.

    Deliberately asymmetric with load_recently_covered's no-cutoff: a covered
    story stays covered forever (aggregators resurface old stories under fresh
    dates), but a rejection is a time-bound judgment — "not newsworthy that
    day" — and the same subject can legitimately become newsworthy again, so
    rejections age out after N days."""
    path = ROOT / "data" / "recently_rejected.yaml"
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


def _covered_section(recently_covered: list[dict] | None) -> str:
    if not recently_covered:
        return ""
    lines = [
        f"- {e['date']}: {headline}"
        for e in recently_covered
        for headline in e["stories"]
    ]
    return (
        "\n\n## Previously covered — avoid unless there is a genuinely new angle. "
        "An aggregator republishing an old story under a fresh date does not count "
        "as new, and neither does a different outlet reporting the same underlying "
        "fact — check the underlying event, not the feed's publish date or source. "
        "This list is internal context only: if you do select a follow-up story, "
        "cite only today's new source in `sources` and explain the new angle in "
        "`editorial_note` — never cite an entry from this list as a source.\n"
        + "\n".join(lines)
    )


def _rejected_section(recently_rejected: list[dict] | None) -> str:
    if not recently_rejected:
        return ""
    lines = [
        f"- {e['date']}: {headline}"
        for e in recently_rejected
        for headline in e["stories"]
    ]
    return (
        "\n\n## Editorially rejected — do not select these stories under any circumstances\n"
        + "\n".join(lines)
    )


def build_user_prompt(story: dict, entries: list[dict], recently_covered: list[dict], recently_rejected: list[dict] | None = None) -> str:
    stories_text = "\n\n".join([
        f"ID: {i}\nSource: {e['source']}\nTitle: {e['title']}\nURL: {e['url']}\nSummary: {e['summary']}\nPublished: {e['published']}"
        for i, e in enumerate(entries, start=1)
    ])
    date_str = datetime.now().strftime("%B %-d, %Y")

    return (
        story["task"]
        + "\n\n"
        + story["selection_criteria"]
        + _covered_section(recently_covered)
        + _rejected_section(recently_rejected)
        + "\n\n"
        + story["output_format"].replace("{date}", date_str)
        + "\n\n"
        + story["input"].replace("{stories}", stories_text)
    )


def _parse_yaml_response(text: str) -> dict:
    """Parse a YAML briefing response from Claude. Returns structured dict."""
    # Strip markdown code fences if present
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    # Find the start of the YAML (skip any preamble). Anchored to start-of-line
    # and the `title: |` block-scalar the prompt always requires, rather than a
    # bare "title:" substring search — a model that rambles about story choices
    # before the real output can otherwise mention the word "title" first and
    # slice the response at the wrong point (confirmed 2026-08-04).
    match = re.search(r"^title:\s*\|", text, re.MULTILINE)
    if match and match.start() > 0:
        text = text[match.start():]
    data = yaml.safe_load(text)
    if not isinstance(data, dict) or "stories" not in data:
        raise ValueError(f"Unexpected YAML structure from Claude:\n{text[:500]}")
    return data


def _build_source_links(ids: list[int], by_id: dict[int, dict], headline: str = "") -> tuple[str, set[str]]:
    """Resolve a list of numeric source_ids against the {id: entry} map into a
    `sources` markdown string, deduping a story's own repeated/duplicate-URL
    citations. Returns (sources_string, urls_used)."""
    if isinstance(ids, int):
        ids = [ids]
    links = []
    urls = set()
    for sid in ids:
        entry = by_id.get(sid)
        if entry is None:
            print(f"Warning: story {headline!r} cited unknown source_id {sid!r}")
            continue
        if entry["url"] in urls:
            print(f"Warning: story {headline!r} cited source_id {sid!r} more than once")
            continue
        links.append(f"[{entry['title']}]({entry['url']}) — {entry['source']}")
        urls.add(entry["url"])
    if not links:
        print(f"Warning: story {headline!r} has no resolvable sources")
    return " | ".join(links), urls


def _resolve_sources(data: dict, entries: list[dict]) -> dict:
    """Replace each story's `source_ids` with a `sources` markdown string built
    from the actual feed entry — the model cites IDs, never URLs, so the link
    can't be mistyped or copied from the wrong story. This guarantees the ID
    resolves to a real entry, not that it's the *right* one — the model can
    still cite a valid ID that belongs to an unrelated story, so stories are
    also checked against each other for a shared cited URL, which usually
    means one of them got the wrong source_id."""
    by_id = {i: e for i, e in enumerate(entries, start=1)}
    stories = data.get("stories", [])
    story_urls = []
    for story in stories:
        ids = story.pop("source_ids", None) or []
        story["sources"], urls = _build_source_links(ids, by_id, story.get("headline", ""))
        story_urls.append(urls)

    for i, story in enumerate(stories):
        shared = set().union(*(u for j, u in enumerate(story_urls) if j != i)) & story_urls[i]
        if shared:
            headline = story.get("headline", "").strip()
            print(f"Warning: story {headline!r} shares a cited source with another story in this briefing")
            story["verification"] = {
                "verified": False,
                "stale": False,
                "duplicate": False,
                "warnings": ["Cited source is also cited by another story in this briefing — likely a wrong or duplicate source_id"],
            }
    return data


def generate_briefing(beat_name: str, entries: list[dict]) -> tuple[dict, list[dict]]:
    """Call the Claude API and return (briefing, filtered_entries). filtered_entries
    is the already-covered-filtered list actually shown to the model — its 1-based
    position is what the model's source_ids refer to, so callers doing further
    source_id-based work (e.g. the revise pass picking a replacement candidate)
    need this exact list, not whatever was originally passed in."""
    system, story = load_prompts(beat_name)
    style_rules = load_style_rules(beat_name)
    recently_covered = load_recently_covered()
    recently_rejected = load_recently_rejected()
    covered_headlines = [h for e in recently_covered for h in e.get("stories", [])]
    covered_headlines += [h for e in recently_rejected for h in e.get("stories", [])]
    entries = filter_already_covered(entries, covered_headlines)
    system_prompt = build_system_prompt(system, style_rules)
    user_prompt = build_user_prompt(story, entries, recently_covered, recently_rejected)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    last_error = None
    for attempt in range(MAX_PARSE_ATTEMPTS):
        message = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        if message.stop_reason == "max_tokens":
            # Fail loudly: YAML truncated mid-block-scalar usually still parses
            # cleanly, so a capped response would otherwise become a briefing with
            # stories or fields silently missing.
            raise RuntimeError(
                f"Briefing generation hit the {MAX_TOKENS}-token output cap and was "
                "truncated — raise MAX_TOKENS or trim the prompt rather than saving "
                "a partial draft."
            )
        try:
            data = _parse_yaml_response(message.content[0].text)
        except (yaml.YAMLError, ValueError) as e:
            # The model occasionally drops the required `|` block-scalar indicator
            # on a free-text field (confirmed 2026-08-25: a colon inside social_post
            # broke the parse with "mapping values are not allowed here"), which a
            # same-prompt retry reliably fixes since it's sampling noise, not a
            # prompt defect — a manual re-trigger of the failed run succeeded first try.
            last_error = e
            print(f"Warning: briefing YAML failed to parse (attempt {attempt + 1}/{MAX_PARSE_ATTEMPTS}): {e}")
            if attempt < MAX_PARSE_ATTEMPTS - 1:
                time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
            continue
        return _resolve_sources(data, entries), entries
    raise RuntimeError(
        f"Briefing generation produced unparseable YAML after {MAX_PARSE_ATTEMPTS} attempts: {last_error}"
    )


def save_draft(beat_name: str, data: dict) -> Path:
    """Write the structured draft to /output/{beat_name}/{date}.yaml"""
    output_dir = Path(__file__).parent.parent / "output" / beat_name
    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = output_dir / f"{date_str}.yaml"
    path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False))
    return path


if __name__ == "__main__":
    from ingester.fetcher import fetch_beat, filter_recent, filter_keywords, resolve_display_sources

    print("Fetching feeds...")
    entries = fetch_beat("payments")
    print(f"{len(entries)} entries fetched")
    entries = filter_recent(entries)
    print(f"{len(entries)} entries after recency filter")
    entries = filter_keywords(entries, "payments")
    print(f"{len(entries)} entries after keyword filter")
    entries = resolve_display_sources(entries)

    print("Generating briefing...")
    briefing, filtered_entries = generate_briefing("payments", entries)

    print("Checking house style...")
    from generator.style_check import check_briefing
    briefing = check_briefing(briefing, load_style_rules("payments"))

    print("Verifying stories...")
    from generator.verify import verify_briefing
    recently_covered = load_recently_covered()
    briefing = verify_briefing(briefing, recently_covered=recently_covered)

    print("Applying fixes and replacements...")
    from generator.revise import revise_briefing
    briefing = revise_briefing(
        briefing, filtered_entries, "payments",
        recently_covered=recently_covered, recently_rejected=load_recently_rejected(),
    )

    path = save_draft("payments", briefing)
    print(f"Draft saved to {path}")
    print(f"Status: {briefing.get('status')}")
    for reason in briefing.get("status_reasons") or []:
        print(f"  - {reason}")
    print("\n" + "=" * 60 + "\n")
    print(yaml.dump(briefing, allow_unicode=True, sort_keys=False, default_flow_style=False))
