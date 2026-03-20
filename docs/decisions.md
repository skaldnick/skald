# Architectural Decisions

## Beat selection: European payments & open banking
Chosen over corporate treasury (thinner free source volume) and broad 
UK/EU regulation (too dry for portfolio demo). European payments has high 
daily source volume from free feeds (FCA, EBA, ECB, Finextra, PYMNTS), 
genuine specialisation that signals expertise, and maps to an obvious 
client type (banks, payment processors, fintech scale-ups).

## Output format: daily briefing
3-5 stories per day, each with a short analysis note. Tight enough to 
show editorial judgement, frequent enough to build a feedback dataset 
quickly and demonstrate consistent automation.

## Feedback loop: prompt refinement, not fine-tuning
Rather than fine-tuning a model (costly, complex, hard to demonstrate), 
the system logs diffs between AI draft and edited version plus quality 
scores. Patterns in edits surface as prompt suggestions. Approved edits 
become few-shot examples injected into future prompts. This is more 
practical and more demonstrable to clients.

## Dashboard: Gradio on HuggingFace Spaces
Chosen over custom Flask app. Deploys without infrastructure configuration, 
provides a public URL usable as a portfolio artefact in its own right, 
and is fast to build. Accepts a public demo mode that strips edit 
functionality and shows quality score trends over time.

## Static site: Hugo on Cloudflare Pages
Hugo chosen for generation speed and simplicity. Cloudflare Pages for 
free hosting with GitHub Actions deploy integration. Stories carry 
"AI + edited by Nick" byline during training phase, transitioning to 
"Viking Media AI" when running fully automated.

## Prompt storage: versioned YAML files
Prompts are data, not code. Each beat has a system prompt and a 
story prompt in /prompts/{beat}/. Versioned in git so the history of 
prompt refinement is legible — this is part of the portfolio story.

## Repo structure: single public repo
Code, prompts and architecture docs are public (the portfolio). 
Raw feedback annotations (edit diffs, scores) live in /data/feedback/ 
which is gitignored. No private repo needed.

## Tooling: Claude Code for implementation, Claude.ai for strategy
Claude Code handles all code generation and file operations.
Claude.ai (this project) handles architectural decisions, beat design, 
prompt strategy, and briefing. DECISIONS.md is the bridge between them.