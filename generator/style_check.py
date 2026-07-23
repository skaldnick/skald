"""House-style compliance pass: checks a drafted story's prose against the
accumulated house style rules (prompts/payments/style_rules.yaml), independently
of generation — the rules are injected into the generation prompt too, but the
model doesn't always follow them, so this catches what slipped through."""

import json
import os

import anthropic

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 512


def _system_prompt(style_rules: list[dict]) -> str:
    rules_text = "\n".join(f"- {r['rule']}" for r in style_rules)
    return f"""You are a copy editor checking a drafted story against this publication's house
style rules. You will be given a story's headline, standfirst, body and editorial note.
Check it against EVERY rule below and flag any breach, quoting the offending text and
naming which rule it breaks.

## House style rules
{rules_text}

Respond with ONLY a single JSON object as your final message — no explanation, no
preamble, no commentary, no code fences, before or after it:

{{"compliant": true or false, "warnings": ["short, specific warning quoting the offending text and the rule it breaks"]}}

If nothing is wrong, return {{"compliant": true, "warnings": []}}."""


def _unparseable(text: str) -> dict:
    snippet = text.strip().replace("\n", " ")[:150]
    return {"compliant": False, "warnings": [f"style check response could not be parsed: {snippet!r}"]}


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
        "compliant": bool(data.get("compliant", False)),
        "warnings": [str(w) for w in (data.get("warnings") or [])],
    }


def check_story(story: dict, style_rules: list[dict], client: anthropic.Anthropic | None = None) -> dict:
    """Check a single story's prose against house style rules. Returns
    {compliant, warnings}. Never raises — an API failure fails open (compliant,
    no warnings) rather than closed, since an unactionable "check failed to run"
    warning would otherwise waste a rewrite call in the revise pass for nothing."""
    if not style_rules:
        return {"compliant": True, "warnings": []}
    client = client or anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    user_prompt = (
        f"Headline: {story.get('headline', '')}\n\n"
        f"Standfirst: {story.get('standfirst', '')}\n\n"
        f"Body:\n{story.get('body', '')}\n\n"
        f"Editorial note: {story.get('editorial_note', '')}"
    )
    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_system_prompt(style_rules),
            messages=[{"role": "user", "content": user_prompt}],
        )
        return _parse_response(message.content[0].text)
    except Exception as e:
        print(f"Warning: style check failed for {story.get('headline', '')!r}: {e}")
        return {"compliant": True, "warnings": []}


def check_briefing(briefing: dict, style_rules: list[dict]) -> dict:
    """Run the style check over every story in a generated briefing, attaching
    a 'style_check' field to each. Mutates and returns the briefing."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    for story in briefing.get("stories", []):
        story["style_check"] = check_story(story, style_rules, client=client)
    return briefing
