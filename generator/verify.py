"""Secondary fact-check pass: re-checks a generated story against the live web
before it reaches the editor, catching stale sources and unsupported figures
that slipped past selection."""

import json
import os
from datetime import datetime

import anthropic

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024
STALE_DAYS = 5


def _system_prompt(today: str) -> str:
    return f"""You are a fact-checker for a European payments news briefing. Today's real-world
date is {today} — treat this as ground truth for any date arithmetic, even if it conflicts
with your own sense of the current date. You will be given a drafted story (headline, body,
cited sources). Use web search to check exactly three things:

1. Currency and figures — every number and currency symbol in the body must match what
   the primary source actually states. Flag any conversion or figure you cannot verify.
2. Recency — find the actual publication or announcement date of the underlying event
   (not an aggregator's republish date). Compute its age by comparing it to today's date,
   {today}, given above — not to whatever date you might otherwise assume. Flag if the
   real event is more than {STALE_DAYS} days old.
3. Unsupported claims — anything stated as fact that your search does not corroborate.

Do your research silently, then respond with ONLY a single JSON object as your final
message — no explanation, no preamble, no commentary, no code fences, before or after it:

{{"verified": true or false, "warnings": ["short, specific warning — e.g. Source states $10bn, draft says £10bn"]}}

If nothing is wrong, return {{"verified": true, "warnings": []}}."""


def _unparseable(text: str) -> dict:
    snippet = text.strip().replace("\n", " ")[:150]
    return {"verified": False, "warnings": [f"verification response could not be parsed: {snippet!r}"]}


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
        "warnings": [str(w) for w in (data.get("warnings") or [])],
    }


def verify_story(story: dict, client: anthropic.Anthropic | None = None, today: str | None = None) -> dict:
    """Fact-check a single story against the live web. Returns {verified, warnings}.
    Never raises — failures are reported as a warning so generation isn't blocked."""
    client = client or anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    today = today or datetime.now().strftime("%B %-d, %Y")
    user_prompt = (
        f"Headline: {story.get('headline', '')}\n\n"
        f"Body:\n{story.get('body', '')}\n\n"
        f"Cited sources: {story.get('sources', '')}"
    )
    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_system_prompt(today),
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": user_prompt}],
        )
        text_blocks = [b.text for b in message.content if getattr(b, "type", None) == "text"]
        return _parse_response("\n".join(text_blocks))
    except Exception as e:
        return {"verified": False, "warnings": [f"verification check failed to run: {e}"]}


def verify_briefing(briefing: dict) -> dict:
    """Run the verification pass over every story in a generated briefing,
    attaching a 'verification' field to each. Mutates and returns the briefing."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    today = datetime.now().strftime("%B %-d, %Y")
    for story in briefing.get("stories", []):
        story["verification"] = verify_story(story, client=client, today=today)
    return briefing
