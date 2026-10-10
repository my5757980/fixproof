from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from fixproof.repo.github import GitHubClient, GitHubError, parse_issue_url, parse_repo_url

API = "https://api.github.com"


def client(
    handler: Callable[[httpx.Request], httpx.Response], token: str | None = None
) -> GitHubClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GitHubClient(token, http=http)


def repo_json(private: bool = False, size_kb: int = 1200) -> dict[str, object]:
    return {
        "full_name": "psf/requests",
        "private": private,
        "size": size_kb,
        "default_branch": "main",
    }


@pytest.mark.parametrize(
    ("url", "owner", "name", "ref"),
    [
        ("https://github.com/psf/requests", "psf", "requests", None),
        ("https://github.com/psf/requests/", "psf", "requests", None),
        ("https://github.com/psf/requests.git", "psf", "requests", None),
        ("https://github.com/psf/requests/tree/v2.31.0", "psf", "requests", "v2.31.0"),
        ("https://github.com/pallets/click/tree/feature/x-y", "pallets", "click", "feature/x-y"),
    ],
)
def test_parse_repo_url(url: str, owner: str, name: str, ref: str | None) -> None:
    loc = parse_repo_url(url)
    assert (loc.owner, loc.name, loc.ref) == (owner, name, ref)
    assert loc.url == f"https://github.com/{owner}/{name}"


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/a/b",
        "http://github.com/a/b",
        "https://github.com/a",
        "github.com/a/b",
        "https://github.com/a/b/issues/1",
    ],
)
def test_non_github_or_malformed_urls_are_invalid_repo(url: str) -> None:
    with pytest.raises(GitHubError) as info:
        parse_repo_url(url)
    assert info.value.code == "invalid_repo"


def test_parse_issue_url_must_match_repo() -> None:
    repo = parse_repo_url("https://github.com/psf/requests")
    assert parse_issue_url("https://github.com/psf/requests/issues/6234", repo) == 6234
    assert parse_issue_url("https://github.com/PSF/Requests/issues/7/", repo) == 7
    with pytest.raises(GitHubError) as info:
        parse_issue_url("https://github.com/other/repo/issues/1", repo)
    assert info.value.code == "invalid_task"


async def test_get_repo_public_ok_and_auth_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=repo_json())

    ref = await client(handler, token="ghp_readonly123").get_repo(
        parse_repo_url("https://github.com/psf/requests"), max_kb=50 * 1024
    )
    assert (ref.owner, ref.name, ref.size_kb, ref.default_branch, ref.private) == (
        "psf",
        "requests",
        1200,
        "main",
        False,
    )
    assert seen[0].headers["Authorization"] == "Bearer ghp_readonly123"


async def test_private_repo_rejected() -> None:
    gh = client(lambda r: httpx.Response(200, json=repo_json(private=True)))
    with pytest.raises(GitHubError) as info:
        await gh.get_repo(parse_repo_url("https://github.com/psf/requests"))
    assert info.value.code == "private_repo"


async def test_missing_repo_is_invalid_repo() -> None:
    gh = client(lambda r: httpx.Response(404, json={"message": "Not Found"}))
    with pytest.raises(GitHubError) as info:
        await gh.get_repo(parse_repo_url("https://github.com/psf/nope"))
    assert info.value.code == "invalid_repo"


async def test_oversized_repo_rejected() -> None:
    gh = client(lambda r: httpx.Response(200, json=repo_json(size_kb=60 * 1024)))
    with pytest.raises(GitHubError) as info:
        await gh.get_repo(parse_repo_url("https://github.com/psf/requests"), max_kb=50 * 1024)
    assert info.value.code == "repo_too_large"


async def test_resolve_ref() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/psf/requests/commits/main"
        return httpx.Response(200, json={"sha": "abc123def456"})

    sha = await client(handler).resolve_ref(
        parse_repo_url("https://github.com/psf/requests"), "main"
    )
    assert sha == "abc123def456"


async def test_tarball_redirect_followed_and_size_capped(tmp_path: Path) -> None:
    payload = b"x" * 5000

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(
                302,
                headers={"Location": "https://codeload.github.com/psf/requests/legacy.tar.gz/abc"},
            )
        assert "Authorization" not in request.headers  # token never leaves api.github.com
        return httpx.Response(200, content=payload)

    loc = parse_repo_url("https://github.com/psf/requests")
    dest = await client(handler, token="ghp_readonly123").download_tarball(
        loc, "abc", tmp_path / "repo.tgz", max_bytes=10_000
    )
    assert dest.read_bytes() == payload

    with pytest.raises(GitHubError) as info:
        await client(handler).download_tarball(loc, "abc", tmp_path / "big.tgz", max_bytes=1000)
    assert info.value.code == "repo_too_large"
    assert not (tmp_path / "big.tgz").exists()


async def test_get_issue_truncates_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/psf/requests/issues/42"
        return httpx.Response(200, json={"title": "Crash on empty header", "body": "b" * 9000})

    title, body = await client(handler).get_issue(
        parse_repo_url("https://github.com/psf/requests"), 42
    )
    assert title == "Crash on empty header"
    assert len(body) == 8000


async def test_missing_issue_is_invalid_task() -> None:
    gh = client(lambda r: httpx.Response(404, json={"message": "Not Found"}))
    with pytest.raises(GitHubError) as info:
        await gh.get_issue(parse_repo_url("https://github.com/psf/requests"), 999)
    assert info.value.code == "invalid_task"


async def test_rate_limit_message_mentions_github_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, headers={"x-ratelimit-remaining": "0"}, json={"message": "API rate limit exceeded"}
        )

    with pytest.raises(GitHubError) as info:
        await client(handler).get_repo(parse_repo_url("https://github.com/psf/requests"))
    assert info.value.code == "rate_limited"
    assert "GITHUB_TOKEN" in str(info.value)


async def test_get_tree_is_capped() -> None:
    entries = [{"path": f"pkg/m{i}.py", "type": "blob"} for i in range(2500)] + [
        {"path": "pkg", "type": "tree"}
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["recursive"] == "1"
        return httpx.Response(200, json={"tree": entries, "truncated": False})

    paths = await client(handler).get_tree(parse_repo_url("https://github.com/psf/requests"), "abc")
    assert len(paths) == 2000
    assert "pkg" not in paths
