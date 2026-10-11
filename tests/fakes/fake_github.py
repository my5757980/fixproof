"""In-memory fake of ``RepoSource`` (GitHub intake) for offline tests; never imported by src."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from fixproof.models import RepoRef
from fixproof.repo.github import TREE_LIMIT, GitHubError, RepoLocation
from tests.fakes.fake_executor import make_tarball

DEFAULT_SHA = "0123456789abcdef0123456789abcdef01234567"


class FakeGitHub:
    """Serves one repository (as a GitHub-style tarball) and one issue."""

    def __init__(
        self,
        files: Mapping[str, str | bytes],
        *,
        issue: tuple[str, str] = (
            "add() returns the wrong result",
            "Calling add(2, 3) returns -1 instead of 5.",
        ),
        private: bool = False,
        size_kb: int = 12,
        sha: str = DEFAULT_SHA,
        default_branch: str = "main",
    ) -> None:
        self.files = dict(files)
        self.issue = issue
        self.private = private
        self.size_kb = size_kb
        self.sha = sha
        self.default_branch = default_branch
        self.calls: list[str] = []
        self.closed = False

    async def get_repo(self, location: RepoLocation, *, max_kb: int | None = None) -> RepoRef:
        self.calls.append("get_repo")
        if self.private:
            raise GitHubError("private_repo", f"{location.owner}/{location.name} is private.")
        if max_kb is not None and self.size_kb > max_kb:
            raise GitHubError("repo_too_large", "The repository is too large.")
        return RepoRef(
            url=location.url,
            owner=location.owner,
            name=location.name,
            ref=location.ref or self.default_branch,
            size_kb=self.size_kb,
            default_branch=self.default_branch,
        )

    async def resolve_ref(self, location: RepoLocation, ref: str) -> str:
        self.calls.append(f"resolve_ref:{ref}")
        return self.sha

    async def download_tarball(
        self, location: RepoLocation, sha: str, dest: Path, *, max_bytes: int
    ) -> Path:
        self.calls.append("download_tarball")
        dest.parent.mkdir(parents=True, exist_ok=True)
        return make_tarball(dest, self.files, top=f"{location.owner}-{location.name}-{sha[:7]}")

    async def get_issue(self, location: RepoLocation, number: int) -> tuple[str, str]:
        self.calls.append(f"get_issue:{number}")
        return self.issue

    async def get_tree(
        self, location: RepoLocation, sha: str, *, limit: int = TREE_LIMIT
    ) -> list[str]:
        self.calls.append("get_tree")
        return sorted(self.files)[:limit]

    async def aclose(self) -> None:
        self.closed = True
