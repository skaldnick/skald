#!/bin/bash
# Reports how far the current branch has drifted from origin/main.
#
# The HF Space dashboard commits directly to origin/main via the GitHub
# Content API (daily briefing drafts, feedback, recently_covered/rejected
# updates) — a local clone never sees those pushes and can silently fall
# days behind. Run this before starting local work.
set -e

git fetch origin --quiet

behind=$(git rev-list --count HEAD..origin/main)
ahead=$(git rev-list --count origin/main..HEAD)

if [ "$behind" -gt 0 ]; then
    echo "⚠️  Local branch is $behind commit(s) behind origin/main (and $ahead ahead)."
    echo "    The dashboard writes to origin/main directly — pull before you branch off stale state:"
    echo "    git pull --rebase origin main"
    exit 1
else
    if [ "$ahead" -gt 0 ]; then
        echo "✅ Up to date with origin/main ($ahead local commit(s) not yet pushed)."
    else
        echo "✅ Up to date with origin/main."
    fi
fi
