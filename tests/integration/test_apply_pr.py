"""Taking the fix home (User Story 4): ``fixproof apply`` and ``fixproof pr`` with approval."""

from __future__ import annotations

import base64
import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from fixproof import cli
from fixproof.agent.report import build_report, render_markdown, write_report_files
from fixproof.cli import Factories, app
from fixproof.events import EventBus, EventType
from fixproof.models import (
    Citation,
    Evidence,
    FileChange,
    FileStatus,
    OutcomeLabel,
    Patch,
    StopReason,
    TestCaseResult,
    TestOutcome,
    TestRun,
)
from fixproof.repo.github import GitHubClient
from fixproof.trace import TraceWriter
from tests.fakes.calc_repo import (
    CALC_FILES,
    EXISTING_ID,
    REPO_URL,
    REPRO_ID,
    REPRO_PATH,
    REPRO_TEST,
)
from tests.fakes.settings import make_settings

RUN_ID = "run-20261011-120000-abcdef"
SHA = "0123456789abcdef0123456789abcdef01234567"
FIXED_CORE = CALC_FILES["calc/core.py"].replace("a - b", "a + b")
runner = CliRunner()


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A fresh local checkout of the calc repository at the run's revision."""
    repo = tmp_path / "checkout"
    for path, text in CALC_FILES.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text, encoding="utf-8", newline="\n")
    git(repo, "init", "-q")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "add", "-A")
    git(repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "base")
    return repo


def real_patch(repo: Path) -> str:
    """The fix as git produces it in the sandbox: core.py changed, a reproduction test added."""
    (repo / "calc/core.py").write_text(FIXED_CORE, encoding="utf-8", newline="\n")
    (repo / REPRO_PATH).write_text(REPRO_TEST, encoding="utf-8", newline="\n")
    git(repo, "add", "-A")
    diff = git(repo, "diff", "--cached", "--no-color")
    git(repo, "reset", "-q", "--hard")
    git(repo, "clean", "-qfd")
    return diff


def run_of(passed: list[str], run_id: str) -> TestRun:
    results = tuple(TestCaseResult(node_id=n, outcome=TestOutcome.PASSED) for n in passed)
    return TestRun(id=run_id, snapshot_id="img", results=results, exit_code=0)


def make_run_dir(
    tmp_path: Path,
    diff: str,
    *,
    label: OutcomeLabel = OutcomeLabel.VERIFIED,
    executor: str | None = None,
) -> Path:
    run_dir = tmp_path / "runs" / RUN_ID
    patch = Patch(
        unified_diff=diff,
        files=(
            FileChange(path="calc/core.py", status=FileStatus.MODIFIED, added=1, removed=1),
            FileChange(path=REPRO_PATH, status=FileStatus.ADDED, added=5, is_test_file=True),
        ),
    )
    evidence = Evidence(
        baseline=run_of([EXISTING_ID], "tr-1"),
        repro_test_id=REPRO_ID,
        repro_created=True,
        repro_after=[run_of([REPRO_ID], f"tr-{i}") for i in (2, 3, 4)],
        regression=run_of([EXISTING_ID, REPRO_ID], "tr-5"),
    )
    report = build_report(
        run_id=RUN_ID,
        label=label,
        stop_reason=StopReason.COMPLETED,
        summary="add() subtracted its arguments; it now adds them.",
        root_cause_md="`calc/core.py:3-3` returned `a - b` instead of `a + b`.",
        citations=[Citation(path="calc/core.py", start_line=1, end_line=3)],
        patch=patch,
        evidence=evidence,
    )
    write_report_files(run_dir, report, render_markdown(report))
    bus = EventBus(RUN_ID)
    writer = TraceWriter.for_run(tmp_path / "runs", RUN_ID).attach(bus)
    started: dict[str, Any] = {"repo_url": REPO_URL, "ref": None, "task": {}}
    if executor is not None:
        started["executor"] = executor
    bus.publish(EventType.RUN_STARTED, started)
    bus.publish(EventType.REPO_FETCHED, {"resolved_sha": SHA, "size_kb": 1})
    writer.close()
    return run_dir


def invoke(*args: str, answer: str | None = None) -> Any:
    return runner.invoke(app, list(args), input=answer)


def status(repo: Path) -> str:
    return git(repo, "status", "--porcelain")


# -- apply ---------------------------------------------------------------------------------


def test_apply_shows_the_change_and_does_nothing_when_declined(
    tmp_path: Path, checkout: Path
) -> None:
    run_dir = make_run_dir(tmp_path, real_patch(checkout))
    result = invoke("apply", str(run_dir), "--to", str(checkout), answer="n\n")
    assert result.exit_code == 3, result.output
    assert "+    return a + b" in result.stdout  # the full diff
    assert "Verified" in result.stdout and REPRO_ID in result.stdout  # the evidence
    assert "Apply this patch? [y/N]" in result.stdout
    assert status(checkout) == ""


def test_apply_applies_after_yes(tmp_path: Path, checkout: Path) -> None:
    run_dir = make_run_dir(tmp_path, real_patch(checkout))
    result = invoke("apply", str(run_dir), "--to", str(checkout), answer="yes\n")
    assert result.exit_code == 0, result.output
    assert (checkout / "calc/core.py").read_text(encoding="utf-8") == FIXED_CORE
    assert (checkout / REPRO_PATH).read_text(encoding="utf-8") == REPRO_TEST


@pytest.mark.parametrize("answer", ["\n", "maybe\n", "Y es\n", ""])
def test_anything_but_yes_declines(tmp_path: Path, checkout: Path, answer: str) -> None:
    run_dir = make_run_dir(tmp_path, real_patch(checkout))
    result = invoke("apply", str(run_dir), "--to", str(checkout), answer=answer)
    assert result.exit_code == 3
    assert status(checkout) == ""


def test_a_patch_that_does_not_apply_exits_4(tmp_path: Path, checkout: Path) -> None:
    run_dir = make_run_dir(tmp_path, real_patch(checkout))
    (checkout / "calc/core.py").write_text("def add(a, b):\n    return 0\n", encoding="utf-8")
    result = invoke("apply", str(run_dir), "--to", str(checkout), answer="y\n")
    assert result.exit_code == 4, result.output
    assert (checkout / "calc/core.py").read_text(
        encoding="utf-8"
    ) == "def add(a, b):\n    return 0\n"


def edit_of(path: str) -> str:
    """A one-line edit of ``path`` as git writes it."""
    header = f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
    return header + "@@ -1 +1 @@\n-x\n+y\n"


UNSAFE = {
    "parent": edit_of("../outside.py"),
    "absolute": "--- /etc/hosts\n+++ /etc/hosts\n@@ -1 +1 @@\n-x\n+y\n",
    "git-dir": edit_of(".git/config"),
}


@pytest.mark.parametrize("kind", sorted(UNSAFE))
def test_unsafe_patch_paths_are_rejected_before_git_apply(
    tmp_path: Path, checkout: Path, kind: str
) -> None:
    run_dir = make_run_dir(tmp_path, UNSAFE[kind])
    result = invoke("apply", str(run_dir), "--to", str(checkout), answer="y\n")
    assert result.exit_code == 4, result.output
    assert "Apply this patch?" not in result.stdout
    assert status(checkout) == ""


def test_a_path_through_a_symlink_is_rejected(tmp_path: Path, checkout: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, checkout / "linked", target_is_directory=True)
    except OSError:
        pytest.skip("creating symbolic links is not permitted on this machine")
    diff = (
        "diff --git a/linked/x.py b/linked/x.py\nnew file mode 100644\n--- /dev/null\n"
        "+++ b/linked/x.py\n@@ -0,0 +1 @@\n+x = 1\n"
    )
    run_dir = make_run_dir(tmp_path, diff)
    result = invoke("apply", str(run_dir), "--to", str(checkout), answer="y\n")
    assert result.exit_code == 4, result.output
    assert not (outside / "x.py").exists()


def test_not_verified_runs_need_force_and_still_ask(tmp_path: Path, checkout: Path) -> None:
    run_dir = make_run_dir(tmp_path, real_patch(checkout), label=OutcomeLabel.NOT_VERIFIED)
    refused = invoke("apply", str(run_dir), "--to", str(checkout), answer="y\n")
    assert refused.exit_code == 2 and "--force-unverified" in refused.stderr
    forced = invoke(
        "apply", str(run_dir), "--to", str(checkout), "--force-unverified", answer="n\n"
    )
    assert forced.exit_code == 3
    assert "WARNING" in forced.stdout and "Apply this patch? [y/N]" in forced.stdout
    assert status(checkout) == ""


def test_apply_needs_a_run_with_a_patch(tmp_path: Path) -> None:
    result = invoke("apply", str(tmp_path / "missing-run"), "--to", str(tmp_path))
    assert result.exit_code == 2


# -- pr ------------------------------------------------------------------------------------


class FakeGitHubApi:
    """Records requests and answers like the GitHub REST API for the pull-request flow."""

    def __init__(
        self,
        core_text: str = CALC_FILES["calc/core.py"],
        overrides: dict[tuple[str, str], tuple[int, Any]] | None = None,
    ) -> None:
        self.requests: list[tuple[str, str, dict[str, Any] | None]] = []
        self.core_text = core_text
        self.overrides = overrides or {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        self.requests.append((request.method, path, body))
        routes: dict[tuple[str, str], tuple[int, Any]] = {
            ("GET", "/user"): (200, {"login": "alice"}),
            ("POST", "/repos/acme/calc/forks"): (
                202,
                {"full_name": "alice/calc", "name": "calc", "owner": {"login": "alice"}},
            ),
            ("GET", "/repos/alice/calc"): (200, {"full_name": "alice/calc"}),
            ("GET", "/repos/acme/calc"): (
                200,
                {"private": False, "size": 4, "default_branch": "main"},
            ),
            ("POST", "/repos/alice/calc/git/refs"): (201, {"ref": "refs/heads/x"}),
            ("GET", "/repos/acme/calc/contents/calc/core.py"): (
                200,
                {
                    "encoding": "base64",
                    "sha": "blob-core",
                    "content": base64.b64encode(self.core_text.encode()).decode(),
                },
            ),
            ("PUT", "/repos/alice/calc/contents/calc/core.py"): (201, {"commit": {}}),
            ("PUT", f"/repos/alice/calc/contents/{REPRO_PATH}"): (201, {"commit": {}}),
            ("POST", "/repos/acme/calc/pulls"): (
                201,
                {"html_url": "https://github.com/acme/calc/pull/42"},
            ),
        }
        routes.update(self.overrides)
        code, payload = routes.get((request.method, path), (404, {"message": "Not Found"}))
        return httpx.Response(code, json=payload)


def use_github(monkeypatch: pytest.MonkeyPatch, api: FakeGitHubApi, token: str | None) -> None:
    settings = make_settings(github_token=token)

    def client(settings: Any) -> GitHubClient:
        return GitHubClient(token=token, http=httpx.AsyncClient(transport=httpx.MockTransport(api)))

    monkeypatch.setattr(cli, "factories", Factories(settings=lambda: settings, github=client))


def test_pr_opens_a_draft_pull_request_from_a_fork(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, checkout: Path
) -> None:
    api = FakeGitHubApi()
    use_github(monkeypatch, api, "ghp_user_token_123456")
    run_dir = make_run_dir(tmp_path, real_patch(checkout))
    result = invoke("pr", str(run_dir), "--title", "Fix add()", answer="y\n")
    assert result.exit_code == 0, result.output
    assert "https://github.com/acme/calc/pull/42" in result.stdout

    calls = {(method, path): body for method, path, body in api.requests}
    assert calls[("POST", "/repos/alice/calc/git/refs")] == {
        "ref": f"refs/heads/fixproof/{RUN_ID}",
        "sha": SHA,
    }
    core = calls[("PUT", "/repos/alice/calc/contents/calc/core.py")]
    assert (
        core is not None and core["branch"] == f"fixproof/{RUN_ID}" and core["sha"] == "blob-core"
    )
    assert base64.b64decode(core["content"]).decode() == FIXED_CORE
    added = calls[("PUT", f"/repos/alice/calc/contents/{REPRO_PATH}")]
    assert added is not None and "sha" not in added
    assert base64.b64decode(added["content"]).decode() == REPRO_TEST
    pull = calls[("POST", "/repos/acme/calc/pulls")]
    assert pull is not None
    assert pull["draft"] is True and pull["base"] == "main"
    assert pull["head"] == f"alice:fixproof/{RUN_ID}" and pull["title"] == "Fix add()"
    assert "returned `a - b`" in pull["body"]  # root cause
    assert "Verified" in pull["body"] and REPRO_ID in pull["body"]  # evidence
    assert "AI agent" in pull["body"]
    assert "Nebius Token Factory sandbox" in pull["body"]


def test_pr_body_says_when_the_tests_ran_in_local_docker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, checkout: Path
) -> None:
    api = FakeGitHubApi()
    use_github(monkeypatch, api, "ghp_user_token_123456")
    run_dir = make_run_dir(tmp_path, real_patch(checkout), executor="docker")
    result = invoke("pr", str(run_dir), answer="y\n")
    assert result.exit_code == 0, result.output
    pull = {(m, p): b for m, p, b in api.requests}[("POST", "/repos/acme/calc/pulls")]
    assert pull is not None
    assert "local Docker container" in pull["body"]
    assert "Token Factory sandbox" not in pull["body"]


def test_a_patch_that_no_longer_applies_creates_no_fork(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, checkout: Path
) -> None:
    api = FakeGitHubApi(core_text="def add(a, b):\n    return b + a\n")
    use_github(monkeypatch, api, "ghp_user_token_123456")
    run_dir = make_run_dir(tmp_path, real_patch(checkout))
    result = invoke("pr", str(run_dir), answer="y\n")
    assert result.exit_code == 5
    assert "does not apply" in result.stderr
    assert all(method == "GET" for method, _, _ in api.requests)  # nothing written to GitHub


def test_github_explains_why_it_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, checkout: Path
) -> None:
    refusal = (422, {"message": "A pull request already exists for alice:fixproof"})
    api = FakeGitHubApi(overrides={("POST", "/repos/acme/calc/pulls"): refusal})
    use_github(monkeypatch, api, "ghp_user_token_123456")
    run_dir = make_run_dir(tmp_path, real_patch(checkout))
    result = invoke("pr", str(run_dir), answer="y\n")
    assert result.exit_code == 5
    assert "HTTP 422" in result.stderr and "already exists" in result.stderr


def test_declining_a_pull_request_makes_no_http_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, checkout: Path
) -> None:
    api = FakeGitHubApi()
    use_github(monkeypatch, api, "ghp_user_token_123456")
    run_dir = make_run_dir(tmp_path, real_patch(checkout))
    result = invoke("pr", str(run_dir), answer="n\n")
    assert result.exit_code == 3
    assert api.requests == []


def test_pr_needs_the_users_own_github_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, checkout: Path
) -> None:
    api = FakeGitHubApi()
    use_github(monkeypatch, api, None)
    run_dir = make_run_dir(tmp_path, real_patch(checkout))
    result = invoke("pr", str(run_dir), answer="y\n")
    assert result.exit_code == 2 and "GITHUB_TOKEN" in result.stderr
    assert api.requests == []


def test_github_errors_exit_5(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, checkout: Path
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    settings = make_settings(github_token="ghp_wrong_token_123456")
    make_client: Callable[[Any], GitHubClient] = lambda s: GitHubClient(  # noqa: E731
        token="ghp_wrong_token_123456",
        http=httpx.AsyncClient(transport=httpx.MockTransport(refuse)),
    )
    monkeypatch.setattr(cli, "factories", Factories(settings=lambda: settings, github=make_client))
    run_dir = make_run_dir(tmp_path, real_patch(checkout))
    result = invoke("pr", str(run_dir), answer="y\n")
    assert result.exit_code == 5
    assert "GITHUB_TOKEN" in result.stderr
