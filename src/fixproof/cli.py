"""Command-line interface (contracts/cli.md): fix, replay, doctor, serve, apply, and pr.

``fix`` prints the plan before any edit and then one line per event. Ctrl+C stops the run
within 10 seconds and still writes the partial report (exit code 30). ``apply`` and ``pr`` always
show the full diff and the evidence and change nothing unless the user answers ``y`` or ``yes``.
"""

import asyncio
import json
import signal
import tempfile
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from types import FrameType
from typing import Annotated, Any, NoReturn

import typer
from pydantic import ValidationError
from rich.console import Console

from fixproof import __version__
from fixproof.agent.orchestrator import Orchestrator, RunRequest, new_event_bus
from fixproof.agent.report import evidence_lines, pull_request_body
from fixproof.config import ConfigError, Settings, load_settings
from fixproof.events import EventType, TraceEvent
from fixproof.llm.client import ModelClient
from fixproof.models import Budget, OutcomeLabel, Report, Run, RunMode, StopReason, Task, TaskKind
from fixproof.repo.github import (
    GitHubClient,
    GitHubError,
    RepoSource,
    open_fix_pull_request,
    parse_issue_url,
    parse_repo_url,
)
from fixproof.repo.patches import git_apply, validate_patch
from fixproof.sandbox.executor import Executor
from fixproof.sandbox.factory import assert_demo_safe, make_executor
from fixproof.trace import read_trace
from fixproof.trace import replay as replay_trace
from fixproof.wiring import github_client, github_source, token_factory_client

EXIT_VERIFIED = 0
EXIT_INTERNAL_ERROR = 1
EXIT_INVALID_INPUT = 2
EXIT_DECLINED = 3
EXIT_PATCH_FAILED = 4
EXIT_GITHUB_ERROR = 5
EXIT_DOCTOR_PROBLEMS = 6
EXIT_NEEDS_REVIEW = 10
EXIT_NOT_VERIFIED = 20
EXIT_STOPPED = 30
EXIT_SETUP_FAILED = 40

EventCallback = Callable[[EventType, dict[str, Any]], None]

app = typer.Typer(
    help=(
        "FixProof fixes bugs in public Python repositories and proves each fix with tests in "
        "Nebius Token Factory Sandboxes, using NVIDIA Nemotron models."
    ),
    no_args_is_help=True,
    add_completion=False,
)


@dataclass
class Factories:
    """How the CLI builds its dependencies; tests replace them with fakes."""

    settings: Callable[[], Settings] = load_settings
    model: Callable[[Settings], ModelClient] = token_factory_client
    executor: Callable[[Settings, EventCallback], Executor] = make_executor
    repo_source: Callable[[Settings], RepoSource] = github_source
    github: Callable[[Settings], GitHubClient] = github_client


factories = Factories()


def exit_code_for(label: OutcomeLabel, stop_reason: StopReason) -> int:
    """Map a run's label and stop reason to the documented exit code."""
    if label is OutcomeLabel.VERIFIED:
        return EXIT_VERIFIED
    if label is OutcomeLabel.NEEDS_REVIEW:
        return EXIT_NEEDS_REVIEW
    if stop_reason in (
        StopReason.USER_STOP,
        StopReason.BUDGET_STEPS,
        StopReason.BUDGET_TIME,
        StopReason.BUDGET_COST,
    ):
        return EXIT_STOPPED
    if stop_reason in (StopReason.SETUP_FAILED, StopReason.NOT_REPRODUCIBLE):
        return EXIT_SETUP_FAILED
    if stop_reason is StopReason.INTERNAL_ERROR:
        return EXIT_INTERNAL_ERROR
    return EXIT_NOT_VERIFIED


def describe_event(event: TraceEvent, *, verbose: bool = False) -> str | None:
    """Return the one-line (or, for plans, multi-line) terminal rendering of an event."""
    d = event.data
    match event.type:
        case EventType.RUN_STARTED:
            task = d["task"]
            return f"run {event.run_id}: {d['repo_url']} ({task['kind']}) on {d['executor']}"
        case EventType.PHASE_CHANGED:
            return f"phase: {d['to']}"
        case EventType.REPO_FETCHED:
            return f"fetched {str(d['resolved_sha'])[:12]} ({d['size_kb']} KB)"
        case EventType.INSTALL_RESULT:
            return f"install: {d['command']} -> exit {d['exit_code']}"
        case EventType.TEST_RUN:
            c = d["counts"]
            target = d["selector"] or "full suite"
            return (
                f"tests {d['test_run_id']} [{target}]: {c['passed']} passed, {c['failed']} "
                f"failed, {c['error']} errors" + (" (timed out)" if d["timed_out"] else "")
            )
        case EventType.PLAN:
            steps = "\n".join(f"  {i}. {step}" for i, step in enumerate(d["steps"], start=1))
            return f"plan ({d['stage']}): {d['understanding']}\n{steps}"
        case EventType.TOOL_CALL:
            return f"-> {d['tool']}: {d['purpose']}"
        case EventType.TOOL_RESULT:
            return f"   {'ok' if d['ok'] else 'error'}: {d['summary']}"
        case EventType.REPRO_STATUS:
            return f"reproduction: {d['repro_test_id']} fails before the fix: {d['fails_before']}"
        case EventType.VERIFICATION:
            passes = ", ".join("pass" if p else "fail" for p in d["repro_passes"])
            return (
                f"verification: {d['label']} (reproduction: {passes}; regressions: "
                f"{len(d['regressions'])}; modified tests: {len(d['modified_test_files'])})"
            )
        case EventType.ATTEMPT_FINISHED:
            return f"attempt {event.attempt_id}: {d['status']} ({d['label']})"
        case EventType.BUDGET:
            limit = f" - limit reached: {d['limit_hit']}" if d["limit_hit"] else ""
            return (
                f"budget: {d['steps_used']} steps, {d['seconds_elapsed']:.0f} s, "
                f"${d['cost_usd']:.4f}{limit}"
            )
        case EventType.ERROR:
            return f"{'error' if d['fatal'] else 'warning'} ({d['where']}): {d['message']}"
        case EventType.REPORT:
            return f"report: {d['label']} ({d['stop_reason']})"
        case EventType.RUN_FINISHED:
            return (
                f"finished: {d['label']} ({d['stop_reason']}) in {d['duration_s']:.0f} s, "
                f"${d['cost_usd']:.4f}"
            )
    if not verbose:
        return None
    match event.type:
        case EventType.MODEL_CALL:
            fallback = f" (fallback from {d['fallback_from']})" if d["fallback_from"] else ""
            return (
                f"model {d['role']} {d['model']}{fallback}: {d['prompt_tokens']}+"
                f"{d['completion_tokens']} tokens, ${d['cost_usd']:.5f}"
            )
        case EventType.REASONING:
            return f"reasoning ({d['role']}): {str(d['text'])[:500]}"
        case EventType.SANDBOX_OP:
            return f"sandbox {d['op']}: {str(d['command'])[:100]} -> exit {d['exit_code']}"
        case EventType.SNAPSHOT:
            return f"snapshot {d['label']}: {d['image_id']}"
    return None


def _fail(message: str, code: int) -> NoReturn:
    Console(stderr=True, soft_wrap=True).print(f"error: {message}", markup=False, highlight=False)
    raise typer.Exit(code)


def _task_from_options(issue: str | None, test: str | None, bug: str | None) -> Task:
    options = {TaskKind.ISSUE: issue, TaskKind.FAILING_TEST: test, TaskKind.DESCRIPTION: bug}
    chosen = [(kind, value) for kind, value in options.items() if value]
    if len(chosen) != 1:
        _fail("give exactly one of --issue, --test, or --bug.", EXIT_INVALID_INPUT)
    kind, value = chosen[0]
    try:
        return Task(kind=kind, value=(value or "").strip())
    except ValidationError as exc:
        _fail(f"invalid task: {exc.errors()[0]['msg']}", EXIT_INVALID_INPUT)


def _budget(
    settings: Settings, max_steps: int | None, max_minutes: float | None, max_cost: float | None
) -> Budget:
    base = settings.budget_cli()
    try:
        return Budget(
            max_steps=max_steps if max_steps is not None else base.max_steps,
            max_seconds=int(max_minutes * 60) if max_minutes is not None else base.max_seconds,
            max_cost_usd=max_cost if max_cost is not None else base.max_cost_usd,
            max_parallel=base.max_parallel,
        )
    except ValidationError as exc:
        _fail(f"invalid budget: {exc.errors()[0]['msg']}", EXIT_INVALID_INPUT)


@app.callback(invoke_without_command=True)
def main(
    version: Annotated[bool, typer.Option("--version", help="Show the version and exit.")] = False,
) -> None:
    """Fix bugs in public Python repositories, with proof."""
    if version:
        typer.echo(f"fixproof {__version__}")
        raise typer.Exit(EXIT_VERIFIED)


@app.command()
def fix(
    repo: Annotated[str, typer.Option("--repo", help="Public GitHub repository URL.")],
    issue: Annotated[
        str | None, typer.Option("--issue", help="GitHub issue URL of the same repository.")
    ] = None,
    test: Annotated[
        str | None,
        typer.Option("--test", help="Failing pytest node ID, e.g. tests/test_x.py::test_y."),
    ] = None,
    bug: Annotated[
        str | None, typer.Option("--bug", help="Plain-English description of the bug.")
    ] = None,
    ref: Annotated[
        str | None, typer.Option("--ref", help="Branch, tag, or commit (default branch if unset).")
    ] = None,
    max_steps: Annotated[
        int | None, typer.Option("--max-steps", help="Model-call budget (default 40).")
    ] = None,
    max_minutes: Annotated[
        float | None, typer.Option("--max-minutes", help="Time budget in minutes (default 15).")
    ] = None,
    max_cost: Annotated[
        float | None, typer.Option("--max-cost", help="Cost budget in USD (default 1.00).")
    ] = None,
    parallel: Annotated[
        int,
        typer.Option(
            "--parallel",
            min=1,
            max=3,
            help="Hypotheses to try at once in separate sandbox branches (1 = single path).",
        ),
    ] = 1,
    exhaustive: Annotated[
        bool,
        typer.Option("--exhaustive", help="With --parallel, finish every branch, then pick."),
    ] = False,
    out: Annotated[Path, typer.Option("--out", help="Directory for run folders.")] = Path("runs"),
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="Also show model calls, sandbox operations, reasoning."),
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print the final report as JSON on stdout.")
    ] = False,
) -> None:
    """Run the agent on one task and prove the fix with tests."""
    task = _task_from_options(issue, test, bug)
    try:
        location = parse_repo_url(repo)
        if task.kind is TaskKind.ISSUE:
            parse_issue_url(task.value, location)
    except GitHubError as exc:
        _fail(str(exc), EXIT_INVALID_INPUT)
    settings = factories.settings()
    budget = _budget(settings, max_steps, max_minutes, max_cost)
    console = Console(stderr=json_output, soft_wrap=True, highlight=False)
    if settings.is_dev_endpoint():
        console.print(
            "DEV ONLY: NEBIUS_BASE_URL does not point at Nebius Token Factory.", markup=False
        )
    request = RunRequest(
        repo_url=repo,
        task=task,
        ref=ref,
        mode=RunMode.PARALLEL if parallel > 1 else RunMode.SINGLE,
        max_parallel=parallel,
        exhaustive=exhaustive,
    )
    try:
        run = asyncio.run(_run_fix(settings, budget, request, out, console, verbose))
    except ConfigError as exc:
        _fail(str(exc), EXIT_INVALID_INPUT)
    except Exception as exc:  # pragma: no cover - last-resort guard for unexpected failures
        _fail(f"{type(exc).__name__}: {exc}", EXIT_INTERNAL_ERROR)
    label = run.label or OutcomeLabel.NOT_VERIFIED
    stop_reason = run.stop_reason or StopReason.INTERNAL_ERROR
    run_dir = out / run.id
    console.print(f"Result: {label.value} ({stop_reason.value})", markup=False)
    console.print(f"Report: {run_dir / 'report.md'}", markup=False)
    if (run_dir / "patch.diff").exists():
        console.print(f"Patch:  {run_dir / 'patch.diff'}", markup=False)
    if json_output and run.report is not None:
        typer.echo(run.report.model_dump_json(indent=2))
    raise typer.Exit(exit_code_for(label, stop_reason))


async def _run_fix(
    settings: Settings,
    budget: Budget,
    request: RunRequest,
    out: Path,
    console: Console,
    verbose: bool,
) -> Run:
    bus = new_event_bus(settings)

    def publish(kind: EventType, data: dict[str, Any]) -> None:
        bus.publish(kind, data)

    model = factories.model(settings)
    executor = factories.executor(settings, publish)
    repo_source = factories.repo_source(settings)

    def render(event: TraceEvent) -> None:
        line = describe_event(event, verbose=verbose)
        if line:
            console.print(line, markup=False)

    bus.add_listener(render)
    orchestrator = Orchestrator(
        settings=settings,
        model=model,
        executor=executor,
        repo_source=repo_source,
        bus=bus,
        runs_dir=out,
        budget=budget,
    )
    restore = _install_interrupt_handler(orchestrator, console)
    try:
        return await orchestrator.run(request)
    finally:
        restore()
        await executor.close()
        await repo_source.aclose()


def _install_interrupt_handler(orchestrator: Orchestrator, console: Console) -> Callable[[], None]:
    """Make the first Ctrl+C stop the run gracefully; a second one aborts immediately."""
    if threading.current_thread() is not threading.main_thread():
        return lambda: None
    loop = asyncio.get_running_loop()
    previous = signal.getsignal(signal.SIGINT)

    def on_interrupt(signum: int, frame: FrameType | None) -> None:
        console.print("Stopping: saving partial results (Ctrl+C again aborts).", markup=False)
        signal.signal(signal.SIGINT, previous)
        loop.call_soon_threadsafe(orchestrator.stop)

    def restore() -> None:
        signal.signal(signal.SIGINT, previous)

    signal.signal(signal.SIGINT, on_interrupt)
    return restore


@app.command()
def serve(
    host: Annotated[str, typer.Option("--host", help="Interface to listen on.")] = "0.0.0.0",
    port: Annotated[int, typer.Option("--port", help="Port to listen on.")] = 7860,
) -> None:
    """Start the web demo for judges (refuses dev settings unless FIXPROOF_ALLOW_DEV=1)."""
    # Imported here so that the other commands do not pay for loading the web stack.
    import uvicorn

    from fixproof.web.app import create_app

    settings = factories.settings()
    try:
        assert_demo_safe(settings)
        web_app = create_app(settings=settings)
    except ConfigError as exc:
        _fail(str(exc), EXIT_INVALID_INPUT)
    if settings.allow_dev:
        Console(stderr=True).print(
            "DEV ONLY: FIXPROOF_ALLOW_DEV=1 is set; never use it for the public demo.", markup=False
        )
    uvicorn.run(web_app, host=host, port=port)


@app.command()
def replay(
    trace_path: Annotated[Path, typer.Argument(help="A recorded trace.jsonl file.")],
    speed: Annotated[float, typer.Option("--speed", help="Playback speed multiplier.")] = 4.0,
    verbose: Annotated[bool, typer.Option("--verbose", help="Show every event.")] = False,
) -> None:
    """Re-play a recorded run in the terminal, clearly labeled REPLAY."""
    if not trace_path.is_file():
        _fail(f"no such trace file: {trace_path}", EXIT_INVALID_INPUT)
    if speed <= 0:
        _fail("--speed must be positive.", EXIT_INVALID_INPUT)
    console = Console(soft_wrap=True, highlight=False)
    console.print(f"REPLAY of a recorded run (not live): {trace_path}", markup=False)

    async def play() -> None:
        async for event in replay_trace(trace_path, speed):
            line = describe_event(event, verbose=verbose)
            if line:
                console.print(f"[REPLAY] {line}", markup=False)

    try:
        asyncio.run(play())
    except (ValueError, KeyError) as exc:
        _fail(f"not a FixProof trace: {exc}", EXIT_INVALID_INPUT)


# -- taking the fix home (User Story 4, FR-016) ----------------------------------------------


def _load_run(run_dir: Path) -> tuple[Report, str]:
    """Return a run's report and patch text, or exit with a clear message."""
    report_file, patch_file = run_dir / "report.json", run_dir / "patch.diff"
    if not report_file.is_file():
        _fail(f"{run_dir} is not a FixProof run folder (no report.json).", EXIT_INVALID_INPUT)
    if not patch_file.is_file():
        _fail(f"The run in {run_dir} produced no patch.", EXIT_INVALID_INPUT)
    try:
        report = Report.model_validate_json(report_file.read_text(encoding="utf-8"))
    except ValidationError:
        _fail(f"{report_file} is not a valid FixProof report.", EXIT_INVALID_INPUT)
    if report.patch is None or report.patch.is_empty:
        _fail(f"The run in {run_dir} produced no patch.", EXIT_INVALID_INPUT)
    return report, patch_file.read_text(encoding="utf-8")


def _check_label(report: Report, force_unverified: bool, console: Console) -> None:
    """Refuse runs that are not verified unless the user insists (they still confirm)."""
    if report.label is not OutcomeLabel.NOT_VERIFIED:
        return
    if not force_unverified:
        _fail(
            "This run is not verified. Use --force-unverified to continue anyway; you will "
            "still see the change and be asked to confirm.",
            EXIT_INVALID_INPUT,
        )
    console.print("WARNING: this run is NOT VERIFIED; tests did not prove the fix.", markup=False)


def _show_change(console: Console, report: Report, diff: str) -> None:
    """Show the evidence summary and the full diff before asking for approval."""
    console.print("Evidence:", markup=False)
    for line in evidence_lines(report):
        console.print(f"  {line}", markup=False)
    console.print("", markup=False)
    console.print(diff.rstrip("\n"), markup=False)
    console.print("", markup=False)


def _approve() -> bool:
    """Ask the fixed question; anything other than ``y`` or ``yes`` declines."""
    try:
        answer = typer.prompt("Apply this patch? [y/N]", default="", show_default=False)
    except typer.Abort:
        return False
    return answer.strip().lower() in ("y", "yes")


def _run_origin(run_dir: Path) -> tuple[str, str, str]:
    """Return the repository URL, the commit, and the executor of a run, from its trace."""
    trace_file = run_dir / "trace.jsonl"
    repo_url = sha = None
    executor = "contree"
    if trace_file.is_file():
        for event in read_trace(trace_file):
            if event.type is EventType.RUN_STARTED:
                repo_url = event.data.get("repo_url")
                executor = str(event.data.get("executor") or executor)
            elif event.type is EventType.REPO_FETCHED:
                sha = event.data.get("resolved_sha")
    if not repo_url or not sha:
        _fail(f"{run_dir} does not record the repository and commit it ran on.", EXIT_INVALID_INPUT)
    return str(repo_url), str(sha), executor


@app.command()
def apply(
    run_dir: Annotated[Path, typer.Argument(help="A run folder, for example runs/<run_id>.")],
    to: Annotated[
        Path, typer.Option("--to", help="Your local checkout at the run's revision.")
    ] = Path("."),
    force_unverified: Annotated[
        bool,
        typer.Option(
            "--force-unverified", help="Allow a run that is not verified (you still confirm)."
        ),
    ] = False,
) -> None:
    """Apply a run's patch to your local checkout after you approve the exact diff."""
    console = Console(soft_wrap=True, highlight=False)
    report, diff = _load_run(run_dir)
    if not to.is_dir():
        _fail(f"{to} is not a folder.", EXIT_INVALID_INPUT)
    _check_label(report, force_unverified, console)
    problems = validate_patch(diff, to)
    if problems:
        _fail("The patch was rejected: " + "; ".join(problems), EXIT_PATCH_FAILED)
    patch_file = run_dir / "patch.diff"
    ok, message = git_apply(patch_file, to, check=True)
    if not ok:
        _fail(f"The patch does not apply to {to}: {message}", EXIT_PATCH_FAILED)
    _show_change(console, report, diff)
    if not _approve():
        console.print("Declined. Nothing was changed.", markup=False)
        raise typer.Exit(EXIT_DECLINED)
    ok, message = git_apply(patch_file, to, check=False)
    if not ok:
        _fail(f"git apply failed: {message}", EXIT_PATCH_FAILED)
    console.print(f"Applied to {to}. Review it with: git -C {to} diff", markup=False)


@app.command()
def pr(
    run_dir: Annotated[Path, typer.Argument(help="A run folder, for example runs/<run_id>.")],
    title: Annotated[str | None, typer.Option("--title", help="Pull request title.")] = None,
    draft: Annotated[
        bool, typer.Option("--draft/--no-draft", help="Open it as a draft (the default).")
    ] = True,
    force_unverified: Annotated[
        bool,
        typer.Option(
            "--force-unverified", help="Allow a run that is not verified (you still confirm)."
        ),
    ] = False,
) -> None:
    """Open a pull request with a run's patch from your own GitHub account, after approval."""
    console = Console(soft_wrap=True, highlight=False)
    report, diff = _load_run(run_dir)
    repo_url, base_sha, executor = _run_origin(run_dir)
    _check_label(report, force_unverified, console)
    settings = factories.settings()
    if settings.github_token is None or not settings.github_token.get_secret_value():
        _fail(
            "Set GITHUB_TOKEN to your own GitHub token (allowed to fork the repository and open "
            "pull requests). FixProof never uses a shared token for this.",
            EXIT_INVALID_INPUT,
        )
    with tempfile.TemporaryDirectory() as empty:
        problems = validate_patch(diff, Path(empty))
    if problems:
        _fail("The patch was rejected: " + "; ".join(problems), EXIT_PATCH_FAILED)
    pr_title = title or _default_title(report)
    _show_change(console, report, diff)
    kind = "draft pull request" if draft else "pull request"
    console.print(
        f"This opens a {kind} on {repo_url} from your GitHub account: {pr_title}", markup=False
    )
    if not _approve():
        console.print("Declined. Nothing was sent to GitHub.", markup=False)
        raise typer.Exit(EXIT_DECLINED)
    assert report.patch is not None  # checked by _load_run
    try:
        url = asyncio.run(
            _open_pull_request(
                settings,
                location=parse_repo_url(repo_url),
                base_sha=base_sha,
                run_id=report.run_id,
                patch=report.patch,
                title=pr_title,
                body=pull_request_body(report, executor=executor),
                draft=draft,
            )
        )
    except GitHubError as exc:
        _fail(f"GitHub did not accept the pull request: {exc}", EXIT_GITHUB_ERROR)
    console.print(f"Opened {url}", markup=False)


def _default_title(report: Report) -> str:
    first_sentence = report.summary.strip().split("\n")[0].split(". ")[0].rstrip(".")
    title = f"Fix: {first_sentence}" if first_sentence else f"FixProof fix ({report.run_id})"
    return title if len(title) <= 72 else title[:71] + "…"


async def _open_pull_request(settings: Settings, **arguments: Any) -> str:
    client = factories.github(settings)
    try:
        return await open_fix_pull_request(client, **arguments)
    finally:
        await client.aclose()


@dataclass(frozen=True)
class Check:
    """One ``doctor`` check."""

    name: str
    ok: bool
    detail: str
    hint: str = ""


_ROLE_VARIABLES = {
    "planner": "FIXPROOF_PLANNER_MODEL",
    "worker": "FIXPROOF_WORKER_MODEL",
    "condenser": "FIXPROOF_FALLBACK_MODEL",
}


@app.command()
def doctor(
    json_output: Annotated[bool, typer.Option("--json", help="Print the checks as JSON.")] = False,
) -> None:
    """Check keys, model IDs on Token Factory, and sandbox access; print a fix for each problem."""
    settings = factories.settings()
    checks = asyncio.run(_doctor_checks(settings))
    if json_output:
        typer.echo(json.dumps([asdict(c) for c in checks], indent=2))
    else:
        console = Console(soft_wrap=True, highlight=False)
        for check in checks:
            status = "OK  " if check.ok else "FAIL"
            console.print(f"{status} {check.name}: {check.detail}", markup=False)
            if not check.ok and check.hint:
                console.print(f"     fix: {check.hint}", markup=False)
    raise typer.Exit(EXIT_VERIFIED if all(c.ok for c in checks) else EXIT_DOCTOR_PROBLEMS)


async def _doctor_checks(settings: Settings) -> list[Check]:
    checks: list[Check] = []
    key = settings.nebius_api_key.get_secret_value() if settings.nebius_api_key else ""
    checks.append(
        Check(
            "NEBIUS_API_KEY",
            bool(key),
            "set" if key else "not set",
            ""
            if key
            else "Create a key at https://tokenfactory.nebius.com and add "
            "NEBIUS_API_KEY=... to .env.",
        )
    )
    dev = settings.is_dev_endpoint()
    checks.append(
        Check(
            "Model endpoint",
            not dev,
            settings.nebius_base_url + (" (DEV ONLY)" if dev else ""),
            "Unset NEBIUS_BASE_URL to use Nebius Token Factory; other endpoints are for local "
            "development only."
            if dev
            else "",
        )
    )
    if key:
        checks.extend(await _model_checks(settings))
    checks.append(await _sandbox_check(settings))
    return checks


async def _model_checks(settings: Settings) -> list[Check]:
    try:
        available = {m.lower() for m in await factories.model(settings).list_models()}
    except Exception as exc:
        return [
            Check(
                "Models",
                False,
                f"could not list models: {type(exc).__name__}: {exc}",
                "Check NEBIUS_API_KEY and that the Token Factory account is active.",
            )
        ]
    checks = []
    for role, model_id in settings.models_by_role().items():
        ok = model_id.lower() in available
        hint = (
            ""
            if ok
            else f"{model_id} is not listed by {settings.nebius_base_url}models; set "
            f"{_ROLE_VARIABLES[role]} to a listed NVIDIA Nemotron model."
        )
        checks.append(Check(f"Model ({role})", ok, model_id, hint))
    return checks


async def _sandbox_check(settings: Settings) -> Check:
    name = f"Sandbox ({settings.executor})"
    if settings.executor == "contree":
        hint = (
            "Request Sandboxes access at https://tokenfactory.nebius.com/sandboxes/about and set "
            "CONTREE_PROJECT (and CONTREE_TOKEN if it differs from NEBIUS_API_KEY)."
        )
    else:
        hint = "Start Docker Desktop. FIXPROOF_EXECUTOR=docker is for local development only."
    try:
        executor = factories.executor(settings, lambda kind, data: None)
    except Exception as exc:
        return Check(name, False, str(exc), hint)
    try:
        lister = getattr(executor, "list_images", None)
        if lister is None:
            return Check(name, True, f"{executor.name} executor ready")
        images = await lister(1)
        return Check(name, True, f"reachable ({len(images)} image listed)")
    except Exception as exc:
        return Check(name, False, f"not reachable: {type(exc).__name__}: {exc}", hint)
    finally:
        await executor.close()
