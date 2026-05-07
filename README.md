# Skald

An AI-driven content pipeline producing daily briefings. Built as a portfolio demonstration of prompt engineering discipline, editorial feedback loops and a systematic path from human-edited to automated publication.

**Live output:** [vikingmedia.org/skald](https://vikingmedia.org/skald)  
**Editorial dashboard:** [nick385/skald on HuggingFace Spaces](https://huggingface.co/spaces/nick385/skald)

---

## What it does

Each weekday at 06:00 UTC, Skald:

1. Fetches and filters stories from 11 RSS feeds (regulators, trade press, Google Alerts)
2. Passes the filtered intake to Claude via a versioned prompt stack
3. Generates a draft briefing of 3–5 stories, each with a short analysis note
4. Commits the draft to the repo, ready for editorial review

The editor opens the Gradio dashboard, reviews the draft, edits where needed and publishes with one click. The published briefing is committed to the Hugo site source and Cloudflare Pages deploys it automatically.

## The editorial feedback loop

Generation quality improves over time through two feedback channels:

**Writing quality** — the dashboard records diffs between the AI draft and the published version. `tools/extract_learning.py` analyses these diffs and proposes style rules for review. Accepted rules are committed to `prompts/payments/style_rules.yaml` and injected into the system prompt on every subsequent run.

**Story selection** — the editor can reject stories with a reason (such as "not news", "vendor announcement", "already covered"). Rejection reasons become training signal for refining the story selection criteria in the story prompt.

**Duplicate avoidance** — approved story headlines are committed to `data/recently_covered.yaml`, which is injected into the user prompt so Claude can make nuanced decisions about whether a returning topic has a genuinely new angle.

This is prompt refinement via feedback loop, not fine-tuning. The result is a system whose output improves iteratively as patterns in human edits surface as explicit, auditable rules.

## Architecture

```
GitHub Actions (generate.yml)
    ↓ 06:00 UTC Mon–Fri
ingester/fetcher.py  →  RSS feeds (FCA, EBA, ECB, Finextra, PYMNTS, …)
    ↓ filtered intake
generator/client.py  →  Claude API
    ↓ draft Markdown
output/payments/YYYY-MM-DD.md  (committed to repo)
    ↓
HuggingFace Space (Gradio dashboard)
    ↓ editor reviews, edits, approves
site/content/briefings/YYYY-MM-DD.md  (committed via GitHub API)
    ↓
Cloudflare Pages  →  vikingmedia.org/skald
```

## Directory structure

```
beats/           Beat config YAML (sources, keyword filters)
prompts/         System and story prompts — versioned YAML, one dir per beat
ingester/        Feed fetching, normalisation, recency and keyword filtering
generator/       Claude API calls, prompt assembly, draft output
dashboard/       Gradio editorial interface
site/            Hugo static site source
tools/           Post-session learning tools (extract_learning.py, test_filters.py)
data/            recently_covered.yaml — committed; feedback/ — gitignored
.github/         GitHub Actions workflows (generate, deploy, sync HF Space)
```

## Prompt stack

Each beat has three prompt files:

| File | Purpose |
|------|---------|
| `prompts/payments/system.yaml` | Voice, editorial stance, style rules block |
| `prompts/payments/story.yaml` | Story selection criteria, news recognition checks, output format |
| `prompts/payments/style_rules.yaml` | Accumulated house style rules extracted from editorial diffs |

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

# After editing in the dashboard, extract learnings
python tools/extract_learning.py
```

The dashboard (`dashboard/app.py`) runs locally with `python dashboard/app.py` and falls back to the local filesystem when no `GITHUB_TOKEN` is set.

## Tech stack

- **Claude API** (Anthropic) — content generation via `generator/client.py`
- **feedparser** — RSS ingestion
- **Gradio** — editorial dashboard, deployed to HuggingFace Spaces
- **Hugo** — static site generation
- **GitHub Actions** — scheduling, generation, deployment
- **Cloudflare Pages** — site hosting

## What's intentionally omitted

- `ANTHROPIC_API_KEY` — GitHub Actions secret, not in the repo
- `GITHUB_TOKEN` (PAT) — HuggingFace Space secret, not in the repo
- `data/feedback/` — editorial session data, gitignored
- `output/` — generated drafts, gitignored
- `public/skald/` — Hugo build output, gitignored (built by Cloudflare Pages on deploy)
