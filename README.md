# Skald

An AI-driven content pipeline with a human editorial feedback loop, producing daily briefings. Built as a portfolio demonstration of prompt engineering discipline, editorial feedback loops and a systematic path from human-edited to automated publication.

**Live output:** [vikingmedia.org/skald](https://vikingmedia.org/skald)

---

## What it does

From the Gradio dashboard, the editor clicks **Trigger generation**, which dispatches a GitHub Actions workflow that:

1. Fetches and filters stories from 11 RSS feeds (regulators, trade press, Google Alerts)
2. Passes the filtered intake to Claude via a versioned prompt stack
3. Generates a draft briefing of 3–5 stories, each with a short analysis note
4. Commits the draft to `output/payments/YYYY-MM-DD.yaml` in this repo

The editor then clicks **Load draft**, reviews it in the dashboard, edits where needed and publishes with one click. Publishing commits the briefing to `site/content/briefings/YYYY-MM-DD.md` in the separate `skaldnick/vikingmedia-site` repo, which Cloudflare Pages auto-deploys.

Generation is manually triggered, not scheduled — there is no cron.

## The editorial feedback loop

Generation quality improves over time through three feedback channels:

**Writing quality** — clicking **Save feedback** in the dashboard commits a diff between the AI draft and the edited version, plus any notes the editor wrote, to `data/feedback/YYYY-MM-DD.json`. That push triggers `extract_learning.yml`, a GitHub Action that calls Claude to propose style rules from the diffs *and* the notes (notes are treated as an authoritative statement of a rule, not something to infer), queuing new proposals in `data/proposed_style_rules.yaml`. The editor reviews the queue in the dashboard's **Proposed style rules** section — editing or deleting lines freely — before saving promotes the rest into `prompts/payments/style_rules.yaml`, which is injected into the system prompt on every subsequent run.

**Story selection** — the editor can reject stories with a reason (such as "not news", "vendor announcement", "already covered"). Rejection reasons become training signal for refining the story selection criteria in the story prompt.

**Duplicate avoidance** — approved story headlines are committed to `data/recently_covered.yaml`, which is injected into the user prompt so Claude can judge whether a returning topic has a genuinely new angle. The bar is deliberately strict: a different outlet restating the same underlying fact doesn't count as new, and a follow-up story must cite only its own new source — never the earlier coverage — in `sources`.

This is prompt refinement via feedback loop, not fine-tuning. The result is a system whose output improves iteratively as patterns in human edits surface as explicit, auditable rules.

## Architecture

```
HuggingFace Space (Gradio dashboard)
    ↓ editor clicks "Trigger generation"
GitHub Actions (generate.yml — manual dispatch, no schedule)
    ↓
ingester/fetcher.py  →  RSS feeds (FCA, EBA, ECB, Finextra, PYMNTS, …)
    ↓ filtered intake
generator/client.py  →  Claude API
    ↓ draft YAML
output/payments/YYYY-MM-DD.yaml  (committed to this repo)
    ↓
HuggingFace Space (Gradio dashboard)
    ↓ editor reviews, edits, approves, publishes
skaldnick/vikingmedia-site: site/content/briefings/YYYY-MM-DD.md  (committed via GitHub API)
    ↓
Cloudflare Pages  →  vikingmedia.org/skald
```

```
dashboard "Save feedback"
    ↓
data/feedback/YYYY-MM-DD.json  (committed to this repo)
    ↓ push triggers
GitHub Actions (extract_learning.yml)
    ↓ Claude proposes rules from diffs + editor notes
data/proposed_style_rules.yaml
    ↓ editor reviews in dashboard's "Proposed style rules" section
prompts/payments/style_rules.yaml  (injected into every generation run)
```

## Directory structure

```
beats/           Beat config YAML (sources, keyword filters)
prompts/         System and story prompts — versioned YAML, one dir per beat
ingester/        Feed fetching, normalisation, recency and keyword filtering
generator/       Claude API calls, prompt assembly, draft output
dashboard/       Gradio editorial interface
tools/           Post-session tools (extract_learning.py, test_filters.py, check_sync.sh)
output/          Generated draft briefings (YAML) — committed to origin/main
data/            recently_covered.yaml, recently_rejected.yaml, proposed_style_rules.yaml,
                 feedback/ — all committed to origin/main; git is the pipeline's only
                 persistence layer (the HF Space filesystem is ephemeral, no database)
.github/         GitHub Actions workflows (generate, extract_learning, sync HF Space)
```

The Hugo site source and Cloudflare Pages web root live in the separate `skaldnick/vikingmedia-site` repo — Skald itself is pipeline-only.

## Prompt stack

Each beat has three prompt files:

| File | Purpose |
|------|---------|
| `prompts/payments/system.yaml` | Voice, editorial stance, style rules block |
| `prompts/payments/story.yaml` | Story selection criteria, news recognition checks, output format |
| `prompts/payments/style_rules.yaml` | Accumulated house style rules extracted from editorial feedback |

Prompts are data, not code. The full edit history in git shows how the prompt stack has evolved — that evolution is part of what this project demonstrates.

## Running locally

```bash
# Install dependencies
pip install -r requirements.txt

# Add your Anthropic key
echo "ANTHROPIC_API_KEY=sk-..." > .env

# Fetch and filter today's feeds
python -m ingester.fetcher

# Generate a draft briefing
python -m generator.client

# Style rule extraction runs automatically on push to data/feedback/ via
# .github/workflows/extract_learning.yml — run manually only to test changes
python tools/extract_learning.py
```

The dashboard (`dashboard/app.py`) runs locally with `python dashboard/app.py` and falls back to the local filesystem when no `GITHUB_TOKEN` is set.

## Tech stack

- **Claude API** (Anthropic) — content generation via `generator/client.py`
- **feedparser** — RSS ingestion
- **Gradio** — editorial dashboard, deployed to HuggingFace Spaces
- **Hugo** — static site generation (in the separate `vikingmedia-site` repo)
- **GitHub Actions** — generation, style-rule extraction, HF Space sync
- **Cloudflare Pages** — site hosting

## What's intentionally omitted

- `ANTHROPIC_API_KEY` — GitHub Actions secret, not in the repo
- `GITHUB_TOKEN` (PAT) — HuggingFace Space secret, not in the repo
- `.env` — local secrets, gitignored
- `data/raw/` — cached raw feed snapshots for offline filter testing, gitignored

`output/` and `data/feedback/` are *not* omitted — they're committed to origin/main intentionally, since git is the pipeline's only persistence layer.
