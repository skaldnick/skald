"""GitHub API helpers for reading and writing repo files.

Used by the dashboard when running on HuggingFace Spaces, where the
local filesystem is ephemeral. Falls back to local filesystem when
GITHUB_TOKEN is not set (local development).
"""
import base64
import os

import requests

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "skaldnick/vikingmedia-site")
GITHUB_PIPELINE_REPO = os.environ.get("GITHUB_PIPELINE_REPO", "skaldnick/skald")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")


def available() -> bool:
    return bool(GITHUB_TOKEN)


def _headers() -> dict:
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


_TIMEOUT = 15  # seconds


def read_file(path: str, repo: str | None = None) -> tuple[str | None, str | None]:
    """Read a file from the repo. Returns (content, sha) or (None, None)."""
    url = f"https://api.github.com/repos/{repo or GITHUB_REPO}/contents/{path}"
    try:
        response = requests.get(url, headers=_headers(), params={"ref": GITHUB_BRANCH}, timeout=_TIMEOUT)
    except requests.exceptions.RequestException:
        return None, None
    if response.status_code == 200:
        data = response.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return content, data["sha"]
    return None, None


def write_file(path: str, content: str, message: str, repo: str | None = None) -> bool:
    """Create or update a file in the repo. Returns True on success."""
    target_repo = repo or GITHUB_REPO
    url = f"https://api.github.com/repos/{target_repo}/contents/{path}"
    _, sha = read_file(path, repo=target_repo)
    data = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        data["sha"] = sha
    try:
        response = requests.put(url, headers=_headers(), json=data, timeout=_TIMEOUT)
    except requests.exceptions.RequestException:
        return False
    return response.status_code in (200, 201)


def dispatch_workflow(workflow_file: str) -> bool:
    """Trigger a workflow_dispatch event. Returns True on success."""
    url = f"https://api.github.com/repos/{GITHUB_PIPELINE_REPO}/actions/workflows/{workflow_file}/dispatches"
    try:
        response = requests.post(url, headers=_headers(), json={"ref": GITHUB_BRANCH}, timeout=_TIMEOUT)
    except requests.exceptions.RequestException:
        return False
    return response.status_code == 204
