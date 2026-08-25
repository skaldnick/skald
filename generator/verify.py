"""Secondary fact-check pass: re-checks a generated story against the live web
before it reaches the editor, catching stale sources and unsupported figures
that slipped past selection."""

import json
import os
import time
from datetime import datetime

import anthropic

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024
STALE_DAYS = 5
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 5


def _system_prompt(today: str, has_covered_list: bool) -> str:
    duplicate_check = """
4. Duplicate coverage — compare this story against the "Previously covered" list below.
   Flag it if it reports the same underlying event as an earlier entry: a different outlet,
   a reworded headline, or a follow-up with no materially new fact all count as the same
   story. A follow-up is only distinct if it reports a genuinely new fact — a changed figure,
   a new party involved, or a subsequent stage of the same process (e.g. law passed ->
   regulator approval -> go-live) that the earlier entry did not report. This is a check
   against the provided list, not a web search.""" if has_covered_list else ""
    return f"""You are a fact-checker for a European payments news briefing. Today's real-world
date is {today} — treat this as ground truth for any date arithmetic, even if it conflicts
with your own sense of the current date. You will be given a drafted story (headline, body,
cited sources). Use web search to check the following:

1. Currency and figures — every number and currency symbol in the body must match what
   the primary source actually states. Flag any conversion or figure your search finds
   direct evidence contradicts.
2. Recency — identify the single core event this story reports (the news the headline
   and standfirst are about), and find its actual publication or announcement date (not
   an aggregator's republish date). Compute its age by comparing it to today's date,
   {today}, given above — not to whatever date you might otherwise assume. Flag only if
   that core event is more than {STALE_DAYS} days old. Other developments mentioned in
   the body purely as background or context (e.g. "this follows X's move last month")
   are not the story being reported and must not be flagged for age on their own,
   even if individually older than {STALE_DAYS} days. A search result describing an
   event as "scheduled" for a date that has already arrived (including today, {today})
   does not prove the event hasn't happened — the cited source reporting on it may
   itself be that day's coverage of it. If your search surfaces an earlier, related
   announcement about the same companies or product (e.g. a partnership or plan agreed
   months ago), check whether this story reports that same announcement again or a
   distinct, later stage of the same process (e.g. partnership agreed -> integration
   goes live; law passed -> regulator approval -> go-live) — the story's own wording
   (e.g. "is now live", "has launched", "granted approval") is the primary evidence of
   which. Only the earlier announcement being re-reported is stale; a later stage is a
   new core event dated to when *that stage* happened, not when the process began. Also
   distinguish an event's occurrence date from when it first received substantive press
   coverage: a regulatory or corporate action that happened more than {STALE_DAYS} days
   ago but is only now being reported in depth (the cited source is among the first
   substantive coverage, not a rehash of prior reporting) is still current news to this
   audience — do not flag it as stale solely because the underlying record predates the
   coverage.
3. Unsupported claims — anything stated as fact that your search finds direct,
   on-topic evidence contradicts. If you simply cannot locate or access the cited
   source itself (common for articles published very recently, including today), or
   your search only turns up tangential results that don't directly address the
   specific claim, that is inconclusive, not a contradiction — do not assert an
   alternative version of events as fact just because it's what you could find. Report
   this kind of warning prefixed "Could not independently verify:" so it reads as an
   open question, not a confirmed correction.
{duplicate_check}
Do your research silently, then respond with ONLY a single JSON object as your final
message — no explanation, no preamble, no commentary, no code fences, before or after it:

{{"verified": true or false, "stale": true or false, "duplicate": true or false,
"warnings": ["short, specific warning — e.g. Source states $10bn, draft says £10bn"]}}

Set "stale" to true if and only if you flagged issue 2 (recency) above. Set "duplicate"
to true if and only if you flagged issue 4 (duplicate coverage) above — leave it false
if no "Previously covered" list was given. If nothing is wrong, return
{{"verified": true, "stale": false, "duplicate": false, "warnings": []}}."""


def _unparseable(text: str) -> dict:
    snippet = text.strip().replace("\n", " ")[:150]
    return {
        "verified": False,
        "stale": False,
        "duplicate": False,
        "warnings": [f"verification response could not be parsed: {snippet!r}"],
    }


def _parse_response(text: str) -> dict:
    raw = text
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return _unparseable(raw)
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return _unparseable(raw)
    if not isinstance(data, dict):
        return _unparseable(raw)
    return {
        "verified": bool(data.get("verified", False)),
        "stale": bool(data.get("stale", False)),
        "duplicate": bool(data.get("duplicate", False)),
        "warnings": [str(w) for w in (data.get("warnings") or [])],
    }


def _covered_text(recently_covered: list[dict]) -> str:
    lines = [f"- {e['date']}: {h}" for e in recently_covered for h in e.get("stories", [])]
    return "\n".join(lines)


def verify_story(
    story: dict,
    client: anthropic.Anthropic | None = None,
    today: str | None = None,
    recently_covered: list[dict] | None = None,
) -> dict:
    """Fact-check a single story against the live web, and — if recently_covered is
    given — flag it as a likely duplicate of an already-published story. Returns
    {verified, warnings}. Never raises — failures are reported as a warning so
    generation isn't blocked."""
    client = client or anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    today = today or datetime.now().strftime("%B %-d, %Y")
    user_prompt = (
        f"Headline: {story.get('headline', '')}\n\n"
        f"Body:\n{story.get('body', '')}\n\n"
        f"Cited sources: {story.get('sources', '')}"
    )
    if recently_covered:
        user_prompt += f"\n\nPreviously covered:\n{_covered_text(recently_covered)}"

    last_error = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            message = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=_system_prompt(today, has_covered_list=bool(recently_covered)),
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": user_prompt}],
            )
            text_blocks = [b.text for b in message.content if getattr(b, "type", None) == "text"]
            return _parse_response("\n".join(text_blocks))
        except Exception as e:
            last_error = e
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    return {
        "verified": False,
        "stale": False,
        "duplicate": False,
        "warnings": [f"verification check failed to run: {last_error}"],
    }


def verify_briefing(briefing: dict, recently_covered: list[dict] | None = None) -> dict:
    """Run the verification pass over every story in a generated briefing,
    attaching a 'verification' field to each. Preserves any warnings already
    present on a story (e.g. the shared-source check in _resolve_sources)
    rather than overwriting them. Mutates and returns the briefing."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    today = datetime.now().strftime("%B %-d, %Y")
    for story in briefing.get("stories", []):
        result = verify_story(story, client=client, today=today, recently_covered=recently_covered)
        pre_existing = (story.get("verification") or {}).get("warnings") or []
        story["verification"] = {
            "verified": result["verified"] and not pre_existing,
            "stale": result["stale"],
            "duplicate": result["duplicate"],
            "warnings": pre_existing + result["warnings"],
        }
    return briefing
