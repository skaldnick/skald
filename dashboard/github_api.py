"""GitHub API helpers for reading and writing repo files.

Used by the dashboard when running on HuggingFace Spaces, where the
local filesystem is ephemeral. Falls back to local filesystem when
GITHUB_TOKEN is not set (local development).
"""
import base64
import os

import requests

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "skaldnick/skald")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")


def available() -> bool:
    return bool(GITHUB_TOKEN)


def _headers() -> dict:
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


def read_file(path: str) -> tuple[str | None, str | None]:
    """Read a file from the repo. Returns (content, sha) or (None, None)."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    response = requests.get(url, headers=_headers(), params={"ref": GITHUB_BRANCH})
    if response.status_code == 200:
        data = response.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return content, data["sha"]
    return None, None


def write_file(path: str, content: str, message: str) -> bool:
    """Create or update a file in the repo. Returns True on success."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    _, sha = read_file(path)  # get SHA if file already exists
    data = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        data["sha"] = sha
    response = requests.put(url, headers=_headers(), json=data)
    return response.status_code in (200, 201)


def dispatch_workflow(workflow_file: str) -> bool:
    """Trigger a workflow_dispatch event. Returns True on success."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{workflow_file}/dispatches"
    response = requests.post(url, headers=_headers(), json={"ref": GITHUB_BRANCH})
    return response.status_code == 204
