# Beat Config Schema

Each beat is defined by a YAML file in this directory.

## Required fields
```yaml
name: string           # Short identifier, used in file paths and logs
title: string          # Human-readable title
description: string    # One-line description of the beat's focus
active: boolean        # Whether this beat runs in the pipeline

sources:               # List of RSS/Atom feed URLs
  - url: string        # Feed URL
    name: string       # Short label
    tier: string       # primary | secondary | regulatory

output:
  format: string       # daily_briefing | weekly_roundup
  stories_per_run: int # Target number of stories per run
  min_stories: int     # Minimum to publish (skip run if below this)

schedule:
  cron: string         # Cron expression for GitHub Actions
```

## Notes
- Tier `regulatory` sources are always included regardless of story count
- `min_stories` prevents publishing thin or empty briefings