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

## Prompt design: principles over style guides
System prompts establish editorial principles, not exhaustive rules. A long style
guide in the prompt produces writing that ticks boxes rather than internalises a
voice. Sharp, concrete examples do more work than abstract guidance.

A core principle: jargon does not demonstrate expertise — clarity does. Where a
technical term is the right word, use it; where plain language serves better,
prefer it. This is worth stating explicitly in prompts because models tend to
pattern-match "expert writing" with jargon-heavy writing.

Prompts are versioned in git and expected to evolve. Specific "write like this,
not like this" examples are added incrementally as patterns emerge from editorial
feedback — not front-loaded into the initial prompt.

## Dashboard: two feedback channels — text editing and selection review
The editorial dashboard needs to capture two distinct types of feedback:

1. **Text editing** — inline edits to the draft, captured as diffs. These teach
   the system about voice, structure, and writing quality.

2. **Selection feedback** — judgements on whether a story should have been chosen
   at all. A story can be well-written but wrongly selected. This feedback teaches
   the system editorial news judgement: what counts as news, what is too stale,
   what is too thin, what duplicates recent coverage.

Selection feedback should be lightweight: a reject/flag action on each story with
an optional reason (e.g. "not news — original event is weeks old", "vendor
announcement", "too US-focused", "already covered"). Reasons become training
signal for the selection stage of the pipeline, distinct from the writing-quality
signal captured by text diffs.

Both channels feed into /data/feedback/ and are used separately — text diffs
inform prompt refinement for the generator; selection feedback informs the
"news nose" relevance scoring layer.

## Story selection: editorial "news nose" over keyword filtering
The goal is for Skald to develop genuine editorial judgement — selecting
stories based on significance, novelty, and relevance to the beat's
audience rather than mechanical keyword matching. Keyword filtering is
a useful first step to discard obvious noise, but the target is a model
that can weigh up the day's intake and decide what matters.

This capability will be built in stages:
1. Keyword filter — cheap noise reduction at ingestion time
2. Relevance scoring via Claude — rate each story against the beat focus
   before drafting; discard low-scorers
3. Novelty detection — deprioritise stories duplicating recent coverage
4. Editorial feedback loop — use dashboard edit history (kept/cut/rewritten)
   as signal for what this beat's audience considers important

The "news nose" likely lives in two places: the ingester (filter before
generation) and the generator (generate candidates, then select). The
feedback loop in /data/feedback/ is the key training signal — patterns
in human edits teach the model what "important" means for this beat.

## Tooling: Claude Code for implementation, Claude.ai for strategy
Claude Code handles all code generation and file operations.
Claude.ai (this project) handles architectural decisions, beat design, 
prompt strategy, and briefing. DECISIONS.md is the bridge between them.