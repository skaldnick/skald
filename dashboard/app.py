import difflib
import json
import os
import re
from datetime import datetime
from pathlib import Path

import anthropic
import gradio as gr
import yaml

from dashboard import github_api
from dashboard import x_api

MAX_STORIES = 5
X_CHAR_LIMIT = 280
DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() == "true"
BRIEFING_BASE_URL = os.environ.get("BRIEFING_BASE_URL", "https://vikingmedia.org/briefings")
ROOT = Path(__file__).parent.parent
OUTPUT_DIR = ROOT / "output"
FEEDBACK_DIR = ROOT / "data" / "feedback"
SITE_DIR = ROOT / "site" / "content" / "briefings"
PROPOSED_RULES_REL = "data/proposed_style_rules.yaml"
STYLE_RULES_REL = "prompts/payments/style_rules.yaml"
STYLE_RULES_HEADER = (
    "# House style rules extracted from editorial feedback.\n"
    "# Populated by: python tools/extract_learning.py\n"
    "# Review proposed rules before adding. More recent rules take precedence on conflict.\n"
)
PROPOSED_RULES_HEADER = (
    "# Proposed style rules awaiting editorial review.\n"
    "# Populated automatically by tools/extract_learning.py (via GitHub Actions on push\n"
    "# to data/feedback/). Review and promote/edit in the dashboard's 'Proposed style\n"
    "# rules' section — accepted rules move to prompts/payments/style_rules.yaml.\n"
)


def load_draft(beat: str = "payments") -> dict | None:
    """Load today's structured YAML draft. Returns parsed dict or None."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = f"output/{beat}/{date_str}.yaml"
    if github_api.available():
        text, _ = github_api.read_file(path, repo=github_api.GITHUB_PIPELINE_REPO)
        if not text:
            return None
    else:
        local = OUTPUT_DIR / beat / f"{date_str}.yaml"
        if not local.exists():
            return None
        text = local.read_text()
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) and "stories" in data else None


def _assemble_web_story(headline: str, standfirst: str, body: str, sources: str) -> str:
    """Assemble the web-published markdown for one story."""
    parts = [f"**{headline.strip()}**", f"*{standfirst.strip()}*", body.strip()]
    if sources.strip():
        parts.append(f"*Sources: {sources.strip()}*")
    return "\n\n".join(parts)


def compute_diff(original: str, edited: str) -> str:
    orig_lines = original.splitlines(keepends=True)
    edit_lines = edited.splitlines(keepends=True)
    return "".join(difflib.unified_diff(orig_lines, edit_lines, fromfile="original", tofile="edited"))


def on_trigger_generation():
    if not github_api.available():
        return "*GITHUB_TOKEN not set — cannot trigger workflow.*"
    ok = github_api.dispatch_workflow("generate.yml")
    if ok:
        return "*Workflow triggered — draft will be ready in ~3 minutes. Click **Load draft** when ready.*"
    return "*Failed to trigger workflow. Check that GITHUB_TOKEN has `actions:write` permission.*"


def on_load_draft():
    data = load_draft()
    date_str = datetime.now().strftime("%B %-d, %Y")

    if not data:
        header = f"*No draft found for {datetime.now().strftime('%Y-%m-%d')}.*"
        outputs = [header, "", ""]
        for _ in range(MAX_STORIES):
            outputs += ["", "", "", "", "", "", "Approve", ""]
        return outputs

    stories = data.get("stories", [])
    # `or ""` not a .get default: an empty `title:` key parses as None, and
    # None.strip() would crash the load handler.
    title = (data.get("title") or "").strip()
    briefing_url = f"{BRIEFING_BASE_URL}/{datetime.now().strftime('%Y-%m-%d')}/"
    social = (data.get("social_post") or "").strip().replace("{link}", briefing_url).rstrip(".")
    outputs = [f"### European Payments & Open Banking — {date_str}", title, social]

    for i in range(MAX_STORIES):
        if i < len(stories):
            s = stories[i]
            revision_summary = (s.get("revision") or {}).get("summary") or []
            if revision_summary:
                warning_md = "".join(f"\n\n✓ **Auto-corrected:** {w}" for w in revision_summary)
            else:
                v_warnings = (s.get("verification") or {}).get("warnings") or []
                sc_warnings = (s.get("style_check") or {}).get("warnings") or []
                warning_md = "".join(f"\n\n⚠️ **Verification flagged:** {w}" for w in v_warnings)
                warning_md += "".join(f"\n\n⚠️ **Style flagged:** {w}" for w in sc_warnings)
            sources = s.get("sources", "").strip()
            outputs += [
                f"*Editorial note: {s.get('editorial_note', '').strip()}*{warning_md}",
                s.get("headline", "").strip(),
                s.get("standfirst", "").strip(),
                s.get("body", "").strip(),
                sources,
                sources,
                "Approve",
                "",
            ]
        else:
            outputs += ["", "", "", "", "", "", "Approve", ""]
    return outputs


def _update_yaml_in_pipeline_repo(path: str, date_str: str, headlines: list[str], commit_msg: str) -> bool:
    """Append a dated list of headlines to a YAML file in the pipeline repo."""
    if github_api.available():
        text, _ = github_api.read_file(path, repo=github_api.GITHUB_PIPELINE_REPO)
        entries = yaml.safe_load(text or "") or []
    else:
        local_path = ROOT / path
        entries = yaml.safe_load(local_path.read_text()) if local_path.exists() else []

    entries = [e for e in (entries or []) if isinstance(e, dict)]
    existing = next((e for e in entries if e.get("date") == date_str), None)
    if existing is None:
        entries.append({"date": date_str, "stories": list(headlines)})
    else:
        # Merge, never replace: a same-day republish (eg, after approving one
        # more story) must add its headlines, but un-approving a story on
        # republish shouldn't remove a headline that was genuinely published
        # earlier in the day — once covered, always covered.
        current = existing.setdefault("stories", [])
        new = [h for h in headlines if h not in current]
        if not new:
            return True  # nothing to add — skip the no-op commit
        current.extend(new)
    entries.sort(key=lambda e: e.get("date", ""))
    payload = (
        "# Updated automatically by the editorial dashboard.\n"
        + yaml.dump(entries, allow_unicode=True, sort_keys=False)
    )

    if github_api.available():
        return github_api.write_file(path, payload, commit_msg, repo=github_api.GITHUB_PIPELINE_REPO)
    else:
        local_path = ROOT / path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(payload)
        return True


def _read_repo_yaml_list(path: str) -> list[dict]:
    """Read a YAML list of dicts from the pipeline repo (or local filesystem)."""
    if github_api.available():
        text, _ = github_api.read_file(path, repo=github_api.GITHUB_PIPELINE_REPO)
    else:
        local_path = ROOT / path
        text = local_path.read_text() if local_path.exists() else None
    entries = yaml.safe_load(text) if text else []
    return [e for e in (entries or []) if isinstance(e, dict)]


def _write_repo_yaml_list(path: str, entries: list[dict], header: str, commit_msg: str) -> bool:
    payload = header + yaml.dump(entries, allow_unicode=True, sort_keys=False)
    if github_api.available():
        return github_api.write_file(path, payload, commit_msg, repo=github_api.GITHUB_PIPELINE_REPO)
    local_path = ROOT / path
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(payload)
    return True


def on_load_proposed_rules():
    proposed = _read_repo_yaml_list(PROPOSED_RULES_REL)
    if not proposed:
        return "No proposed rules pending review."
    return "\n".join(f"[{r.get('date', '')}] {r['rule']}" for r in proposed if r.get("rule"))


def on_save_reviewed_rules(text: str):
    """Promote whatever remains in the review textbox into house style rules, then
    clear the pending queue — lines the editor deleted are treated as rejected."""
    line_re = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\]\s*(.+)$")
    today = datetime.now().strftime("%Y-%m-%d")
    accepted = []
    for line in text.splitlines():
        line = line.strip().lstrip("-").strip()
        if not line:
            continue
        m = line_re.match(line)
        if m:
            accepted.append({"date": m.group(1), "rule": m.group(2).strip()})
        else:
            accepted.append({"date": today, "rule": line})

    if accepted:
        style_rules = _read_repo_yaml_list(STYLE_RULES_REL)
        style_rules.extend(accepted)
        if not _write_repo_yaml_list(
            STYLE_RULES_REL, style_rules, STYLE_RULES_HEADER,
            f"Add {len(accepted)} reviewed style rule(s)",
        ):
            return "Error saving style rules."

    if not _write_repo_yaml_list(
        PROPOSED_RULES_REL, [], PROPOSED_RULES_HEADER, "Clear reviewed style rule proposals",
    ):
        return f"Saved {len(accepted)} style rule(s), but failed to clear the pending queue — clear it manually."

    if accepted:
        return f"Saved {len(accepted)} style rule(s) to house style. Pending queue cleared."
    return "No rules accepted — pending queue cleared."


def _save_feedback(headlines, standfirsts, bodies, sources_list, decisions, notes) -> str:
    """Write the day's edit diffs, decisions and notes to data/feedback/. Called
    by the Save feedback button and automatically on publish, so the learning
    loop never misses a session because Save wasn't clicked."""
    original_data = load_draft()
    original_stories = original_data.get("stories", []) if original_data else []

    date_str = datetime.now().strftime("%Y-%m-%d")
    records = []
    for i, (headline, standfirst, body, sources, decision, note) in enumerate(
        zip(headlines, standfirsts, bodies, sources_list, decisions, notes)
    ):
        if not headline.strip():
            continue
        edited = _assemble_web_story(headline, standfirst, body, sources)
        original = ""
        if i < len(original_stories):
            s = original_stories[i]
            original = _assemble_web_story(
                s.get("headline", ""), s.get("standfirst", ""),
                s.get("body", "").strip(), s.get("sources", ""),
            )
        records.append({
            "original": original,
            "edited": edited,
            "diff": compute_diff(original, edited),
            "decision": decision,
            "notes": note or None,
        })
    payload = json.dumps({"date": date_str, "beat": "payments", "stories": records}, indent=2)

    if github_api.available():
        ok = github_api.write_file(
            f"data/feedback/{date_str}.json",
            payload,
            f"Save feedback {date_str}",
            repo=github_api.GITHUB_PIPELINE_REPO,
        )
        if not ok:
            return "Error saving feedback to GitHub."
    else:
        FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
        (FEEDBACK_DIR / f"{date_str}.json").write_text(payload)

    return f"Feedback saved — {len(records)} stories recorded."


def on_save(*args):
    # args: headlines, standfirsts, bodies, sources_txts, decisions, reasons
    headlines = list(args[0:MAX_STORIES])
    standfirsts = list(args[MAX_STORIES:MAX_STORIES * 2])
    bodies = list(args[MAX_STORIES * 2:MAX_STORIES * 3])
    sources_list = list(args[MAX_STORIES * 3:MAX_STORIES * 4])
    decisions = list(args[MAX_STORIES * 4:MAX_STORIES * 5])
    notes = list(args[MAX_STORIES * 5:])
    return _save_feedback(headlines, standfirsts, bodies, sources_list, decisions, notes)


def on_publish(*args):
    briefing_title = args[0]
    rest = args[1:]
    headlines = list(rest[0:MAX_STORIES])
    standfirsts = list(rest[MAX_STORIES:MAX_STORIES * 2])
    bodies = list(rest[MAX_STORIES * 2:MAX_STORIES * 3])
    sources_list = list(rest[MAX_STORIES * 3:MAX_STORIES * 4])
    decisions = list(rest[MAX_STORIES * 4:MAX_STORIES * 5])
    notes = list(rest[MAX_STORIES * 5:])

    date_str = datetime.now().strftime("%Y-%m-%d")
    approved, rejected = [], []
    for headline, standfirst, body, sources, decision in zip(
        headlines, standfirsts, bodies, sources_list, decisions
    ):
        if not headline.strip():
            continue
        if decision == "Approve":
            approved.append((headline, standfirst, body, sources))
        else:
            rejected.append(headline)

    if not approved:
        return "No approved stories to publish."

    title = briefing_title.strip() or date_str
    body_md = "\n\n---\n\n".join(
        _assemble_web_story(h, sf, b, src) for h, sf, b, src in approved
    )
    # Front matter is built with yaml.dump, not an f-string — the title is model-
    # or editor-written prose that can contain quote marks or colons, either of
    # which breaks hand-quoted YAML (same failure class as the block-scalar rule
    # in CLAUDE.md's prompt conventions).
    front_matter = yaml.dump(
        {"title": title, "date": date_str, "draft": False, "beat": "payments"},
        allow_unicode=True, sort_keys=False, default_flow_style=False,
    )
    content = f"---\n{front_matter}---\n\n{body_md}"
    path = f"site/content/briefings/{date_str}.md"

    if github_api.available():
        ok = github_api.write_file(path, content, f"Publish briefing {date_str}")
        if not ok:
            return "Error publishing to GitHub."
    else:
        SITE_DIR.mkdir(parents=True, exist_ok=True)
        (SITE_DIR / f"{date_str}.md").write_text(content)

    approved_headlines = [h for h, *_ in approved]
    _update_yaml_in_pipeline_repo(
        "data/recently_covered.yaml", date_str, approved_headlines,
        f"Update recently_covered {date_str}",
    )
    if rejected:
        _update_yaml_in_pipeline_repo(
            "data/recently_rejected.yaml", date_str, rejected,
            f"Update recently_rejected {date_str}",
        )

    feedback_msg = _save_feedback(headlines, standfirsts, bodies, sources_list, decisions, notes)
    return (
        f"Published {len(approved)} {'story' if len(approved) == 1 else 'stories'} to {path}. "
        + feedback_msg
    )


def on_post_to_x(social_post: str):
    post_text = social_post.strip()
    if not post_text:
        return "No social post text — nothing to post."
    if not x_api.available():
        return "X credentials not configured."
    ok, result = x_api.post_tweet(post_text)
    return f"Posted to X: {result}" if ok else f"X post failed: {result}"


# Country name <-> demonym/adjective pairs, so e.g. a headline saying "Greek fintech"
# doesn't cause a social post saying "Greece" to be flagged as an invented term.
COUNTRY_DEMONYMS = {
    "Austria": "Austrian", "Belgium": "Belgian", "Bulgaria": "Bulgarian",
    "Croatia": "Croatian", "Cyprus": "Cypriot", "Czechia": "Czech",
    "Denmark": "Danish", "Estonia": "Estonian", "Finland": "Finnish",
    "France": "French", "Germany": "German", "Greece": "Greek",
    "Hungary": "Hungarian", "Iceland": "Icelandic", "Ireland": "Irish",
    "Italy": "Italian", "Latvia": "Latvian", "Lithuania": "Lithuanian",
    "Luxembourg": "Luxembourgish", "Malta": "Maltese", "Netherlands": "Dutch",
    "Norway": "Norwegian", "Poland": "Polish", "Portugal": "Portuguese",
    "Romania": "Romanian", "Slovakia": "Slovak", "Slovenia": "Slovenian",
    "Spain": "Spanish", "Sweden": "Swedish", "Switzerland": "Swiss",
    "Turkey": "Turkish", "Britain": "British", "England": "English",
}
COUNTRY_DEMONYMS.update({v: k for k, v in COUNTRY_DEMONYMS.items()})


def _flag_unlisted_terms(social_text: str, source_text: str) -> list[str]:
    """Heuristic guard: capitalized words in the social post that don't appear anywhere
    in the approved headlines/standfirsts are surfaced as a warning. The model has been
    observed inventing plausible-sounding but fabricated stories to pad out a thin day,
    despite being told not to — this doesn't stop that, it just flags it for the editor
    before they post."""
    stoplist = {"Plus", "Today", "Read", "The", "European", "Payments", "Open", "Banking"}
    allowed = set(re.findall(r"[A-Z][a-zA-Z]{2,}", source_text))
    found = sorted(
        w for w in set(re.findall(r"[A-Z][a-zA-Z]{2,}", social_text))
        if w not in allowed and w not in stoplist and COUNTRY_DEMONYMS.get(w) not in allowed
    )
    return found


def on_regenerate(*args):
    headlines = list(args[:MAX_STORIES])
    standfirsts = list(args[MAX_STORIES:MAX_STORIES * 2])
    decisions = list(args[MAX_STORIES * 2:])
    approved = [h for h, d in zip(headlines, decisions) if h.strip() and d == "Approve"]
    if not approved:
        return gr.update(), gr.update(), "*No approved stories — approve at least one story first.*"
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return gr.update(), gr.update(), "*ANTHROPIC_API_KEY not set — enter title and social post manually.*"
    client = anthropic.Anthropic(api_key=api_key)
    headlines_text = "\n".join(f"- {h}" for h in approved)
    # Headline + standfirst, used only to widen the hallucination-check's allowed-terms
    # pool (not fed to the model) — standfirsts carry entity/company/country names that
    # get trimmed out of the deliberately short headline, causing false-positive flags.
    approved_context = "\n".join(
        f"- {h}\n  {s}" for h, s, d in zip(headlines, standfirsts, decisions) if h.strip() and d == "Approve"
    )
    briefing_url = f"{BRIEFING_BASE_URL}/{datetime.now().strftime('%Y-%m-%d')}/"
    link_suffix = f". Today's briefing → {briefing_url}"
    text_budget = X_CHAR_LIMIT - len(link_suffix)
    title_resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=60,
        system=(
            "You write concise briefing titles for a European payments and open banking newsletter. "
            "Format: 4–8 words, semicolons separating topics. No quotes, no trailing punctuation. "
            "Example: 'GoCardless profits; pay-by-bank friction; PSD3 delay'"
        ),
        messages=[{"role": "user", "content": f"Generate a briefing title for these approved story headlines:\n\n{headlines_text}"}],
    )
    if len(approved) == 1:
        # A single approved story is where the model has been observed padding the post
        # with invented "Plus:" items rather than writing about just the one story as
        # instructed. Removing the "Plus:" option from the prompt entirely for this case
        # is a stronger guardrail than just telling it not to use one.
        social_system = (
            "You write social posts for X (Twitter) for a European payments and open banking newsletter. "
            f"Write no more than {text_budget} characters — the caller will append a fixed "
            f"{len(link_suffix)}-character link suffix ('. Today's briefing → <url>') to reach the {X_CHAR_LIMIT} total. "
            "There is exactly ONE approved story today. Write the entire post about that single story only. "
            "Do not add a 'Plus:' section or any other clause. Do not mention, tease, or imply any other story, "
            "company, country, or regulation under any circumstance — even if it would make the post feel fuller. "
            "Never flag or apologise for there being only one story (e.g. 'thin' day) — a single strong story "
            "stands on its own. No hashtags. No trailing punctuation. Output only the post text, nothing else."
        )
    else:
        social_system = (
            "You write social posts for X (Twitter) for a European payments and open banking newsletter. "
            f"Write no more than {text_budget} characters — the caller will append a fixed "
            f"{len(link_suffix)}-character link suffix ('. Today's briefing → <url>') to reach the {X_CHAR_LIMIT} total. "
            "Lead with the most interesting story. You MUST mention only stories from the approved headline list "
            "below — never invent, imply, or tease any topic, company, country, or regulation that is not one of "
            "the listed headlines, even to fill out a 'Plus:' clause. You may tease 2-3 of the listed headlines with "
            "'Plus:'. Never flag or apologise for the number of stories. No hashtags. No trailing punctuation. "
            "Output only the post text, nothing else."
        )
    social_resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        system=social_system,
        messages=[{"role": "user", "content": f"Write an X social post for a briefing covering these stories:\n\n{headlines_text}"}],
    )
    social_text = social_resp.content[0].text.strip().rstrip(".")
    social = social_text + link_suffix
    unlisted = _flag_unlisted_terms(social_text, approved_context)
    status = ""
    if unlisted:
        status = (
            f"*⚠️ Social post mentions terms not found in the approved headlines — "
            f"check for invented content before posting: {', '.join(unlisted)}*"
        )
    return title_resp.content[0].text.strip(), social, status


# --- UI ---

with gr.Blocks(title="Skald — Editorial Dashboard") as app:
    with gr.Row():
        gr.Markdown("# Skald — Editorial Dashboard")
        trigger_btn = gr.Button("Trigger generation", variant="secondary", scale=0)
        load_btn = gr.Button("Load draft", variant="primary", scale=0)

    header_md = gr.Markdown("*Checking for today's draft...*")

    groups = []
    editorial_note_mds = []
    headlines, standfirsts, bodies, sources_txts, sources_mds = [], [], [], [], []
    decisions, reasons = [], []

    for i in range(MAX_STORIES):
        with gr.Group() as grp:
            with gr.Row():
                gr.Markdown(f"#### Story {i + 1}")
                dec = gr.Radio(["Approve", "Reject"], value="Approve", label="Decision", scale=0)
            ed_note = gr.Markdown("")
            headline = gr.Textbox(lines=1, label="Headline")
            standfirst = gr.Textbox(lines=2, label="Standfirst")
            body = gr.Textbox(lines=12, label="Body", show_label=True)
            src_md = gr.Markdown(label="Sources")
            src = gr.State("")
            rsn = gr.Textbox(
                placeholder="Notes — story selection, style, or rejection reason (optional)",
                label="Notes",
                lines=2,
            )
        groups.append(grp)
        editorial_note_mds.append(ed_note)
        headlines.append(headline)
        standfirsts.append(standfirst)
        bodies.append(body)
        sources_txts.append(src)
        sources_mds.append(src_md)
        decisions.append(dec)
        reasons.append(rsn)

    with gr.Row():
        briefing_title_input = gr.Textbox(
            placeholder="Briefing title — AI-drafted, edit before publishing",
            label="Briefing title",
            scale=1,
            visible=not DEMO_MODE,
        )
        if not DEMO_MODE:
            regen_btn = gr.Button("Re-generate", variant="secondary", scale=0)

    with gr.Row(visible=not DEMO_MODE):
        social_post_input = gr.Textbox(
            placeholder="Social post for X — AI-drafted, edit before publishing",
            label="Social post (X)",
            lines=3,
            scale=1,
        )
        post_x_btn = gr.Button("Post to X", variant="secondary", scale=0)
    if not DEMO_MODE:
        social_char_count = gr.Markdown(f"0 / {X_CHAR_LIMIT}")

    with gr.Row():
        status_md = gr.Markdown("")
        if not DEMO_MODE:
            save_btn = gr.Button("Save feedback", variant="secondary", scale=0)
            publish_btn = gr.Button("Publish approved", variant="primary", scale=0)

    # Per-story load outputs: editorial_note, headline, standfirst, body, sources_md, sources_state, decision, reason
    load_outputs = [header_md, briefing_title_input, social_post_input]
    for i in range(MAX_STORIES):
        load_outputs += [
            editorial_note_mds[i],
            headlines[i], standfirsts[i], bodies[i], sources_mds[i], sources_txts[i],
            decisions[i], reasons[i],
        ]

    app.load(on_load_draft, outputs=load_outputs)
    trigger_btn.click(on_trigger_generation, outputs=header_md)
    load_btn.click(on_load_draft, outputs=load_outputs)

    if not DEMO_MODE:
        feedback_inputs = headlines + standfirsts + bodies + sources_txts + decisions + reasons
        save_btn.click(on_save, inputs=feedback_inputs, outputs=status_md)
        publish_btn.click(
            on_publish,
            inputs=[briefing_title_input] + headlines + standfirsts + bodies + sources_txts + decisions + reasons,
            outputs=status_md,
        )
        post_x_btn.click(on_post_to_x, inputs=social_post_input, outputs=status_md)
        social_post_input.change(
            fn=lambda text: f"{len(text)} / {X_CHAR_LIMIT}",
            inputs=social_post_input,
            outputs=social_char_count,
        )
        regen_btn.click(
            on_regenerate,
            inputs=headlines + standfirsts + decisions,
            outputs=[briefing_title_input, social_post_input, status_md],
        )

    if not DEMO_MODE:
        with gr.Group():
            with gr.Row():
                gr.Markdown("#### Proposed style rules")
                load_rules_btn = gr.Button("Load proposed rules", variant="secondary", scale=0)
                save_rules_btn = gr.Button("Save reviewed rules", variant="primary", scale=0)
            proposed_rules_box = gr.Textbox(
                label="One rule per line — edit wording freely, delete a line to reject it",
                placeholder="Click **Load proposed rules** to check for new rules extracted from recent feedback.",
                lines=6,
            )
            rules_status_md = gr.Markdown("")

        load_rules_btn.click(on_load_proposed_rules, outputs=proposed_rules_box)
        save_rules_btn.click(on_save_reviewed_rules, inputs=proposed_rules_box, outputs=rules_status_md)


if __name__ == "__main__":
    app.launch(theme=gr.themes.Base(), server_name="0.0.0.0", ssr_mode=False)
