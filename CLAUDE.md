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
/docs/           Project documentation
```

Note: the Hugo site source (`site/`) and Cloudflare Pages web root (`public/`) have moved
to the separate `skaldnick/vikingmedia-site` repo. Skald is pipeline-only.

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
/.github/        GitHub Actions workflows
/hf-readme.md    HuggingFace Space card (README synced to Space on deploy)
```

## HuggingFace Space sync
The HuggingFace Space is kept in sync automatically via `.github/workflows/sync-hf-space.yml`.
Any push to main that touches `dashboard/`, `generator/`, `ingester/`, `prompts/`, `beats/`,
`requirements.txt`, or `hf-readme.md` triggers the workflow, which clones the Space,
replaces its contents, and pushes. The workflow can also be triggered manually from the
Actions tab. There is no separate local `hf-space/` repo to maintain.

### Deploying changes to the Space (from a Claude Code worktree branch)
1. Commit and push the branch: `git push origin <branch>`
2. Go to github.com/skaldnick/skald — click **Compare & pull request**
3. Click **Create pull request**
4. Click **Merge pull request** → **Confirm merge**
5. The sync workflow fires automatically; Space is updated within ~2 minutes.

## Current status
Full cloud pipeline operational. First briefing published April 13, 2026.

### Cloud architecture
1. **GitHub Actions** (`generate.yml`) — runs `python -m generator.client` at 06:00 UTC Mon–Fri, commits draft to `output/payments/YYYY-MM-DD.md`. Can also be triggered manually via workflow_dispatch.
2. **HuggingFace Space** (`nick385/skald`) — Gradio dashboard; editor clicks "Trigger generation" to dispatch the GitHub Actions workflow, then "Load draft" once it completes. Reviews, edits, approves stories, and publishes to `site/content/briefings/YYYY-MM-DD.md` in `skaldnick/vikingmedia-site` via GitHub API commit.
3. **Cloudflare Pages** — watches `skaldnick/vikingmedia-site`; auto-deploys on push; runs `hugo --minify --source site`, serves from `public/`; live at vikingmedia.org/skald/

### Secrets and tokens
- `ANTHROPIC_API_KEY` — required in GitHub Actions only (not HF Space)
- `GITHUB_TOKEN` (PAT) — required in HF Space; needs `repo` and `workflow` scopes

### Components built
- ingester/fetcher.py — feed fetching, normalisation, recency filter (3 days), keyword filter
- generator/client.py — prompt assembly, Claude API call, draft output; loads style_rules.yaml, recently_covered.yaml, and recently_rejected.yaml and injects all into prompts; outputs a `title:` line at the top for the dashboard to parse
- prompts/payments/system.yaml — voice, style, editorial stance
- prompts/payments/story.yaml — selection criteria, news recognition, output format; instructs Claude to produce a concise briefing title
- prompts/payments/style_rules.yaml — accumulated house style rules extracted from editorial diffs; injected into system prompt on every generation run
- data/recently_covered.yaml — approved and published story headlines by date; updated automatically on publish; injected into user prompt to prevent repeat coverage; committed to repo so GitHub Actions can access it
- data/recently_rejected.yaml — editorially rejected story headlines by date; updated automatically on publish; injected into user prompt as a hard block against re-selection
- dashboard/app.py — Gradio editorial interface (trigger generation, load draft, edit, save feedback, approve/reject, publish); pre-fills briefing title from AI draft; updates recently_covered.yaml and recently_rejected.yaml in pipeline repo on publish
- dashboard/github_api.py — GitHub API helpers (read/write files, dispatch workflows); dashboard uses this when GITHUB_TOKEN set, local filesystem otherwise. Uses two repo env vars: GITHUB_REPO (vikingmedia-site, for publishing briefings) and GITHUB_PIPELINE_REPO (skald, for workflow dispatch, reading drafts, and writing feedback/coverage files)
- beats/payments.yaml — source config (11 sources: regulatory, Google Alerts, trade press)
- beats/payments_filters.yaml — keyword filter config (global + per-source include/exclude, passthrough)
- .github/workflows/generate.yml — scheduled briefing generation (06:00 UTC Mon–Fri) + manual trigger
- .github/workflows/sync-hf-space.yml — syncs dashboard and source files to HuggingFace Space on push to main; also triggerable manually
- tools/fetch_raw.py — fetch and cache raw feed snapshot for offline filter testing
- tools/test_filters.py — test filter configs against cached snapshots; shows per-source pass/cut
- tools/extract_learning.py — post-session style learning tool; reads feedback JSON (local or from GitHub pipeline repo); calls Claude to propose style rules from editorial diffs for human review; recently_covered/rejected updates are now handled automatically on publish

### Post-session workflow
After each editorial session, to extract style rules from edits:
```bash
python tools/extract_learning.py   # proposes style rules from editorial diffs
# review output, add keepers to prompts/payments/style_rules.yaml
git add prompts/payments/style_rules.yaml
git commit -m "..."
```
Note: recently_covered.yaml and recently_rejected.yaml are updated automatically
when you click "Publish approved" in the dashboard — no manual step needed.

### Next priorities
- Design TL;DR/summary product — concise daily digest and/or teaser email, separate from the full briefing
- HF Space dashboard redesign — multi-tab layout:
  - **Today** tab: existing briefing workflow, unchanged
  - **Briefings** tab: list published briefings, click to view (read-only initially; editing deferred)
  - **Settings** tab: raw YAML editors for system prompt, story prompt, style rules, sources, and keyword filters — each as a textarea with a Save button
  - Navigation via `gr.Tab` inside `gr.Blocks`; no separate landing page needed
- Independent reporting / contextual research — pre-draft step where Claude identifies claims needing verification, queries a search API, and incorporates results before writing; even a lightweight version (fetching older relevant sources for context) would improve story quality
