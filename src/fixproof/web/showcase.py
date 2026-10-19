"""Static showcase: the web demo as plain files that play the labeled replays in the browser.

Free static hosts (for example a Hugging Face Static Space) cannot run the FastAPI service.
``build_showcase`` asks a showcase app (``FIXPROOF_SHOWCASE=1``, no live runs) for its health,
samples, and replay catalog and writes those answers into one flat folder, next to the page,
its assets, and the replay traces. The page is marked ``data-mode="static"``, so ``app.js``
reads those files instead of the API and plays each trace with the server's replay timing.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import httpx

from fixproof.config import load_settings
from fixproof.web.app import STATIC_DIR, create_app, load_samples
from fixproof.web.runs import RunManager

API_FILES = {
    "/api/health": "health.json",
    "/api/samples": "samples.json",
    "/api/replays": "replays.json",
}
PAGE_EDITS = (
    ('<html lang="en">', '<html lang="en" data-mode="static">'),
    ('href="/static/style.css"', 'href="style.css"'),
    ('src="/static/app.js"', 'src="app.js"'),
)
README = """\
---
title: FixProof
emoji: ✅
colorFrom: green
colorTo: gray
sdk: static
pinned: false
license: mit
short_description: Recorded runs of an agent that proves its bug fixes
---

# FixProof: bug fixes with proof (showcase)

FixProof is an autonomous agent that fixes bugs in public Python repositories and **proves each
fix**. It reproduces the bug with a failing test and changes the code. Then the harness, not the
model, checks the result: the reproduction test must pass three times in a row, and no test
that passed before may fail. Only then is a fix labeled **Verified**.

This page is a **showcase** and starts no live runs. It replays real recorded runs, clearly
labeled REPLAY, in the browser. Each replay's title and report say where it ran; runs marked
"personal mode" used NVIDIA Nemotron models through another provider and local Docker
containers, not the Nebius Token Factory hackathon platform.
"""


async def build_showcase(out_dir: Path, replays_dir: Path = Path("replays")) -> list[Path]:
    """Write the static showcase into ``out_dir`` and return the files written.

    Args:
        out_dir: A new or empty folder.
        replays_dir: The replay catalog (``index.toml`` and ``<name>.jsonl`` traces).

    Raises:
        ValueError: If ``out_dir`` is not empty, there is no replay to show, or ``index.html``
            changed so that it can no longer be made static.
    """
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError(f"{out_dir} is not empty; choose a new or empty folder.")
    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for old, new in PAGE_EDITS:
        if old not in page:
            raise ValueError(f"index.html no longer contains {old!r}; update PAGE_EDITS.")
        page = page.replace(old, new)
    answers = await _api_answers(replays_dir)
    names = [entry["name"] for entry in json.loads(answers["replays.json"])]
    if not names:
        raise ValueError(f"{replays_dir} has no replay to show.")

    out_dir.mkdir(parents=True, exist_ok=True)
    written = [_write(out_dir / "index.html", page), _write(out_dir / "README.md", README)]
    written += [Path(shutil.copy(STATIC_DIR / name, out_dir)) for name in ("style.css", "app.js")]
    written += [_write(out_dir / file, body) for file, body in answers.items()]
    written += [Path(shutil.copy(replays_dir / f"{name}.jsonl", out_dir)) for name in names]
    return written


async def _api_answers(replays_dir: Path) -> dict[str, str]:
    """Return the showcase app's answers, keyed by the file name they are saved under."""
    with tempfile.TemporaryDirectory(prefix="fixproof-showcase-") as state:
        settings = load_settings(env_file=None).model_copy(
            update={"showcase": True, "state_dir": Path(state)}
        )
        manager = RunManager(settings, samples=load_samples(), replays_dir=replays_dir)
        try:
            transport = httpx.ASGITransport(app=create_app(manager=manager))
            async with httpx.AsyncClient(transport=transport, base_url="http://showcase") as client:
                answers: dict[str, str] = {}
                for path, file in API_FILES.items():
                    response = await client.get(path)
                    response.raise_for_status()
                    answers[file] = response.text
        finally:
            await manager.shutdown()
    return answers


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8", newline="\n")
    return path
