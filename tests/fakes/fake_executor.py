"""In-memory fake of the ``Executor`` protocol for offline tests (never imported by ``src/``).

Snapshots are copy-on-write dictionaries of ``path -> bytes``. Built-in command handlers simulate
pytest (emitting the exact marker + JUnit format of ``fixproof.sandbox.pytest_results``), pip
installs, the git baseline, and git diffs computed from filesystem deltas. Tests can register
extra rules (regex -> handler) and control behavior through simple switches.
"""

from __future__ import annotations

import asyncio
import base64
import difflib
import fnmatch
import gzip
import inspect
import io
import itertools
import re
import shlex
import tarfile
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import quoteattr

from fixproof.models import Snapshot, TestCaseResult, TestOutcome
from fixproof.sandbox.executor import BASELINE_TAG, PATCH_MARKERS, CommandResult, DirEntry
from fixproof.sandbox.pytest_results import JUNIT_GZ_BEGIN, JUNIT_GZ_END, OUT_BEGIN, OUT_END

Files = dict[str, bytes]
RuleResult = CommandResult | tuple[CommandResult, Files]
Rule = Callable[[str, Files], RuleResult | Awaitable[RuleResult]]
TestBehavior = Callable[[Mapping[str, bytes], str | None], list[TestCaseResult]]


@dataclass(frozen=True)
class CommandRecord:
    snapshot_id: str
    command: str
    mutate: bool
    timeout_s: int


class FakeExecutor:
    """Deterministic in-memory executor."""

    name = "fake"

    def __init__(
        self, files: Mapping[str, str | bytes] | None = None, *, delay_s: float = 0.0
    ) -> None:
        self.initial_files: Files = {k: _b(v) for k, v in (files or {}).items()}
        self.delay_s = delay_s
        self._fs: dict[str, Files] = {}
        self._parents: dict[str, str | None] = {}
        self._ids = itertools.count(1)
        self.baseline: Files | None = None
        self.rules: list[tuple[re.Pattern[str], Rule]] = []
        self.install_ok = True
        self.install_failures_remaining = 0
        self.test_behavior: TestBehavior | None = None
        self.commands: list[CommandRecord] = []
        self.base_images: list[str] = []
        self.written: list[dict[str, bytes]] = []
        self.active = 0
        self.max_active = 0
        self.cancelled = False
        self.closed = False

    # -- helpers for tests -------------------------------------------------------------------

    def add_rule(self, pattern: str, handler: Rule) -> FakeExecutor:
        self.rules.append((re.compile(pattern), handler))
        return self

    def files(self, snapshot: Snapshot | str) -> Files:
        image_id = snapshot if isinstance(snapshot, str) else snapshot.image_id
        return dict(self._fs[image_id])

    def new_snapshot(
        self, files: Mapping[str, bytes], *, parent: str | None, label: str
    ) -> Snapshot:
        image_id = f"fake-img-{next(self._ids)}"
        self._fs[image_id] = dict(files)
        self._parents[image_id] = parent
        return Snapshot(image_id=image_id, parent_id=parent, label=label)

    # -- Executor protocol -------------------------------------------------------------------

    async def prepare_repo(self, tarball_path: Path, base_image: str) -> Snapshot:
        self.base_images.append(base_image)
        files = dict(self.initial_files)
        if tarball_path.exists():
            files = _read_tarball(tarball_path)
        return self.new_snapshot(files, parent=None, label="source")

    async def run(
        self, snapshot: Snapshot, command: str, *, timeout_s: int, mutate: bool
    ) -> tuple[CommandResult, Snapshot]:
        self.commands.append(CommandRecord(snapshot.image_id, command, mutate, timeout_s))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
            fs = self.files(snapshot)
            outcome = self._dispatch(command, fs)
            if inspect.isawaitable(outcome):
                outcome = await outcome
            if isinstance(outcome, tuple):
                result, fs = outcome
            else:
                result = outcome
        finally:
            self.active -= 1
        if not mutate:
            return result, snapshot
        return result, self.new_snapshot(fs, parent=snapshot.image_id, label="run")

    async def read_file(self, snapshot: Snapshot, path: str) -> bytes:
        fs = self._fs[snapshot.image_id]
        key = _norm(path)
        if key not in fs:
            if any(name.startswith(key.rstrip("/") + "/") for name in fs):
                raise IsADirectoryError(path)
            raise FileNotFoundError(path)
        return fs[key]

    async def list_dir(self, snapshot: Snapshot, path: str = ".", depth: int = 2) -> list[DirEntry]:
        base = _norm(path)
        prefix = "" if base in ("", ".") else base.rstrip("/") + "/"
        entries: dict[str, DirEntry] = {}
        for file_path, content in self._fs[snapshot.image_id].items():
            if not file_path.startswith(prefix):
                continue
            rel_parts = file_path[len(prefix) :].split("/")
            for level in range(1, min(len(rel_parts), depth) + 1):
                rel = "/".join(rel_parts[:level])
                full = prefix + rel
                is_file = level == len(rel_parts)
                entries[full] = DirEntry(
                    path=full,
                    type="file" if is_file else "dir",
                    size=len(content) if is_file else 0,
                )
        return sorted(entries.values(), key=lambda e: e.path)

    async def write_files(self, snapshot: Snapshot, files: Mapping[str, bytes]) -> Snapshot:
        fs = self.files(snapshot)
        self.written.append(dict(files))
        for path, content in files.items():
            fs[_norm(path)] = content
        return self.new_snapshot(fs, parent=snapshot.image_id, label="write")

    async def tag(self, snapshot: Snapshot, label: str) -> Snapshot:
        return snapshot.model_copy(update={"tag": label, "label": label.rsplit("/", 1)[-1]})

    async def cancel_all(self) -> None:
        self.cancelled = True

    async def close(self) -> None:
        self.closed = True

    # -- built-in command simulation ---------------------------------------------------------

    def _dispatch(self, command: str, fs: Files) -> RuleResult | Awaitable[RuleResult]:
        for pattern, handler in self.rules:
            if pattern.search(command):
                return handler(command, fs)
        if "python -m pytest" in command:
            return self._pytest(command, fs)
        if command.startswith("grep -rnE"):
            return _grep(command, fs)
        if "pip install" in command:
            return self._pip()
        if command.startswith("git init"):
            self.baseline = dict(fs)
            return CommandResult(stdout="")
        if PATCH_MARKERS[0] in command:
            diff, numstat, names = self._unified_diff(fs), self._numstat(fs), self._name_status(fs)
            sections = zip(PATCH_MARKERS, (diff, numstat, names), strict=True)
            return CommandResult(stdout="".join(f"{m}\n{body}\n" for m, body in sections))
        if f"--numstat {BASELINE_TAG}" in command:
            return CommandResult(stdout=self._numstat(fs))
        if f"--name-status --no-renames {BASELINE_TAG}" in command:
            return CommandResult(stdout=self._name_status(fs))
        if f"--no-ext-diff {BASELINE_TAG}" in command:
            return CommandResult(stdout=self._unified_diff(fs))
        if command.startswith("git ls-files --others"):
            return CommandResult(stdout="")
        return CommandResult(stdout="", stderr=f"fake: command not found: {command}", exit_code=127)

    def _pip(self) -> CommandResult:
        if self.install_failures_remaining > 0:
            self.install_failures_remaining -= 1
            return CommandResult(stdout="", stderr="ERROR: could not install", exit_code=1)
        if not self.install_ok:
            return CommandResult(stdout="", stderr="ERROR: could not install", exit_code=1)
        return CommandResult(stdout="Successfully installed")

    def _pytest(self, command: str, fs: Files) -> CommandResult:
        selector = _selector_from(command)
        results = self.test_behavior(fs, selector) if self.test_behavior else []
        failed = any(r.outcome in (TestOutcome.FAILED, TestOutcome.ERROR) for r in results)
        exit_code = 5 if not results else (1 if failed else 0)
        stdout = render_pytest_stdout(results, console=f"{len(results)} tests ran")
        return CommandResult(stdout=stdout, exit_code=exit_code)

    def _changed(self, fs: Files) -> tuple[dict[str, tuple[bytes | None, bytes | None]], Files]:
        base = self.baseline or {}
        changed: dict[str, tuple[bytes | None, bytes | None]] = {}
        for path in sorted(set(base) | set(fs)):
            before, after = base.get(path), fs.get(path)
            if before != after:
                changed[path] = (before, after)
        return changed, base

    def _numstat(self, fs: Files) -> str:
        changed, _ = self._changed(fs)
        lines = []
        for path, (before, after) in changed.items():
            diff = list(difflib.unified_diff(_lines(before), _lines(after), lineterm=""))
            added = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
            removed = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
            lines.append(f"{added}\t{removed}\t{path}")
        return "\n".join(lines)

    def _name_status(self, fs: Files) -> str:
        changed, _ = self._changed(fs)
        codes = {(True, False): "A", (False, True): "D"}
        return "\n".join(
            f"{codes.get((before is None, after is None), 'M')}\t{path}"
            for path, (before, after) in changed.items()
        )

    def _unified_diff(self, fs: Files) -> str:
        changed, _ = self._changed(fs)
        chunks = []
        for path, (before, after) in changed.items():
            chunks.extend(
                difflib.unified_diff(
                    _lines(before),
                    _lines(after),
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                    lineterm="",
                )
            )
        return "\n".join(chunks)


def render_pytest_stdout(results: list[TestCaseResult], console: str = "") -> str:
    """Render results in the exact stdout format produced by ``build_pytest_command``."""
    cases = []
    for r in results:
        path, _, rest = r.node_id.partition("::")
        name = rest.split("::")[-1] if rest else r.node_id
        classes = rest.split("::")[:-1] if rest else []
        module = path.removesuffix(".py").replace("/", ".")
        classname = ".".join([module, *classes])
        child = ""
        message = quoteattr(r.message or "")
        if r.outcome is TestOutcome.FAILED:
            child = f"<failure message={message}>{r.message or ''}</failure>"
        elif r.outcome is TestOutcome.ERROR:
            child = f"<error message={message}>{r.message or ''}</error>"
        elif r.outcome is TestOutcome.SKIPPED:
            child = f"<skipped message={message} />"
        cases.append(
            f"<testcase classname={quoteattr(classname)} name={quoteattr(name)} "
            f"file={quoteattr(path)} "
            f'time="{r.duration_s:.3f}">{child}</testcase>'
        )
    xml = (
        '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" time="0.010">'
        f"{''.join(cases)}</testsuite></testsuites>"
    )
    packed = base64.b64encode(gzip.compress(xml.encode("utf-8"))).decode() if results else ""
    return f"{OUT_BEGIN}\n{console}\n{OUT_END}\n{JUNIT_GZ_BEGIN}\n{packed}\n{JUNIT_GZ_END}\n"


def outcome(node_id: str, result: str = "passed", message: str | None = None) -> TestCaseResult:
    """Shorthand for building a ``TestCaseResult`` in tests."""
    return TestCaseResult(node_id=node_id, outcome=TestOutcome(result), message=message)


def make_tarball(
    dest: Path, files: Mapping[str, str | bytes], top: str = "owner-repo-abc123"
) -> Path:
    """Write a GitHub-style tarball (single top-level directory) for ``prepare_repo``."""
    with tarfile.open(dest, "w:gz") as tar:
        for path, content in files.items():
            data = _b(content)
            info = tarfile.TarInfo(name=f"{top}/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return dest


def _read_tarball(path: Path) -> Files:
    files: Files = {}
    with tarfile.open(path, "r:*") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            name = member.name.split("/", 1)[1] if "/" in member.name else member.name
            extracted = tar.extractfile(member)
            if extracted is not None:
                files[_norm(name)] = extracted.read()
    return files


def _grep(command: str, fs: Files) -> CommandResult:
    """Simulate ``fixproof.tools.handlers.build_search_command`` (``grep -rnE ... | head``)."""
    left, _, limit = command.partition(" | head -n ")
    tokens = shlex.split(left)
    pattern = tokens[tokens.index("-e") + 1]
    glob = next(t.removeprefix("--include=") for t in tokens if t.startswith("--include="))
    root = tokens[tokens.index("--") + 1]
    try:
        regex = re.compile(pattern)
    except re.error:
        return CommandResult(stdout="", stderr="grep: Unmatched ( or \\(")
    prefix = "" if root == "." else root.rstrip("/") + "/"
    if prefix and not any(p == root or p.startswith(prefix) for p in fs):
        return CommandResult(stdout="", stderr=f"grep: {root}: No such file or directory")
    # Like GNU grep, a single file operand prints "line:text" unless -H is given.
    names = "-H" in tokens or root not in fs
    lines = []
    for path in sorted(fs):
        in_root = not prefix or path == root or path.startswith(prefix)
        content = fs[path]
        if not in_root or not fnmatch.fnmatch(path.rsplit("/", 1)[-1], glob) or b"\0" in content:
            continue
        shown = f"./{path}" if root == "." else path
        for number, text in enumerate(content.decode("utf-8", "replace").splitlines(), start=1):
            if regex.search(text):
                lines.append(f"{shown}:{number}:{text}" if names else f"{number}:{text}")
    return CommandResult(stdout="\n".join(lines[: int(limit or len(lines) or 1)]))


def _selector_from(command: str) -> str | None:
    match = re.search(r"--junitxml=\S+(.*?) > ", command)
    if not match or not match.group(1).strip():
        return None
    return " ".join(shlex.split(match.group(1)))


def _lines(content: bytes | None) -> list[str]:
    return [] if content is None else content.decode("utf-8", "replace").splitlines()


def _norm(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./").lstrip("/")


def _b(value: str | bytes) -> bytes:
    return value.encode() if isinstance(value, str) else value
