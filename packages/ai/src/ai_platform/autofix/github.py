"""The few GitHub REST calls auto-fix needs: read a branch, list and read files, and open a pull
request from a new branch (one commit, built with the Git Data API so no checkout is needed).

The token is a fine-grained personal access token limited to the linked repository with
"Contents: read and write" and "Pull requests: read and write" (docs/autofix.md).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from ai_platform.http import HttpError, HttpResponse, HttpTransport, UrllibTransport, send_json

GITHUB_API = "https://api.github.com"


@dataclass(frozen=True, slots=True)
class RepoFile:
    path: str
    size: int
    mode: str = "100644"


@dataclass(frozen=True, slots=True)
class PullRequest:
    number: int
    url: str


class GitHubRepository:
    def __init__(
        self,
        repo: str,
        token: str,
        *,
        transport: HttpTransport | None = None,
        api_url: str = GITHUB_API,
    ) -> None:
        self.repo = repo
        self._token = token
        self._transport = transport or UrllibTransport()
        self._api = f"{api_url.rstrip('/')}/repos/{repo}"

    # --- reads ------------------------------------------------------------------------------

    def default_branch(self) -> str:
        return str(self._get("")["default_branch"])

    def branch_sha(self, branch: str) -> str:
        data = self._get(f"/git/ref/heads/{quote(branch, safe='/')}")
        return str(data["object"]["sha"])

    def list_files(self, commit_sha: str) -> tuple[list[RepoFile], bool]:
        """Every file (blob) at ``commit_sha`` and whether GitHub truncated the listing."""
        commit = self._get(f"/git/commits/{commit_sha}")
        tree = self._get(f"/git/trees/{commit['tree']['sha']}?recursive=1")
        files = [
            RepoFile(path=e["path"], size=int(e.get("size") or 0), mode=e.get("mode", "100644"))
            for e in tree.get("tree", [])
            if e.get("type") == "blob"
        ]
        return files, bool(tree.get("truncated"))

    def read_file(self, path: str, ref: str) -> str | None:
        """UTF-8 text of ``path`` at ``ref``; ``None`` when missing or not text."""
        response = self._call("GET", f"/contents/{quote(path)}?ref={quote(ref, safe='')}")
        if response.status == 404:
            return None
        data = _ok(response, f"read {path}")
        if not isinstance(data, dict) or data.get("encoding") != "base64":
            return None
        try:
            return base64.b64decode(data.get("content", "")).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None

    # --- writes -----------------------------------------------------------------------------

    def open_pull_request(
        self,
        *,
        base_branch: str,
        base_sha: str,
        branch: str,
        changes: dict[str, str],
        modes: dict[str, str],
        commit_message: str,
        title: str,
        body: str,
    ) -> PullRequest:
        """Commit ``changes`` (path -> new full text) on top of ``base_sha`` as ``branch`` and
        open a pull request into ``base_branch``. Never touches ``base_branch`` itself."""
        commit = self._get(f"/git/commits/{base_sha}")
        tree = self._post(
            "/git/trees",
            {
                "base_tree": commit["tree"]["sha"],
                "tree": [
                    {
                        "path": path,
                        "mode": modes.get(path, "100644"),
                        "type": "blob",
                        "content": content,
                    }
                    for path, content in sorted(changes.items())
                ],
            },
            "create tree",
        )
        new_commit = self._post(
            "/git/commits",
            {"message": commit_message, "tree": tree["sha"], "parents": [base_sha]},
            "create commit",
        )
        self._post(
            "/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": new_commit["sha"]},
            "create branch",
        )
        pr = self._post(
            "/pulls",
            {
                "title": title,
                "head": branch,
                "base": base_branch,
                "body": body,
                "maintainer_can_modify": True,
            },
            "open pull request",
        )
        return PullRequest(number=int(pr["number"]), url=str(pr["html_url"]))

    # --- plumbing ---------------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "builderwars-autofix",
        }

    def _call(self, method: str, path: str, payload: Any = None) -> HttpResponse:
        return send_json(
            self._transport, method, self._api + path, headers=self._headers(), payload=payload
        )

    def _get(self, path: str) -> Any:
        return _ok(self._call("GET", path), f"GET {path or '/'}")

    def _post(self, path: str, payload: Any, what: str) -> Any:
        return _ok(self._call("POST", path, payload), what)


def _ok(response: HttpResponse, what: str) -> Any:
    if response.status < 400:
        return response.json()
    message = ""
    try:
        data = response.json()
        if isinstance(data, dict):
            message = str(data.get("message", ""))
    except HttpError:
        pass
    hint = {
        401: " (token invalid or expired)",
        403: " (token lacks permission for this repository)",
        404: " (repository not found, or the token cannot see it)",
    }.get(response.status, "")
    raise HttpError(
        f"GitHub {what} failed: HTTP {response.status}{hint} {message}".strip(),
        status=response.status,
    )
