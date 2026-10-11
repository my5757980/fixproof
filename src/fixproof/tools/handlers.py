"""Tool implementations on top of the ``Executor`` (contracts/agent-tools.md).

Handlers only ever touch the isolated environment. The guards below are enforced by the harness,
never left to the model:

- every path must stay inside the repository root;
- ``run_command`` always runs disposably and rejects forbidden commands;
- in the reproduce phase, files that existed before the phase are frozen;
- output sent back to the model is bounded (``…[truncated N chars]``).

A handler raises ``ToolInputError`` for anything the model can fix (a wrong path, an ambiguous
edit); the tool box turns it into an error result for the model.
"""

from __future__ import annotations

import copy
import difflib
import json
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from fixproof.models import Snapshot, TestOutcome
from fixproof.sandbox.executor import Executor
from fixproof.sandbox.pytest_results import TestRunner
from fixproof.tools.schemas import (
    CreateFileArgs,
    EditFileArgs,
    FinishArgs,
    ListDirArgs,
    ReadFileArgs,
    RunCommandArgs,
    RunTestsArgs,
    SearchCodeArgs,
    WebSearchArgs,
)

TRUNCATION_MARKER = "…[truncated {n} chars]"
READ_MAX_LINES = 400
LIST_MAX_ENTRIES = 400
SEARCH_TEXT_LIMIT = 300
FAILURES_LIMIT = 20
SEARCH_TIMEOUT_S = 60
CREDENTIAL_ENV_NAMES = ("NEBIUS_API_KEY", "CONTREE_TOKEN", "GITHUB_TOKEN", "TAVILY_API_KEY")

_NOISE_DIRS = frozenset({".git", "__pycache__"})
_GREP_LINE = re.compile(r"^(?P<path>.+?):(?P<line>\d+):(?P<text>.*)$")
_FORBIDDEN_COMMANDS = (
    (re.compile(r"\bgit\s+push\b", re.IGNORECASE), "git push"),
    (re.compile(r"\bcurl\b", re.IGNORECASE), "curl"),
    (re.compile(r"\bwget\b", re.IGNORECASE), "wget"),
    (re.compile(r"\bpip3?\s+install\b", re.IGNORECASE), "pip install"),
    (re.compile(r"\brm\s+-[a-z]*r[a-z]*\s+/(?=\s|\*|$)", re.IGNORECASE), "rm -rf /"),
)


class ToolPhase(StrEnum):
    """Agent phase that decides which tools are offered (contract table)."""

    REPRODUCE = "reproduce"
    FIX = "fix"


class WebSearch(Protocol):
    """Optional web search backend (Tavily; off by default, FR-022)."""

    async def __call__(self, query: str) -> list[dict[str, str]]:
        """Return up to five results with ``title``, ``url``, and ``snippet``."""
        ...


class ToolInputError(Exception):
    """A tool call the harness refuses; it becomes an error result for the model.

    Args:
        code: Machine-readable error code from the tools contract.
        message: What failed and how the model can fix it.
        **extra: Additional fields for the result, such as ``count``.
    """

    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra

    def output(self) -> dict[str, Any]:
        """Return the error result in the contract shape ``{"error", "message", ...}``."""
        return {"error": self.code, "message": self.message, **self.extra}


@dataclass
class ToolContext:
    """Mutable state shared by the tools of one worker conversation.

    Attributes:
        executor: The isolated environment.
        snapshot: The current snapshot; mutating tools advance it.
        phase: The current phase (reproduce or fix).
        tests: Runs pytest and publishes ``test_run`` events.
        output_chars: Size limit of each tool result sent to the model.
        command_timeout_s: Upper bound for command and test timeouts.
        attempt_id: The attempt the calls belong to, for the trace.
        created_files: Files created by ``create_file`` in this conversation.
        phase_start: Snapshot at the start of the current phase.
        web_search: Optional search backend.
    """

    executor: Executor
    snapshot: Snapshot
    phase: ToolPhase
    tests: TestRunner
    output_chars: int = 8000
    command_timeout_s: int = 300
    attempt_id: str | None = None
    created_files: set[str] = field(default_factory=set)
    phase_start: Snapshot | None = None
    web_search: WebSearch | None = None

    def __post_init__(self) -> None:
        if self.phase_start is None:
            self.phase_start = self.snapshot

    def enter_phase(self, phase: ToolPhase) -> None:
        """Switch to ``phase``, starting it from the current snapshot."""
        self.phase = phase
        self.phase_start = self.snapshot


@dataclass(frozen=True)
class ToolOutcome:
    """Result of one tool call.

    Attributes:
        output: JSON-serializable result returned to the model.
        summary: One-line description for the trace.
        error: Error code, or ``None`` on success.
        finish: The accepted ``finish`` payload, when the call ended the attempt.
    """

    output: dict[str, Any]
    summary: str
    error: str | None = None
    finish: FinishArgs | None = None

    @property
    def ok(self) -> bool:
        """Whether the call succeeded."""
        return self.error is None

    @classmethod
    def from_error(cls, error: ToolInputError) -> ToolOutcome:
        """Build the outcome of a refused call."""
        return cls(output=error.output(), summary=one_line(error.message), error=error.code)


# -- helpers -------------------------------------------------------------------------------


def one_line(text: str, limit: int = 200) -> str:
    """Collapse whitespace to single spaces and cut ``text`` to ``limit`` characters."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def truncate_middle(text: str, limit: int) -> str:
    """Cut the middle of ``text`` so it fits in about ``limit`` characters.

    The head and tail are kept (errors are usually at the end of command output), and the
    removed part is replaced with ``…[truncated N chars]``.
    """
    if len(text) <= limit:
        return text
    keep = max(limit - len(TRUNCATION_MARKER.format(n=len(text))), 0)
    head = keep * 2 // 5
    tail = keep - head
    removed = len(text) - head - tail
    return text[:head] + TRUNCATION_MARKER.format(n=removed) + (text[-tail:] if tail else "")


def fit_output(output: Mapping[str, Any], limit: int) -> str:
    """Serialize ``output`` as JSON of at most about ``limit`` characters.

    The longest string values are shortened first, so the result stays valid JSON.
    """
    text = json.dumps(output, ensure_ascii=False)
    if len(text) <= limit:
        return text
    data: Any = copy.deepcopy(dict(output))
    for _ in range(50):
        found = _longest_string(data)
        if found is None:
            break
        container, key, value = found
        if len(value) <= 200:
            break
        overflow = len(text) - limit
        container[key] = truncate_middle(value, max(len(value) - overflow - 40, 160))
        text = json.dumps(data, ensure_ascii=False)
        if len(text) <= limit:
            return text
    return truncate_middle(text, limit)


def _longest_string(node: Any) -> tuple[Any, Any, str] | None:
    best: tuple[Any, Any, str] | None = None
    items: list[tuple[Any, Any, Any]] = []
    if isinstance(node, dict):
        items = [(node, key, value) for key, value in node.items()]
    elif isinstance(node, list):
        items = [(node, index, value) for index, value in enumerate(node)]
    for container, key, value in items:
        candidate = (container, key, value) if isinstance(value, str) else _longest_string(value)
        if candidate is not None and (best is None or len(candidate[2]) > len(best[2])):
            best = candidate
    return best


def repo_path(path: str, *, allow_root: bool = True) -> str:
    """Normalize a path relative to the repository root.

    Args:
        path: Path from the model.
        allow_root: Whether ``.`` (the root itself) is acceptable.

    Returns:
        The normalized relative path, or ``.`` for the root.

    Raises:
        ToolInputError: ``path_outside_repo`` for absolute paths or paths escaping the root.
    """
    raw = (path or ".").strip().replace("\\", "/")
    if raw.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", raw):
        raise ToolInputError(
            "path_outside_repo",
            f"{path!r} is absolute; use a path relative to the repository root.",
        )
    parts: list[str] = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise ToolInputError(
                    "path_outside_repo", f"{path!r} points outside the repository root."
                )
            parts.pop()
            continue
        parts.append(part)
    normalized = "/".join(parts) or "."
    if normalized == "." and not allow_root:
        raise ToolInputError("invalid_arguments", "A file path is required, not the root.")
    return normalized


def _writable_path(path: str) -> str:
    normalized = repo_path(path, allow_root=False)
    if normalized.split("/", 1)[0] == ".git":
        raise ToolInputError("path_outside_repo", "Files inside .git cannot be changed.")
    return normalized


def forbidden_reason(command: str) -> str | None:
    """Return why ``command`` is not allowed in ``run_command``, or ``None`` if it is allowed."""
    for pattern, label in _FORBIDDEN_COMMANDS:
        if pattern.search(command):
            return label
    upper = command.upper()
    for name in CREDENTIAL_ENV_NAMES:
        if name in upper:
            return f"a reference to {name}"
    return None


def build_search_command(pattern: str, path: str, glob: str, max_results: int) -> str:
    """Build the ``grep`` command used by ``search_code`` (every argument is shell-quoted)."""
    return (
        "grep -rnE --binary-files=without-match --exclude-dir=.git --exclude-dir=__pycache__ "
        f"--include={shlex.quote(glob)} -e {shlex.quote(pattern)} -- {shlex.quote(path)} "
        f"| head -n {max_results + 1}"
    )


def parse_search_output(stdout: str) -> list[dict[str, Any]]:
    """Parse ``path:line:text`` lines printed by ``grep -rn``."""
    matches: list[dict[str, Any]] = []
    for raw in stdout.splitlines():
        match = _GREP_LINE.match(raw)
        if match:
            matches.append(
                {
                    "path": match["path"].removeprefix("./"),
                    "line": int(match["line"]),
                    "text": match["text"][:SEARCH_TEXT_LIMIT],
                }
            )
    return matches


async def _read_bytes(ctx: ToolContext, path: str) -> bytes:
    try:
        return await ctx.executor.read_file(ctx.snapshot, path)
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError) as exc:
        raise ToolInputError(
            "not_found",
            f"{path} does not exist or is not a file. Use list_dir or search_code to find it.",
        ) from exc


async def _exists(ctx: ToolContext, path: str) -> bool:
    try:
        await ctx.executor.read_file(ctx.snapshot, path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except IsADirectoryError:
        return True
    return True


def _crlf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


# -- handlers ------------------------------------------------------------------------------


async def list_dir(ctx: ToolContext, args: ListDirArgs) -> ToolOutcome:
    """List files and folders under a repository path."""
    path = repo_path(args.path)
    try:
        entries = await ctx.executor.list_dir(ctx.snapshot, path, args.depth)
    except (FileNotFoundError, NotADirectoryError):
        entries = []
    entries = [e for e in entries if not _NOISE_DIRS.intersection(e.path.split("/"))]
    if not entries and path != ".":
        raise ToolInputError(
            "not_found", f"{path} is not a directory in the repository (or it is empty)."
        )
    truncated = len(entries) > LIST_MAX_ENTRIES
    shown = entries[:LIST_MAX_ENTRIES]
    output = {
        "entries": [{"path": e.path, "type": e.type, "size": e.size} for e in shown],
        "truncated": truncated,
    }
    summary = f"{len(shown)} entries under {path}" + (" (truncated)" if truncated else "")
    return ToolOutcome(output, summary)


async def read_file(ctx: ToolContext, args: ReadFileArgs) -> ToolOutcome:
    """Read numbered lines of a file (at most 400 lines per call)."""
    path = repo_path(args.path, allow_root=False)
    if args.end_line < args.start_line:
        raise ToolInputError("invalid_arguments", "end_line must be greater than start_line.")
    data = await _read_bytes(ctx, path)
    if b"\x00" in data[:8192]:
        raise ToolInputError("binary_file", f"{path} is a binary file and cannot be read as text.")
    lines = data.decode("utf-8", errors="replace").splitlines()
    total = len(lines)
    if total and args.start_line > total:
        raise ToolInputError(
            "invalid_arguments",
            f"start_line {args.start_line} is past the end of {path} ({total} lines).",
        )
    last = min(args.end_line, args.start_line + READ_MAX_LINES - 1, total)
    char_budget = max(ctx.output_chars - 400, 500)
    rendered: list[str] = []
    used = 0
    end = args.start_line - 1
    for number in range(args.start_line, last + 1):
        line = f"{number}: {lines[number - 1]}"
        if rendered and used + len(line) + 1 > char_budget:
            break
        rendered.append(line)
        used += len(line) + 1
        end = number
    text = "\n".join(rendered)
    if end < last:
        omitted = sum(len(f"{n}: {lines[n - 1]}") + 1 for n in range(end + 1, last + 1))
        text += "\n" + TRUNCATION_MARKER.format(n=omitted)
    output = {
        "path": path,
        "start_line": args.start_line,
        "end_line": end,
        "total_lines": total,
        "text": text,
    }
    return ToolOutcome(output, f"read {path} lines {args.start_line}-{end} of {total}")


async def search_code(ctx: ToolContext, args: SearchCodeArgs) -> ToolOutcome:
    """Search repository files with ``grep -rnE`` inside the sandbox."""
    path = repo_path(args.path)
    try:
        re.compile(args.pattern)
    except re.error as exc:
        raise ToolInputError("invalid_pattern", f"Invalid regular expression: {exc}.") from exc
    command = build_search_command(args.pattern, path, args.glob, args.max_results)
    timeout = min(SEARCH_TIMEOUT_S, ctx.command_timeout_s)
    result, _ = await ctx.executor.run(ctx.snapshot, command, timeout_s=timeout, mutate=False)
    matches = parse_search_output(result.stdout)
    if not matches and result.stderr.strip():
        if "No such file" in result.stderr:
            raise ToolInputError("not_found", f"{path} does not exist in the repository.")
        raise ToolInputError(
            "invalid_pattern", f"grep rejected the pattern: {one_line(result.stderr, 300)}"
        )
    truncated = len(matches) > args.max_results
    matches = matches[: args.max_results]
    summary = f"{len(matches)} matches for /{one_line(args.pattern, 60)}/ in {path}"
    return ToolOutcome({"matches": matches, "truncated": truncated}, summary)


async def create_file(ctx: ToolContext, args: CreateFileArgs) -> ToolOutcome:
    """Create a new file; fails if the path already exists."""
    path = _writable_path(args.path)
    if await _exists(ctx, path):
        raise ToolInputError(
            "already_exists", f"{path} already exists; use edit_file to change it."
        )
    ctx.snapshot = await ctx.executor.write_files(
        ctx.snapshot, {path: args.content.encode("utf-8")}
    )
    ctx.created_files.add(path)
    line_count = len(args.content.splitlines())
    output = {"path": path, "created": True, "snapshot": ctx.snapshot.image_id}
    return ToolOutcome(output, f"created {path} ({line_count} lines)")


async def edit_file(ctx: ToolContext, args: EditFileArgs) -> ToolOutcome:
    """Replace exactly one occurrence of ``old_text`` and return the diff of the edit."""
    path = _writable_path(args.path)
    if ctx.phase is ToolPhase.REPRODUCE and path not in ctx.created_files:
        raise ToolInputError(
            "test_file_edit_blocked_in_reproduce",
            f"{path} is frozen: in the reproduce phase you may only edit files you created in "
            "this phase. Source files can be changed in the fix phase.",
        )
    data = await _read_bytes(ctx, path)
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolInputError("binary_file", f"{path} is not UTF-8 text.") from exc
    old, new = args.old_text, args.new_text
    count = content.count(old)
    if count == 0 and "\r\n" in content:
        count = content.count(_crlf(old))
        if count:
            old, new = _crlf(old), _crlf(new)
    if count == 0:
        raise ToolInputError(
            "no_match",
            f"old_text was not found in {path}. Read the file again and copy the exact text, "
            "without the line-number prefixes.",
        )
    if count > 1:
        raise ToolInputError(
            "multiple_matches",
            f"old_text occurs {count} times in {path}; include more surrounding lines so it is "
            "unique.",
            count=count,
        )
    updated = content.replace(old, new, 1)
    diff_lines = list(
        difflib.unified_diff(
            content.splitlines(),
            updated.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=2,
            lineterm="",
        )
    )
    if updated != content:
        ctx.snapshot = await ctx.executor.write_files(ctx.snapshot, {path: updated.encode("utf-8")})
    added = sum(1 for d in diff_lines if d.startswith("+") and not d.startswith("+++"))
    removed = sum(1 for d in diff_lines if d.startswith("-") and not d.startswith("---"))
    output = {"path": path, "diff": "\n".join(diff_lines), "snapshot": ctx.snapshot.image_id}
    return ToolOutcome(output, f"edited {path} (+{added} -{removed})")


async def run_tests(ctx: ToolContext, args: RunTestsArgs) -> ToolOutcome:
    """Run pytest on a selector (or the full suite) without changing the snapshot."""
    try:
        run = await ctx.tests.run(ctx.snapshot, args.selector, attempt_id=ctx.attempt_id)
    except ValueError as exc:
        raise ToolInputError("invalid_arguments", str(exc)) from exc
    bad = (TestOutcome.FAILED, TestOutcome.ERROR)
    failures = [
        {"node_id": r.node_id, "message": (r.message or "")[:500]}
        for r in run.results
        if r.outcome in bad
    ][:FAILURES_LIMIT]
    output = {
        "exit_code": run.exit_code,
        "counts": run.counts,
        "failures": failures,
        "output_tail": run.output_tail[-2000:],
        "timed_out": run.timed_out,
        "test_run_id": run.id,
    }
    counts = run.counts
    if run.results:
        summary = (
            f"{run.id}: {counts['passed']} passed, {counts['failed']} failed, "
            f"{counts['error']} errors"
        )
    else:
        summary = f"{run.id}: no tests ran (exit {run.exit_code})"
    if run.timed_out:
        summary += " (timed out)"
    return ToolOutcome(output, summary)


async def run_command(ctx: ToolContext, args: RunCommandArgs) -> ToolOutcome:
    """Run a read-only inspection command; the snapshot never changes."""
    reason = forbidden_reason(args.command)
    if reason is not None:
        raise ToolInputError(
            "forbidden_command",
            f"{reason} is not allowed in run_command. Change files with create_file or edit_file; "
            "the sandbox has no network access and no credentials.",
        )
    timeout = min(args.timeout_s, ctx.command_timeout_s)
    result, _ = await ctx.executor.run(ctx.snapshot, args.command, timeout_s=timeout, mutate=False)
    output = {
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "timed_out": result.timed_out,
    }
    summary = f"exit {result.exit_code}" + (" (timed out)" if result.timed_out else "")
    return ToolOutcome(output, summary)


async def web_search(ctx: ToolContext, args: WebSearchArgs) -> ToolOutcome:
    """Search the web with a short query (only when enabled, FR-022)."""
    if ctx.web_search is None:
        raise ToolInputError("disabled", "Web search is disabled for this run.")
    try:
        results = await ctx.web_search(args.query)
    except Exception as exc:
        raise ToolInputError("search_failed", f"Search failed ({type(exc).__name__}).") from exc
    return ToolOutcome({"results": results[:5]}, f"{len(results)} results for {args.query!r}")


async def finish(ctx: ToolContext, args: FinishArgs) -> ToolOutcome:
    """Accept the attempt and hand over to independent verification (never sets the label)."""
    changed = ctx.phase_start is not None and ctx.snapshot.image_id != ctx.phase_start.image_id
    if ctx.phase is ToolPhase.FIX and changed and not args.citations:
        raise ToolInputError(
            "missing_citations",
            "Add citations (path, start_line, end_line) of the code involved in the root cause, "
            "then call finish again.",
        )
    output = {"accepted": True, "next": "verification"}
    return ToolOutcome(output, "finish: handing over to independent verification", finish=args)
