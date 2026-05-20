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
DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() == "true"
BRIEFING_BASE_URL = os.environ.get("BRIEFING_BASE_URL", "https://vikingmedia.org/briefings")
ROOT = Path(__file__).parent.parent
OUTPUT_DIR = ROOT / "output"
FEEDBACK_DIR = ROOT / "data" / "feedback"
SITE_DIR = ROOT / "site" / "content" / "briefings"


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
            outputs += [gr.update(visible=False), "", "", "", "", "", "Approve", ""]
        return outputs

    stories = data.get("stories", [])
    title = data.get("title", "")
    briefing_url = f"{BRIEFING_BASE_URL}/{datetime.now().strftime('%Y-%m-%d')}/"
    social = data.get("social_post", "").replace("{link}", briefing_url)
    outputs = [f"### European Payments & Open Banking — {date_str}", title, social]

    for i in range(MAX_STORIES):
        if i < len(stories):
            s = stories[i]
            outputs += [
                gr.update(visible=True),
                f"*Editorial note: {s.get('editorial_note', '')}*",
                gr.update(value=s.get("headline", "")),
                gr.update(value=s.get("standfirst", "")),
                gr.update(value=s.get("body", "").strip()),
                gr.update(value=s.get("sources", "")),
                gr.update(value="Approve"),
                gr.update(value=""),
            ]
        else:
            outputs += [
                gr.update(visible=False),
                "", "", "", "", "",
                gr.update(value="Approve"),
                gr.update(value=""),
            ]
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
    if any(e["date"] == date_str for e in entries):
        return True

    entries.append({"date": date_str, "stories": headlines})
    entries.sort(key=lambda e: e["date"])
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


def on_save(*args):
    # args: headlines, standfirsts, bodies, sources_txts, decisions, reasons
    headlines = list(args[0:MAX_STORIES])
    standfirsts = list(args[MAX_STORIES:MAX_STORIES * 2])
    bodies = list(args[MAX_STORIES * 2:MAX_STORIES * 3])
    sources_list = list(args[MAX_STORIES * 3:MAX_STORIES * 4])
    decisions = list(args[MAX_STORIES * 4:MAX_STORIES * 5])
    notes = list(args[MAX_STORIES * 5:])

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


def on_publish(*args):
    briefing_title = args[0]
    social_post = args[1]
    headlines = list(args[2:MAX_STORIES + 2])
    standfirsts = list(args[MAX_STORIES + 2:MAX_STORIES * 2 + 2])
    bodies = list(args[MAX_STORIES * 2 + 2:MAX_STORIES * 3 + 2])
    sources_list = list(args[MAX_STORIES * 3 + 2:MAX_STORIES * 4 + 2])
    decisions = list(args[MAX_STORIES * 4 + 2:])

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
    content = (
        f'---\ntitle: "{title}"\n'
        f'date: {date_str}\ndraft: false\nbeat: payments\n---\n\n{body_md}'
    )
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

    messages = [f"Published {len(approved)} {'story' if len(approved) == 1 else 'stories'} to {path}"]

    post_text = social_post.strip()
    if post_text:
        if x_api.available():
            ok, result = x_api.post_tweet(post_text)
            messages.append(f"Posted to X: {result}" if ok else f"X post failed: {result}")
        else:
            messages.append("X credentials not configured — social post skipped.")
    else:
        messages.append("No social post — skipped.")

    return "\n\n".join(messages)


def on_generate_title(*args):
    headlines = list(args[:MAX_STORIES])
    decisions = list(args[MAX_STORIES:])
    approved = [h for h, d in zip(headlines, decisions) if h.strip() and d == "Approve"]
    if not approved:
        return gr.update(), "*No approved stories — approve at least one story first.*"
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return gr.update(), "*ANTHROPIC_API_KEY not set — enter title manually.*"
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=60,
        system=(
            "You write concise briefing titles for a European payments and open banking newsletter. "
            "Format: 4–8 words, semicolons separating topics. No quotes, no trailing punctuation. "
            "Example: 'GoCardless profits; pay-by-bank friction; PSD3 delay'"
        ),
        messages=[{"role": "user", "content": f"Generate a briefing title for these approved story headlines:\n\n" + "\n".join(f"- {h}" for h in approved)}],
    )
    return resp.content[0].text.strip(), ""


# --- UI ---

with gr.Blocks(title="Skald — Editorial Dashboard") as app:
    with gr.Row():
        gr.Markdown("# Skald — Editorial Dashboard")
        trigger_btn = gr.Button("Trigger generation", variant="secondary", scale=0)
        load_btn = gr.Button("Load draft", variant="primary", scale=0)

    header_md = gr.Markdown("*Loading draft...*")

    groups = []
    editorial_note_mds = []
    headlines, standfirsts, bodies, sources_txts = [], [], [], []
    decisions, reasons = [], []

    for i in range(MAX_STORIES):
        with gr.Group(visible=False) as grp:
            with gr.Row():
                gr.Markdown(f"#### Story {i + 1}")
                dec = gr.Radio(["Approve", "Reject"], value="Approve", label="Decision", scale=0)
            ed_note = gr.Markdown("")
            headline = gr.Textbox(lines=1, label="Headline")
            standfirst = gr.Textbox(lines=2, label="Standfirst")
            body = gr.Textbox(lines=12, label="Body", show_label=True)
            src = gr.Textbox(lines=2, label="Sources")
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
            gen_title_btn = gr.Button("Generate title", variant="secondary", scale=0)

    social_post_input = gr.Textbox(
        placeholder="Social post for X — AI-drafted, edit before publishing",
        label="Social post (X)",
        lines=3,
        visible=not DEMO_MODE,
    )

    with gr.Row():
        status_md = gr.Markdown("")
        if not DEMO_MODE:
            save_btn = gr.Button("Save feedback", variant="secondary", scale=0)
            publish_btn = gr.Button("Publish approved", variant="primary", scale=0)

    # Per-story load outputs: group, editorial_note, headline, standfirst, body, sources, decision, reason
    load_outputs = [header_md, briefing_title_input, social_post_input]
    for i in range(MAX_STORIES):
        load_outputs += [
            groups[i], editorial_note_mds[i],
            headlines[i], standfirsts[i], bodies[i], sources_txts[i],
            decisions[i], reasons[i],
        ]

    trigger_btn.click(on_trigger_generation, outputs=header_md)
    load_btn.click(on_load_draft, outputs=load_outputs)

    if not DEMO_MODE:
        feedback_inputs = headlines + standfirsts + bodies + sources_txts + decisions + reasons
        save_btn.click(on_save, inputs=feedback_inputs, outputs=status_md)
        publish_btn.click(
            on_publish,
            inputs=[briefing_title_input, social_post_input] + headlines + standfirsts + bodies + sources_txts + decisions,
            outputs=status_md,
        )
        gen_title_btn.click(
            on_generate_title,
            inputs=headlines + decisions,
            outputs=[briefing_title_input, status_md],
        )


if __name__ == "__main__":
    app.launch(theme=gr.themes.Base(), server_name="0.0.0.0", ssr_mode=False)
