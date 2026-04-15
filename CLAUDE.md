# Skald — Claude Code Context

## What this project is
Skald is an AI-driven content pipeline producing daily European payments 
and open banking briefings. It ingests free news feeds, generates drafts 
via the Claude API, routes them through a Gradio editorial dashboard for 
human review and editing, and publishes to vikingmedia.org.

Built as a portfolio demonstration of prompt engineering discipline, 
editorial feedback loops, and the transition from human-edited to 
automated publication.

## Directory structure
```
/beats/          Beat config YAML files (one per topic)
/prompts/        System and story prompts (versioned YAML, one dir per beat)
/ingester/       Feed fetching and normalisation
/generator/      Claude API calls and draft production
/dashboard/      Gradio editorial interface
/output/         Generated drafts (Markdown, gitignored)
/data/feedback/  Edit diffs and quality scores (gitignored)
/site/           Hugo static site source
/docs/           Project documentation
```

## Key conventions
- Beat configs are YAML; schema defined in /beats/README.md
- Prompts are YAML files, never hardcoded in Python
- All Claude API calls go through generator/client.py — no direct API 
  calls elsewhere
- API keys via environment variables only (.env, never committed)
- /data/feedback/ is gitignored — do not add to version control
- /output/ is gitignored — generated files, not source files
- Commit messages: describe what was built and why, not just what changed

## APIs and services
- Claude API (Anthropic) — content generation
- feedparser — RSS ingestion
- Gradio — dashboard UI (deployed to HuggingFace Spaces)
- Hugo — static site generation
- GitHub Actions — scheduling and deployment
- Cloudflare Pages — site hosting (vikingmedia.org)

## Docs
- /docs/brief.md — project purpose, audience, owner background
- /docs/decisions.md — architectural decisions and rationale
- /docs/sources.md — feed source registry for the payments beat

## Directory structure (additional)
```
/hf-space/       HuggingFace Space repo (dashboard + dependencies, pushed separately)
/public/         Cloudflare Pages web root (vikingmedia.org landing page + Hugo output)
/public/skald/   Hugo build output (gitignored — built by Cloudflare Pages on deploy)
/.github/        GitHub Actions workflows
```

## Keeping hf-space/ in sync
`hf-space/` is a separate git repo (remote: HuggingFace Spaces). It is a
near-mirror of the main repo's dashboard code. When `dashboard/app.py` or
`dashboard/github_api.py` change, the same changes must be applied to
`hf-space/dashboard/` and pushed separately:

```bash
cd hf-space/
git add dashboard/app.py dashboard/github_api.py
git commit -m "..."
git push
```

The HuggingFace Space restarts automatically on push. The two repos can
diverge if a change is committed to the main repo but not pushed to hf-space —
check both when debugging dashboard behaviour.

## Current status
Full cloud pipeline operational. First briefing published April 13, 2026.

### Cloud architecture
1. **GitHub Actions** (`generate.yml`) — runs `python -m generator.client` at 06:00 UTC Mon–Fri, commits draft to `output/payments/YYYY-MM-DD.md`. Can also be triggered manually via workflow_dispatch.
2. **HuggingFace Space** (`nick385/skald`) — Gradio dashboard; editor clicks "Trigger generation" to dispatch the GitHub Actions workflow, then "Load draft" once it completes. Reviews, edits, approves stories, and publishes to `site/content/briefings/YYYY-MM-DD.md` via GitHub API commit.
3. **Cloudflare Pages** — auto-deploys on push to main; runs `hugo --minify --source site`, serves from `public/`; live at vikingmedia.org/skald/

### Secrets and tokens
- `ANTHROPIC_API_KEY` — required in GitHub Actions only (not HF Space)
- `GITHUB_TOKEN` (PAT) — required in HF Space; needs `repo` and `workflow` scopes

### Components built
- ingester/fetcher.py — feed fetching, normalisation, recency filter (3 days), keyword filter
- generator/client.py — prompt assembly, Claude API call, draft output; loads style_rules.yaml and recently_covered.yaml and injects both into prompts; outputs a `title:` line at the top for the dashboard to parse
- prompts/payments/system.yaml — voice, style, editorial stance
- prompts/payments/story.yaml — selection criteria, news recognition, output format; instructs Claude to produce a concise briefing title
- prompts/payments/style_rules.yaml — accumulated house style rules extracted from editorial diffs; injected into system prompt on every generation run
- data/recently_covered.yaml — approved and published story headlines by date; injected into user prompt to prevent repeat coverage; committed to repo so GitHub Actions can access it
- dashboard/app.py — Gradio editorial interface (trigger generation, load draft, edit, save feedback, approve/reject, publish); pre-fills briefing title from AI draft
- dashboard/github_api.py — GitHub API helpers (read/write files, dispatch workflows); dashboard uses this when GITHUB_TOKEN set, local filesystem otherwise
- beats/payments.yaml — source config (11 sources: regulatory, Google Alerts, trade press)
- beats/payments_filters.yaml — keyword filter config (global + per-source include/exclude, passthrough)
- site/ — Hugo static site; theme at site/themes/skald/; briefings at site/content/briefings/
- .github/workflows/generate.yml — scheduled briefing generation (06:00 UTC Mon–Fri) + manual trigger
- tools/fetch_raw.py — fetch and cache raw feed snapshot for offline filter testing
- tools/test_filters.py — test filter configs against cached snapshots; shows per-source pass/cut
- tools/extract_learning.py — post-session learning tool; auto-updates recently_covered.yaml with approved stories; calls Claude to propose style rules from editorial diffs for human review

### Post-session workflow
After each editorial session (save feedback in dashboard):
```bash
python tools/extract_learning.py   # updates recently_covered.yaml, proposes style rules
# review output, add keepers to prompts/payments/style_rules.yaml
git add data/recently_covered.yaml prompts/payments/style_rules.yaml
git commit -m "..."
```

### Next priorities
- Design TL;DR/summary product — concise daily digest and/or teaser email, separate from the full briefing
- HF Space dashboard redesign — multi-tab layout:
  - **Today** tab: existing briefing workflow, unchanged
  - **Briefings** tab: list published briefings, click to view (read-only initially; editing deferred)
  - **Settings** tab: raw YAML editors for system prompt, story prompt, style rules, sources, and keyword filters — each as a textarea with a Save button
  - Navigation via `gr.Tab` inside `gr.Blocks`; no separate landing page needed
- Website layout improvements (separate from dashboard work)
