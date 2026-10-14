"""Published traces and benchmark results contain no credentials (FR-020, T081).

Scans every ``replays/*.jsonl`` and everything under ``bench/results/`` for token-shaped
values and for credential assignments that were not redacted.
"""

from __future__ import annotations

import re
from pathlib import Path

from fixproof.trace import REDACTED, SECRET_PATTERN

ROOT = Path(__file__).resolve().parents[2]
TOKEN_PATTERNS = {
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "Tavily key": re.compile(r"\btvly-[A-Za-z0-9_-]{10,}"),
    "sk- key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    "bearer token": re.compile(r"(?i)\bbearer\s+(?!\[REDACTED\])[A-Za-z0-9._~+/=-]{16,}"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}


def published_files() -> list[Path]:
    patterns = ("replays/*.jsonl", "bench/results/**/*.json", "bench/results/**/*.jsonl")
    return sorted({path for pattern in patterns for path in ROOT.glob(pattern) if path.is_file()})


def find_secrets(text: str) -> list[str]:
    """Return the kinds of credential found in ``text``."""
    found = [name for name, pattern in TOKEN_PATTERNS.items() if pattern.search(text)]
    if any(not m.group(3).startswith(REDACTED) for m in SECRET_PATTERN.finditer(text)):
        found.append("credential assignment")
    return found


def test_published_traces_and_results_hold_no_credentials() -> None:
    problems = {
        path.relative_to(ROOT).as_posix(): kinds
        for path in published_files()
        if (kinds := find_secrets(path.read_text(encoding="utf-8", errors="replace")))
    }
    assert problems == {}


def test_the_scan_recognizes_credentials() -> None:
    samples = [
        "ghp_" + "a1" * 18,
        "github_pat_" + "B2" * 15,
        "tvly-" + "c3" * 10,
        "sk-" + "d4" * 15,
        "Authorization: Bearer " + "e5" * 15,
        "AKIA" + "F6" * 8,
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3",
        "NEBIUS_API_KEY=abcdef123456",
    ]
    for sample in samples:
        assert find_secrets(sample), sample
    clean = '{"message": "token=[REDACTED]\\" here", "prompt_tokens": 120, "bearer": "x"}'
    assert find_secrets(clean) == []
