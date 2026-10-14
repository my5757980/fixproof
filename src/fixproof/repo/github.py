"""Repository and task intake from GitHub's REST API (research.md R6).

Only public repositories are accepted. The optional server-side ``GITHUB_TOKEN`` (read-only)
raises the 60 requests per hour unauthenticated limit. It is sent only to ``api.github.com``
and never enters a sandbox. Errors carry the codes used by the web API contract.
"""

from __future__ import annotations

import asyncio
import base64
import re
import tarfile
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from fixproof.models import FileStatus, Patch, RepoRef
from fixproof.repo.patches import git_apply, validate_patch

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


def _strip_top(name: str) -> str:
    """Drop the single top-level directory of a GitHub tarball member name."""
    return name.split("/", 1)[1] if "/" in name else ""


def tarball_paths(tarball: Path) -> list[str]:
    """Return the file paths in a GitHub tarball, relative to the repository root.

    The archive is only listed, never extracted on the host.
    """
    with tarfile.open(tarball, "r:*") as archive:
        return sorted(
            path
            for member in archive.getmembers()
            if member.isfile() and (path := _strip_top(member.name))
        )


def read_tarball_text(tarball: Path, path: str, *, max_bytes: int = 1_000_000) -> str:
    """Return one file of a GitHub tarball as text, read in memory (never extracted).

    Raises:
        FileNotFoundError: If the archive has no such file.
    """
    with tarfile.open(tarball, "r:*") as archive:
        for member in archive.getmembers():
            if member.isfile() and _strip_top(member.name) == path:
                handle = archive.extractfile(member)
                if handle is None:
                    break
                return handle.read(max_bytes).decode("utf-8", errors="replace")
    raise FileNotFoundError(path)


class RepoSource(Protocol):
    """Where the orchestrator gets repositories and issues (``GitHubClient``; faked in tests)."""

    async def get_repo(self, location: RepoLocation, *, max_kb: int | None = None) -> RepoRef:
        """Fetch repository metadata, enforcing the public and size rules."""
        ...

    async def resolve_ref(self, location: RepoLocation, ref: str) -> str:
        """Return the commit SHA that ``ref`` points to."""
        ...

    async def download_tarball(
        self, location: RepoLocation, sha: str, dest: Path, *, max_bytes: int
    ) -> Path:
        """Download the repository tarball at ``sha`` to ``dest``."""
        ...

    async def get_issue(self, location: RepoLocation, number: int) -> tuple[str, str]:
        """Return the issue title and body."""
        ...

    async def get_tree(
        self, location: RepoLocation, sha: str, *, limit: int = TREE_LIMIT
    ) -> list[str]:
        """Return file paths in the repository at ``sha``."""
        ...

    async def aclose(self) -> None:
        """Release network resources."""
        ...


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

    # -- pull requests (CLI only, with the user's own token; FR-016) ------------------------

    async def authenticated_login(self) -> str:
        """Return the login of the token's owner."""
        data = await self._request("GET", "/user", not_found="github_error")
        return str(data["login"])

    async def create_fork(
        self,
        location: RepoLocation,
        *,
        attempts: int = 10,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> RepoLocation:
        """Fork ``location`` into the token owner's account and wait until it is ready."""
        data = await self._request(
            "POST", f"/repos/{location.owner}/{location.name}/forks", not_found="invalid_repo"
        )
        fork = RepoLocation(str(data["owner"]["login"]), str(data["name"]))
        for attempt in range(attempts):
            try:
                await self._request(
                    "GET", f"/repos/{fork.owner}/{fork.name}", not_found="not_ready"
                )
                return fork
            except GitHubError as exc:
                if exc.code != "not_ready":
                    raise
            await sleep(min(2.0 * (attempt + 1), 10.0))
        raise GitHubError(
            "github_error", f"The fork {fork.owner}/{fork.name} did not become ready."
        )

    async def create_branch(self, location: RepoLocation, branch: str, sha: str) -> None:
        """Create ``branch`` at commit ``sha``."""
        await self._request(
            "POST",
            f"/repos/{location.owner}/{location.name}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": sha},
            not_found="invalid_repo",
        )

    async def get_file(
        self, location: RepoLocation, path: str, ref: str
    ) -> tuple[bytes, str] | None:
        """Return a file's content and blob SHA at ``ref``, or ``None`` if it does not exist."""
        try:
            data = await self._request(
                "GET",
                f"/repos/{location.owner}/{location.name}/contents/{quote(path)}",
                params={"ref": ref},
                not_found="missing_file",
            )
        except GitHubError as exc:
            if exc.code == "missing_file":
                return None
            raise
        if data.get("encoding") != "base64":
            raise GitHubError("github_error", f"{path} is too large for the contents API.")
        return base64.b64decode(str(data.get("content") or "")), str(data["sha"])

    async def put_file(
        self,
        location: RepoLocation,
        path: str,
        content: bytes,
        *,
        branch: str,
        message: str,
        sha: str | None = None,
    ) -> None:
        """Create or update a file on ``branch`` (one commit)."""
        body: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content).decode(),
            "branch": branch,
        }
        if sha is not None:
            body["sha"] = sha
        await self._request(
            "PUT",
            f"/repos/{location.owner}/{location.name}/contents/{quote(path)}",
            json=body,
            not_found="invalid_repo",
        )

    async def delete_file(
        self, location: RepoLocation, path: str, *, branch: str, message: str, sha: str
    ) -> None:
        """Delete a file on ``branch`` (one commit)."""
        await self._request(
            "DELETE",
            f"/repos/{location.owner}/{location.name}/contents/{quote(path)}",
            json={"message": message, "sha": sha, "branch": branch},
            not_found="invalid_repo",
        )

    async def create_pull_request(
        self, location: RepoLocation, *, title: str, head: str, base: str, body: str, draft: bool
    ) -> str:
        """Open a pull request on ``location`` and return its URL."""
        data = await self._request(
            "POST",
            f"/repos/{location.owner}/{location.name}/pulls",
            json={"title": title, "head": head, "base": base, "body": body, "draft": draft},
            not_found="invalid_repo",
        )
        return str(data["html_url"])

    async def _get_json(
        self, path: str, *, not_found: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        return await self._request("GET", path, not_found=not_found, params=params)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        not_found: str,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._http.request(
                method, f"{self._api_url}{path}", headers=self._headers, params=params, json=json
            )
        except httpx.HTTPError as exc:
            raise GitHubError("github_error", f"Could not reach GitHub: {exc}") from exc
        if response.status_code >= 400:
            self._raise_for(response, not_found=not_found)
        data = response.json() if response.content else {}
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
        detail = ""
        try:
            message = response.json().get("message")
        except (ValueError, AttributeError):
            message = None
        if isinstance(message, str) and message:
            detail = f": {message[:300]}"
        raise GitHubError("github_error", f"GitHub returned HTTP {status}{detail}.")


async def open_fix_pull_request(
    client: GitHubClient,
    *,
    location: RepoLocation,
    base_sha: str,
    run_id: str,
    patch: Patch,
    title: str,
    body: str,
    draft: bool = True,
) -> str:
    """Open a pull request with a run's patch, from the token owner's fork (FR-016).

    Steps: fork (unless the token owner owns the repository), create ``fixproof/<run_id>`` at
    the run's commit, commit each changed file through the contents API, and open the pull
    request against the default branch. The new file contents come from applying the patch with
    ``git apply`` to the original files in a temporary folder; no repository code runs.

    Returns:
        The pull request's URL.

    Raises:
        GitHubError: For any GitHub failure, or a patch that does not apply.
    """
    login = await client.authenticated_login()
    originals: dict[str, tuple[bytes, str]] = {}
    for change in patch.files:
        if change.status is not FileStatus.ADDED:
            found = await client.get_file(location, change.path, base_sha)
            if found is None:
                raise GitHubError("github_error", f"{change.path} is not in {base_sha[:12]}.")
            originals[change.path] = found
    # Everything that can fail without writing to GitHub happens before the fork.
    updated = _apply_to_originals(patch, {path: data for path, (data, _) in originals.items()})
    repo = await client.get_repo(location)
    own_repository = login.lower() == location.owner.lower()
    head = location if own_repository else await client.create_fork(location)
    branch = f"fixproof/{run_id}"
    await client.create_branch(head, branch, base_sha)
    message = f"{title} ({run_id})"
    for change in patch.files:
        sha = originals[change.path][1] if change.path in originals else None
        if change.status is FileStatus.DELETED:
            if sha is None:
                raise GitHubError("github_error", f"Cannot delete {change.path}: unknown file.")
            await client.delete_file(head, change.path, branch=branch, message=message, sha=sha)
        else:
            await client.put_file(
                head, change.path, updated[change.path], branch=branch, message=message, sha=sha
            )
    return await client.create_pull_request(
        location,
        title=title,
        head=f"{head.owner}:{branch}",
        base=repo.default_branch or "main",
        body=body,
        draft=draft,
    )


def _apply_to_originals(patch: Patch, originals: dict[str, bytes]) -> dict[str, bytes]:
    """Apply ``patch`` to the original files in a temporary folder and read the results."""
    with tempfile.TemporaryDirectory(prefix="fixproof-pr-") as tmp:
        root = Path(tmp)
        for path, content in originals.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        problems = validate_patch(patch.unified_diff, root)
        if problems:
            raise GitHubError("github_error", "Unsafe patch: " + "; ".join(problems))
        patch_file = root / ".fixproof.patch"
        diff = patch.unified_diff
        patch_file.write_text(
            diff if diff.endswith("\n") else diff + "\n", encoding="utf-8", newline="\n"
        )
        ok, message = git_apply(patch_file, root, check=False, keep_line_endings=True)
        if not ok:
            raise GitHubError(
                "github_error", f"The patch does not apply to the original files: {message}"
            )
        return {
            change.path: (root / change.path).read_bytes()
            for change in patch.files
            if change.status is not FileStatus.DELETED
        }
