"""Repository and task intake from GitHub's REST API (research.md R6).

Only public repositories are accepted. The optional server-side ``GITHUB_TOKEN`` (read-only)
raises the 60 requests per hour unauthenticated limit. It is sent only to ``api.github.com``
and never enters a sandbox. Errors carry the codes used by the web API contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from fixproof.models import RepoRef

GITHUB_API = "https://api.github.com"
ISSUE_BODY_LIMIT = 8000
TREE_LIMIT = 2000

_REPO_URL = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<name>[A-Za-z0-9_.-]+?)(?:\.git)?"
    r"(?:/tree/(?P<ref>[^\s?#]+?))?/?$"
)
_ISSUE_URL = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<name>[A-Za-z0-9_.-]+)/issues/(?P<number>\d+)/?$"
)


class GitHubError(Exception):
    """A GitHub intake failure with a machine-readable ``code``.

    Codes: ``invalid_repo``, ``private_repo``, ``repo_too_large``, ``invalid_task``,
    ``rate_limited``, ``github_error``.

    Args:
        code: Machine-readable error code.
        message: Human-readable reason and how to proceed.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RepoLocation:
    """A parsed GitHub repository URL."""

    owner: str
    name: str
    ref: str | None = None

    @property
    def url(self) -> str:
        """Canonical repository URL without a ref."""
        return f"https://github.com/{self.owner}/{self.name}"


def parse_repo_url(url: str) -> RepoLocation:
    """Parse ``https://github.com/<owner>/<repo>`` with an optional ``/tree/<ref>``.

    Args:
        url: The repository URL entered by the user.

    Returns:
        The owner, name, and optional ref.

    Raises:
        GitHubError: With code ``invalid_repo`` for any other URL.
    """
    match = _REPO_URL.match(url.strip())
    if not match:
        raise GitHubError(
            "invalid_repo",
            f"Not a public GitHub repository URL: {url!r}. Use https://github.com/<owner>/<repo>.",
        )
    return RepoLocation(match["owner"], match["name"], match["ref"])


def parse_issue_url(url: str, repo: RepoLocation) -> int:
    """Return the issue number from an issue URL of the same repository.

    Args:
        url: ``https://github.com/<owner>/<repo>/issues/<n>``.
        repo: The repository the run works on.

    Returns:
        The issue number.

    Raises:
        GitHubError: With code ``invalid_task`` if the URL is malformed or names another repo.
    """
    match = _ISSUE_URL.match(url.strip())
    if not match:
        raise GitHubError("invalid_task", f"Not a GitHub issue URL: {url!r}.")
    same_repo = (match["owner"].lower(), match["name"].lower()) == (
        repo.owner.lower(),
        repo.name.lower(),
    )
    if not same_repo:
        raise GitHubError(
            "invalid_task",
            f"The issue belongs to {match['owner']}/{match['name']}, not {repo.owner}/{repo.name}.",
        )
    return int(match["number"])


class GitHubClient:
    """Minimal async client for the public GitHub REST endpoints FixProof needs.

    Args:
        token: Optional read-only token; sent only to ``api.github.com``.
        http: Pre-built ``httpx.AsyncClient`` (tests inject a mock transport).
        api_url: Base URL of the GitHub REST API.
        timeout_s: Request timeout in seconds.
    """

    def __init__(
        self,
        token: str | None = None,
        *,
        http: httpx.AsyncClient | None = None,
        api_url: str = GITHUB_API,
        timeout_s: float = 30.0,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._http = http or httpx.AsyncClient(timeout=timeout_s)
        self._headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "fixproof",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    async def get_repo(self, location: RepoLocation, *, max_kb: int | None = None) -> RepoRef:
        """Fetch repository metadata and enforce the public and size rules (FR-018).

        Args:
            location: The parsed repository URL.
            max_kb: Largest accepted repository size in KB, or ``None`` for no limit.

        Returns:
            The repository reference (ref defaults to the default branch).

        Raises:
            GitHubError: ``invalid_repo``, ``private_repo``, ``repo_too_large``, or a transport
                error code.
        """
        data = await self._get_json(
            f"/repos/{location.owner}/{location.name}", not_found="invalid_repo"
        )
        if data.get("private"):
            raise GitHubError(
                "private_repo",
                f"{location.owner}/{location.name} is private; only public repos are supported.",
            )
        size_kb = int(data.get("size") or 0)
        if max_kb is not None and size_kb > max_kb:
            raise GitHubError(
                "repo_too_large",
                f"{location.owner}/{location.name} is {size_kb / 1024:.0f} MB; "
                f"the limit is {max_kb / 1024:.0f} MB.",
            )
        default_branch = data.get("default_branch")
        return RepoRef(
            url=location.url,
            owner=location.owner,
            name=location.name,
            ref=location.ref or default_branch,
            size_kb=size_kb,
            private=False,
            default_branch=default_branch,
        )

    async def resolve_ref(self, location: RepoLocation, ref: str) -> str:
        """Return the commit SHA that ``ref`` (branch, tag, or SHA) points to."""
        data = await self._get_json(
            f"/repos/{location.owner}/{location.name}/commits/{ref}", not_found="invalid_repo"
        )
        return str(data["sha"])

    async def download_tarball(
        self, location: RepoLocation, sha: str, dest: Path, *, max_bytes: int
    ) -> Path:
        """Download the repository tarball at ``sha`` to ``dest``, enforcing a size cap.

        Args:
            location: The repository.
            sha: Commit to download.
            dest: Destination file path.
            max_bytes: Abort (and delete the partial file) beyond this many bytes.

        Returns:
            ``dest``.

        Raises:
            GitHubError: ``repo_too_large`` if the archive exceeds ``max_bytes``.
        """
        url = f"{self._api_url}/repos/{location.owner}/{location.name}/tarball/{sha}"
        received = 0
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            async with self._http.stream(
                "GET", url, headers=self._headers, follow_redirects=True
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    self._raise_for(response, not_found="invalid_repo")
                with dest.open("wb") as handle:
                    async for chunk in response.aiter_bytes():
                        received += len(chunk)
                        if received > max_bytes:
                            raise GitHubError(
                                "repo_too_large",
                                "The repository archive is larger than "
                                f"{max_bytes / 1_048_576:.0f} MB.",
                            )
                        handle.write(chunk)
        except GitHubError:
            dest.unlink(missing_ok=True)
            raise
        return dest

    async def get_issue(self, location: RepoLocation, number: int) -> tuple[str, str]:
        """Return the issue title and body (body truncated to 8,000 characters)."""
        data = await self._get_json(
            f"/repos/{location.owner}/{location.name}/issues/{number}", not_found="invalid_task"
        )
        return str(data.get("title") or ""), str(data.get("body") or "")[:ISSUE_BODY_LIMIT]

    async def get_tree(
        self, location: RepoLocation, sha: str, *, limit: int = TREE_LIMIT
    ) -> list[str]:
        """Return file paths in the repository at ``sha``, capped at ``limit`` entries."""
        data = await self._get_json(
            f"/repos/{location.owner}/{location.name}/git/trees/{sha}",
            params={"recursive": "1"},
            not_found="invalid_repo",
        )
        tree = data.get("tree") or []
        return [item["path"] for item in tree if item.get("type") == "blob"][:limit]

    async def _get_json(
        self, path: str, *, not_found: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        try:
            response = await self._http.get(
                f"{self._api_url}{path}", headers=self._headers, params=params
            )
        except httpx.HTTPError as exc:
            raise GitHubError("github_error", f"Could not reach GitHub: {exc}") from exc
        if response.status_code >= 400:
            self._raise_for(response, not_found=not_found)
        data = response.json()
        if not isinstance(data, dict):
            raise GitHubError("github_error", "Unexpected response from GitHub.")
        return data

    @staticmethod
    def _raise_for(response: httpx.Response, *, not_found: str) -> None:
        status = response.status_code
        if status == 404:
            raise GitHubError(
                not_found, "Not found on GitHub (it may not exist, or it may be private)."
            )
        if status in (403, 429) and (
            response.headers.get("x-ratelimit-remaining") == "0"
            or "rate limit" in response.text.lower()
        ):
            raise GitHubError(
                "rate_limited",
                "GitHub API rate limit reached. Set GITHUB_TOKEN (a read-only token) "
                "to raise the limit, or try again later.",
            )
        if status == 401:
            raise GitHubError(
                "github_error", "GitHub rejected the credentials; check GITHUB_TOKEN."
            )
        raise GitHubError("github_error", f"GitHub returned HTTP {status}.")
