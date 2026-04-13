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

## Current status
Pipeline operational. First briefing generated March 26, 2025.

Components built:
- ingester/fetcher.py — feed fetching, normalisation, recency filter (3 days), keyword filter
- generator/client.py — prompt assembly, Claude API call, draft output
- prompts/payments/system.yaml — voice, style, editorial stance
- prompts/payments/story.yaml — selection criteria, news recognition, output format
- dashboard/app.py — Gradio editorial interface (generate & load, edit, approve/reject, publish)
- beats/payments.yaml — source config (11 sources: regulatory, Google Alerts, trade press; EBA dropped)
- beats/payments_filters.yaml — keyword filter config (global + per-source include/exclude, passthrough)
- tools/fetch_raw.py — fetch and cache raw feed snapshot for offline filter testing
- tools/test_filters.py — test filter configs against cached snapshots; shows per-source pass/cut

Next priorities: Hugo site scaffold; GitHub Actions schedule; source/keyword management in dashboard.