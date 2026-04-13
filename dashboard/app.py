import difflib
import json
import os
import re
from datetime import datetime
from pathlib import Path

import gradio as gr

from dashboard import github_api
from ingester.fetcher import fetch_beat, filter_recent, filter_keywords
from generator.client import generate_briefing, save_draft

MAX_STORIES = 5
DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() == "true"
ROOT = Path(__file__).parent.parent
OUTPUT_DIR = ROOT / "output"
FEEDBACK_DIR = ROOT / "data" / "feedback"
SITE_DIR = ROOT / "site" / "content" / "briefings"


def _parse_draft(text: str) -> tuple[list[str], str]:
    parts = re.split(r"\n---\n", text)
    header = parts[0].strip()
    stories = [p.strip() for p in parts[1:] if p.strip()]
    return stories, header


def load_draft(beat: str = "payments") -> tuple[list[str], str]:
    date_str = datetime.now().strftime("%Y-%m-%d")
    if github_api.available():
        text, _ = github_api.read_file(f"output/{beat}/{date_str}.md")
        if not text:
            return [], f"No draft found for {date_str}."
        return _parse_draft(text)
    else:
        path = OUTPUT_DIR / beat / f"{date_str}.md"
        if not path.exists():
            return [], f"No draft found for {date_str}."
        return _parse_draft(path.read_text())


def compute_diff(original: str, edited: str) -> str:
    orig_lines = original.splitlines(keepends=True)
    edit_lines = edited.splitlines(keepends=True)
    return "".join(difflib.unified_diff(orig_lines, edit_lines, fromfile="original", tofile="edited"))


def _pipeline_outputs(header: str, stories: list | None = None) -> list:
    """Build the full output list for load_outputs. Stories=None means no-op on story rows."""
    if stories is None:
        return [gr.update(value=header)] + [gr.update()] * (MAX_STORIES * 4)
    outputs = [header]
    for _ in range(MAX_STORIES):
        outputs += [gr.update(visible=False), gr.update(value=""), gr.update(value="Approve"), gr.update(value="", visible=False)]
    return outputs


def on_run_and_load():
    yield _pipeline_outputs("*Fetching feeds...*")
    try:
        entries = fetch_beat("payments")
        entries = filter_recent(entries)
        entries = filter_keywords(entries, "payments")
        if not entries:
            yield _pipeline_outputs("**No recent entries found — try again later.**", stories=[])
            return
        yield _pipeline_outputs(f"*{len(entries)} entries fetched. Generating briefing — this takes ~30 seconds...*")
        briefing = generate_briefing("payments", entries)
        save_draft("payments", briefing)
    except Exception as e:
        yield _pipeline_outputs(f"**Pipeline error:** {e}", stories=[])
        return
    yield on_load_draft()


def on_load_draft():
    stories, header = load_draft()
    outputs = [f"### {header}"]
    for i in range(MAX_STORIES):
        if i < len(stories):
            outputs += [
                gr.update(visible=True),
                gr.update(value=stories[i]),
                gr.update(value="Approve"),
                gr.update(value="", visible=False),
            ]
        else:
            outputs += [
                gr.update(visible=False),
                gr.update(value=""),
                gr.update(value="Approve"),
                gr.update(value="", visible=False),
            ]
    return outputs


def on_decision_change(decision):
    return gr.update(visible=decision == "Reject")


def on_save(*args):
    texts = list(args[:MAX_STORIES])
    decisions = list(args[MAX_STORIES : MAX_STORIES * 2])
    reasons = list(args[MAX_STORIES * 2 :])

    originals, _ = load_draft()
    if not originals:
        return "No draft loaded — nothing to save."

    date_str = datetime.now().strftime("%Y-%m-%d")
    records = []
    for orig, edited, decision, reason in zip(originals, texts, decisions, reasons):
        if not edited.strip():
            continue
        records.append({
            "original": orig,
            "edited": edited,
            "diff": compute_diff(orig, edited),
            "decision": decision,
            "reason": reason or None,
        })
    payload = json.dumps({"date": date_str, "beat": "payments", "stories": records}, indent=2)

    if github_api.available():
        ok = github_api.write_file(
            f"data/feedback/{date_str}.json",
            payload,
            f"Save feedback {date_str}",
        )
        if not ok:
            return "Error saving feedback to GitHub."
    else:
        FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
        (FEEDBACK_DIR / f"{date_str}.json").write_text(payload)

    return f"Feedback saved — {len(records)} stories recorded."


def on_publish(*args):
    texts = list(args[:MAX_STORIES])
    decisions = list(args[MAX_STORIES:])

    approved = [
        edited for edited, decision in zip(texts, decisions)
        if edited.strip() and decision == "Approve"
    ]
    if not approved:
        return "No approved stories to publish."

    date_str = datetime.now().strftime("%Y-%m-%d")
    date_display = datetime.now().strftime("%B %-d, %Y")
    body = "\n\n---\n\n".join(approved)
    content = (
        f'---\ntitle: "European Payments Briefing — {date_display}"\n'
        f'date: {date_str}\ndraft: false\nbeat: payments\n---\n\n{body}'
    )
    n = len(approved)
    path = f"site/content/briefings/{date_str}.md"

    if github_api.available():
        ok = github_api.write_file(path, content, f"Publish briefing {date_str}")
        if not ok:
            return "Error publishing to GitHub."
    else:
        SITE_DIR.mkdir(parents=True, exist_ok=True)
        (SITE_DIR / f"{date_str}.md").write_text(content)

    return f"Published {n} {'story' if n == 1 else 'stories'} to {path}"


# --- UI ---

with gr.Blocks(title="Skald — Editorial Dashboard") as app:
    with gr.Row():
        gr.Markdown("# Skald — Editorial Dashboard")
        load_btn = gr.Button("Generate today's draft", variant="primary", scale=0)

    header_md = gr.Markdown("*Loading draft...*")

    groups, texts, decisions, reasons = [], [], [], []
    for i in range(MAX_STORIES):
        with gr.Group(visible=False) as grp:
            with gr.Row():
                gr.Markdown(f"#### Story {i + 1}")
                dec = gr.Radio(
                    ["Approve", "Reject"],
                    value="Approve",
                    label="Decision",
                    scale=0,
                )
            rsn = gr.Textbox(
                placeholder="Reason (e.g. 'not news', 'vendor announcement', 'already covered')",
                label="Reason",
                visible=False,
            )
            txt = gr.Textbox(lines=18, label="", show_label=False, container=False)
        groups.append(grp)
        texts.append(txt)
        decisions.append(dec)
        reasons.append(rsn)

    with gr.Row():
        status_md = gr.Markdown("")
        if not DEMO_MODE:
            save_btn = gr.Button("Save feedback", variant="secondary", scale=0)
            publish_btn = gr.Button("Publish approved", variant="primary", scale=0)

    # Load draft — auto on startup and on button click
    load_outputs = [header_md]
    for i in range(MAX_STORIES):
        load_outputs += [groups[i], texts[i], decisions[i], reasons[i]]

    app.load(on_load_draft, outputs=load_outputs)
    load_btn.click(on_run_and_load, outputs=load_outputs)

    # Decision → reason visibility
    for dec, rsn in zip(decisions, reasons):
        dec.change(on_decision_change, inputs=dec, outputs=rsn)
        dec.select(on_decision_change, inputs=dec, outputs=rsn)

    if not DEMO_MODE:
        feedback_inputs = texts + decisions + reasons
        save_btn.click(on_save, inputs=feedback_inputs, outputs=status_md)
        publish_btn.click(
            on_publish,
            inputs=texts + decisions,
            outputs=status_md,
        )


if __name__ == "__main__":
    app.launch(theme=gr.themes.Base())
