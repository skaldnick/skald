"""Secondary fact-check pass: re-checks a generated story against the live web
before it reaches the editor, catching stale sources and unsupported figures
that slipped past selection."""

import os

import anthropic
import yaml

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 400
STALE_DAYS = 5

SYSTEM_PROMPT = f"""You are a fact-checker for a European payments news briefing. You will be
given a drafted story (headline, body, cited sources). Use web search to check exactly
three things:

1. Currency and figures — every number and currency symbol in the body must match what
   the primary source actually states. Flag any conversion or figure you cannot verify.
2. Recency — find the actual publication or announcement date of the underlying event
   (not an aggregator's republish date). Flag if the real event is more than {STALE_DAYS}
   days old.
3. Unsupported claims — anything stated as fact that your search does not corroborate.

Respond with only a YAML document, no preamble, no code fences:

verified: true or false
warnings:
  - "short, specific warning — e.g. 'Source states $10bn, draft says £10bn'"

If nothing is wrong, return verified: true and warnings: []."""


def _parse_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        return {"verified": False, "warnings": ["verification response could not be parsed"]}
    return {
        "verified": bool(data.get("verified", False)),
        "warnings": [str(w) for w in (data.get("warnings") or [])],
    }


def verify_story(story: dict, client: anthropic.Anthropic | None = None) -> dict:
    """Fact-check a single story against the live web. Returns {verified, warnings}.
    Never raises — failures are reported as a warning so generation isn't blocked."""
    client = client or anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    user_prompt = (
        f"Headline: {story.get('headline', '')}\n\n"
        f"Body:\n{story.get('body', '')}\n\n"
        f"Cited sources: {story.get('sources', '')}"
    )
    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
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
    for story in briefing.get("stories", []):
        story["verification"] = verify_story(story, client=client)
    return briefing
