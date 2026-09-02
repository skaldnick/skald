"""Fix/replace pass: runs after style_check and verify, and acts on what they
flagged. Text issues (bad figures, unsupported claims, style breaches) get a
targeted rewrite; stories flagged stale or duplicate-coverage get dropped and
replaced with an unused candidate from the same day's feed, if one exists.
Each touched story gets a short 'revision' summary of what changed and why,
which the dashboard shows in place of the raw warning."""

import json
import os
import re

import anthropic

from generator.client import (
    MODEL,
    _build_source_links,
    _covered_section,
    _rejected_section,
    build_system_prompt,
    load_prompts,
    load_style_rules,
)
from generator.style_check import check_story
from generator.verify import verify_story

MAX_TOKENS = 2048
_NON_ACTIONABLE_MARKERS = ("failed to run", "could not be parsed", "could not independently verify")


def _actionable(warnings: list[str]) -> list[str]:
    """Drop warnings that aren't real fixable issues: pipeline failure markers
    (an earlier pass's own API hiccup) and verify.py's "could not independently
    verify" warnings, which mean the fact-checker's search was inconclusive
    (e.g. a same-day source not yet indexed) rather than finding an actual
    contradiction. Handing either to the rewrite model risks it "fixing" a
    correct story to match a guess — these need editor judgment, not an
    automatic rewrite."""
    return [w for w in warnings if not any(m in w.lower() for m in _NON_ACTIONABLE_MARKERS)]


def _source_urls(sources_md: str) -> set[str]:
    """Extract cited URLs from a story's `sources` markdown string (the format
    _build_source_links produces), since source_ids no longer exist once a
    story's sources have been resolved."""
    return set(re.findall(r"\((https?://[^)]+)\)", sources_md or ""))


def _unparseable_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _fix_system_prompt(house_style_system: str) -> str:
    return house_style_system + """

## Task
You will be given a previously drafted story and a list of specific issues raised by
fact-checking and house-style review. Rewrite ONLY what's necessary to fix each listed
issue — preserve the wording, structure and every fact that isn't flagged. If an issue
can't actually be addressed by rewriting (e.g. it requires information you don't have),
leave the related text unchanged and say so plainly in the change summary rather than
guessing. In particular, only change a specific fact (a date, quarter, figure, name)
when the issue states clearly, with evidence, what the correct value is — an issue that
only expresses uncertainty ("may not match", "could not confirm") is not evidence of
what the right value is, and substituting your own guess risks replacing a correct fact
with a wrong one. Leave those unchanged and note in "changes" that it could not be
confirmed either way.

Respond with ONLY a single JSON object as your final message — no explanation, no
preamble, no commentary, no code fences, before or after it:

{"headline": "...", "standfirst": "...", "body": "...", "editorial_note": "...",
 "changes": ["short bullet describing what changed and why — e.g. Corrected PSP count to 8 per official announcement"]}

Keep paragraph breaks in the body and a single-sentence standfirst, consistent with the
original. If truly nothing could be fixed, return the original text unchanged with a
"changes" entry explaining why."""


def revise_story(story: dict, warnings: list[str], house_style_system: str, client: anthropic.Anthropic | None = None) -> dict | None:
    """Rewrite a single story to address the given warnings. Returns
    {headline, standfirst, body, editorial_note, changes} or None on failure."""
    client = client or anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    user_prompt = (
        f"Headline: {story.get('headline', '')}\n\n"
        f"Standfirst: {story.get('standfirst', '')}\n\n"
        f"Body:\n{story.get('body', '')}\n\n"
        f"Editorial note: {story.get('editorial_note', '')}\n\n"
        "Issues to fix:\n" + "\n".join(f"- {w}" for w in warnings)
    )
    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_fix_system_prompt(house_style_system),
            messages=[{"role": "user", "content": user_prompt}],
        )
        data = _unparseable_json(message.content[0].text)
        if data is None:
            print(f"Warning: revision response could not be parsed for {story.get('headline', '')!r}")
            return None
        return {
            "headline": str(data.get("headline", story.get("headline", ""))),
            "standfirst": str(data.get("standfirst", story.get("standfirst", ""))),
            "body": str(data.get("body", story.get("body", ""))),
            "editorial_note": str(data.get("editorial_note", story.get("editorial_note", ""))),
            "changes": [str(c) for c in (data.get("changes") or [])],
        }
    except Exception as e:
        print(f"Warning: revision pass failed for {story.get('headline', '')!r}: {e}")
        return None


def _replacement_system_prompt(house_style_system: str) -> str:
    return house_style_system + """

## Task
A story originally selected for today's briefing has been dropped (reason given below).
Select ONE replacement from the candidate stories provided, following the same
selection criteria, or report that none of them qualify.

Respond with ONLY a single JSON object as your final message — no explanation, no
preamble, no commentary, no code fences, before or after it:

{"no_candidate": true} if nothing in the candidate list meets the selection criteria,
otherwise:
{"no_candidate": false, "headline": "...", "standfirst": "...", "body": "...",
 "editorial_note": "...", "source_ids": [3]}

source_ids must cite only IDs from the candidate list below — never invent one, and
never cite an entry from the "Previously covered" or "Editorially rejected" lists."""


def generate_replacement(
    beat_name: str,
    unused: list[tuple[int, dict]],
    rejection_reason: str,
    recently_covered: list[dict] | None = None,
    recently_rejected: list[dict] | None = None,
    client: anthropic.Anthropic | None = None,
) -> dict | None:
    """Try to select and draft a replacement story from `unused` — the (id, entry)
    pairs not yet cited elsewhere in today's briefing, with ids keeping their
    1-based position in the filtered entry list the model's source_ids refer to.
    Returns a resolved story dict (with `sources` already built) or None if
    there's nothing usable to replace with."""
    if not unused:
        return None
    client = client or anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    system, story_prompt = load_prompts(beat_name)
    style_rules = load_style_rules(beat_name)
    house_style_system = build_system_prompt(system, style_rules)

    candidates_text = "\n\n".join(
        f"ID: {i}\nSource: {e['source']}\nTitle: {e['title']}\nURL: {e['url']}\nSummary: {e['summary']}\nPublished: {e['published']}"
        for i, e in unused
    )
    user_prompt = (
        f"The following story was removed from today's briefing: {rejection_reason}\n\n"
        + story_prompt["selection_criteria"]
        + _covered_section(recently_covered)
        + _rejected_section(recently_rejected)
        + "\n\nCandidate stories not yet used elsewhere in today's briefing:\n"
        + candidates_text
    )
    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_replacement_system_prompt(house_style_system),
            messages=[{"role": "user", "content": user_prompt}],
        )
        data = _unparseable_json(message.content[0].text)
        if data is None or data.get("no_candidate"):
            return None
        # Resolve only against the unused candidates, not the full entry list —
        # the model is *told* to cite candidate IDs only, but if it cites an ID
        # already used by another story anyway, resolution must fail (unknown-id
        # warning in _build_source_links, then None below) rather than recreate
        # the duplicate-source problem this pass exists to fix.
        by_id = dict(unused)
        headline = str(data.get("headline", ""))
        sources, _ = _build_source_links(data.get("source_ids") or [], by_id, headline)
        if not sources:
            return None
        return {
            "headline": headline,
            "standfirst": str(data.get("standfirst", "")),
            "body": str(data.get("body", "")),
            "editorial_note": str(data.get("editorial_note", "")),
            "sources": sources,
        }
    except Exception as e:
        print(f"Warning: replacement generation failed: {e}")
        return None


def _web_replacement_system_prompt(house_style_system: str) -> str:
    return house_style_system + """

## Task
A story originally selected for today's briefing has been dropped (reason given below),
and today's RSS feeds have no other unused candidate that qualifies as a replacement.
Use web search to find ONE genuinely new, significant European payments or open banking
story from today or the last day or two, following the same selection criteria, or report
that search turned up nothing that qualifies.

Respond with ONLY a single JSON object as your final message — no explanation, no
preamble, no commentary, no code fences, before or after it:

{"no_candidate": true} if search finds nothing that meets the selection criteria,
otherwise:
{"no_candidate": false, "headline": "...", "standfirst": "...", "body": "...",
 "editorial_note": "...", "source_title": "...", "source_url": "...", "source_publisher": "..."}

source_url must be a URL your search actually surfaced — never invent one. source_title
is that outlet's own headline for the piece (not your rewritten headline), and
source_publisher is the outlet's name (e.g. "Finextra", "Reuters"). Never cite a URL
listed below as already used elsewhere in today's briefing, and never select a story
matching the "Previously covered" or "Editorially rejected" lists."""


def generate_web_replacement(
    beat_name: str,
    excluded_urls: set[str],
    rejection_reason: str,
    recently_covered: list[dict] | None = None,
    recently_rejected: list[dict] | None = None,
    client: anthropic.Anthropic | None = None,
) -> dict | None:
    """Second-tier fallback when generate_replacement() finds nothing in today's
    RSS feeds: use web search to look past the feeds for a genuine current story.
    Returns a resolved story dict (with `sources` already built) or None if
    search turns up nothing usable. The candidate is not otherwise verified here —
    the verify_story() call the caller runs on any replacement re-checks it against
    the live web regardless of where it came from, same as a feed-sourced one."""
    client = client or anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    system, story_prompt = load_prompts(beat_name)
    style_rules = load_style_rules(beat_name)
    house_style_system = build_system_prompt(system, style_rules)

    excluded_text = (
        "\n\nURLs already used elsewhere in today's briefing — do not cite these:\n"
        + "\n".join(f"- {u}" for u in sorted(excluded_urls))
        if excluded_urls else ""
    )
    user_prompt = (
        f"The following story was removed from today's briefing: {rejection_reason}\n\n"
        + story_prompt["selection_criteria"]
        + _covered_section(recently_covered)
        + _rejected_section(recently_rejected)
        + excluded_text
    )
    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_web_replacement_system_prompt(house_style_system),
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": user_prompt}],
        )
        text_blocks = [b.text for b in message.content if getattr(b, "type", None) == "text"]
        data = _unparseable_json("\n".join(text_blocks))
        if data is None or data.get("no_candidate"):
            return None
        source_url = str(data.get("source_url", ""))
        if not source_url.startswith(("http://", "https://")) or source_url in excluded_urls:
            print(f"Warning: web replacement cited an invalid or already-used URL: {source_url!r}")
            return None
        source_title = str(data.get("source_title", ""))
        source_publisher = str(data.get("source_publisher", ""))
        return {
            "headline": str(data.get("headline", "")),
            "standfirst": str(data.get("standfirst", "")),
            "body": str(data.get("body", "")),
            "editorial_note": str(data.get("editorial_note", "")),
            "sources": f"[{source_title}]({source_url}) — {source_publisher}",
        }
    except Exception as e:
        print(f"Warning: web replacement generation failed: {e}")
        return None


def _used_source_urls(stories: list[dict]) -> set[str]:
    used_urls = set()
    for s in stories:
        used_urls |= _source_urls(s.get("sources", ""))
    return used_urls


def revise_briefing(
    briefing: dict,
    entries: list[dict],
    beat_name: str,
    recently_covered: list[dict] | None = None,
    recently_rejected: list[dict] | None = None,
) -> dict:
    """Apply the fix/replace pass to every flagged story in a briefing. Mutates
    and returns the briefing."""
    system, _ = load_prompts(beat_name)
    style_rules = load_style_rules(beat_name)
    house_style_system = build_system_prompt(system, style_rules)
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    stories = briefing.get("stories", [])
    for idx, story in enumerate(stories):
        v = story.get("verification") or {}
        sc = story.get("style_check") or {}
        v_warnings = _actionable(v.get("warnings") or [])
        sc_warnings = _actionable(sc.get("warnings") or [])

        if v.get("stale") or v.get("duplicate"):
            kind = "stale" if v.get("stale") else "duplicate coverage"
            reason = "; ".join(v_warnings) or kind
            used_urls = _used_source_urls(stories)
            unused = [(i, e) for i, e in enumerate(entries, start=1) if e["url"] not in used_urls]
            replacement = generate_replacement(
                beat_name, unused, reason, recently_covered, recently_rejected, client=client,
            )
            source = "feed"
            if not replacement:
                replacement = generate_web_replacement(
                    beat_name, used_urls, reason, recently_covered, recently_rejected, client=client,
                )
                source = "web search"
            if replacement:
                replacement["style_check"] = check_story(replacement, style_rules, client=client)
                replacement["verification"] = verify_story(replacement, client=client, recently_covered=recently_covered)
                origin = "today's feed" if source == "feed" else "a live web search (not in today's RSS feeds)"
                summary = [f"Replaced: original story flagged as {kind} ({reason}); swapped in a candidate sourced from {origin}."]
                new_warnings = _actionable(replacement["verification"].get("warnings") or []) + _actionable(replacement["style_check"].get("warnings") or [])
                summary += [f"Note: the replacement was also flagged — {w}" for w in new_warnings]
                replacement["revision"] = {"replaced": True, "resolved": True, "summary": summary}
                stories[idx] = replacement
            else:
                story["revision"] = {
                    "replaced": False,
                    "resolved": False,
                    "summary": [f"Flagged as {kind} but no unused feed or web candidate was available — kept as-is, editor should review."],
                }
            continue

        all_warnings = v_warnings + sc_warnings
        if all_warnings:
            fixed = revise_story(story, all_warnings, house_style_system, client=client)
            if fixed:
                story["headline"] = fixed["headline"]
                story["standfirst"] = fixed["standfirst"]
                story["body"] = fixed["body"]
                story["editorial_note"] = fixed["editorial_note"]
                story["revision"] = {
                    "replaced": False,
                    "resolved": True,
                    "summary": fixed["changes"] or ["Applied fixes for flagged issues."],
                }
            else:
                story["revision"] = {
                    "replaced": False,
                    "resolved": False,
                    "summary": ["Auto-fix failed to run — original flagged issues remain, editor should review."],
                }

    briefing["stories"] = stories
    unresolved = [
        s.get("headline", "").strip()
        for s in stories
        if (s.get("revision") or {}).get("resolved") is False
    ]
    briefing["status"] = "needs_review" if unresolved else "ready"
    if unresolved:
        briefing["status_reasons"] = [f"Could not resolve: {h}" for h in unresolved]
    return briefing
