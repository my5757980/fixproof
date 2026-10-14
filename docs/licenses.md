# Licenses

FixProof is released under the [MIT License](../LICENSE).

## Dependencies and licenses

Runtime dependencies, as resolved in `uv.lock` (from `uv tree --no-dev` and each package's
metadata, checked on 2026-10-14). Development tools (pytest, ruff, mypy) are not distributed
and are not listed.

| Package | Version | License | Used for |
|---|---|---|---|
| openai | 3.28.0 | Apache-2.0 | Token Factory client (OpenAI-compatible API) |
| contree-sdk | 0.3.6 | Apache-2.0 | Token Factory Sandboxes client |
| httpx | 0.28.1 | BSD-3-Clause | GitHub and Tavily HTTP calls |
| pydantic | 2.14.0 | MIT | Data models and validation |
| pydantic-settings | 2.15.0 | MIT | Configuration from the environment |
| fastapi | 0.143.0 | MIT | Web demo API |
| uvicorn | 0.54.0 | BSD-3-Clause | Web demo server |
| typer | 0.27.3 | MIT | Command-line interface |
| rich | 15.0.0 | MIT | Terminal output |
| aiofiles | 25.1.0 | Apache-2.0 | (via contree-sdk) |
| cattrs | 26.2.1 | MIT | (via contree-sdk) |
| attrs | 26.1.0 | MIT | (via cattrs) |
| StrEnum | 0.4.15 | MIT | (via contree-sdk) |
| anyio | 4.15.1 | MIT | (via httpx, openai, starlette) |
| idna | 3.20 | BSD-3-Clause | (via httpx) |
| certifi | 2026.7.22 | MPL-2.0 | (via httpx) |
| httpcore | 1.0.9 | BSD-3-Clause | (via httpx) |
| h11 | 0.16.0 | MIT | (via httpcore, uvicorn) |
| httpx2 | 2.13.1 | BSD-3-Clause | (via openai) |
| httpcore2 | 2.13.1 | BSD-3-Clause | (via httpx2) |
| truststore | 0.10.4 | MIT | (via httpx2) |
| jiter | 0.17.0 | MIT | (via openai) |
| sniffio | 1.3.1 | MIT OR Apache-2.0 | (via openai) |
| starlette | 1.7.0 | BSD-3-Clause | (via fastapi) |
| annotated-doc | 0.0.5 | MIT | (via fastapi, typer) |
| opentelemetry-api | 1.45.1 | Apache-2.0 | (via fastapi) |
| annotated-types | 0.8.0 | MIT | (via pydantic) |
| pydantic-core | 2.50.0 | MIT | (via pydantic) |
| typing-inspection | 0.4.4 | MIT | (via pydantic) |
| typing-extensions | 4.16.0 | PSF-2.0 | (via several packages) |
| python-dotenv | 1.2.4 | BSD-3-Clause | (via pydantic-settings) |
| markdown-it-py | 4.2.0 | MIT | (via rich) |
| mdurl | 0.1.2 | MIT | (via markdown-it-py) |
| Pygments | 2.21.0 | BSD-2-Clause | (via rich) |
| click | 8.5.0 | BSD-3-Clause | (via typer, uvicorn) |
| colorama | 0.4.6 | BSD-3-Clause | (via typer) |
| shellingham | 1.5.4 | ISC | (via typer) |

**Compatibility with MIT (Constitution I)**: every runtime dependency uses a permissive license
(MIT, BSD, ISC, Apache-2.0, PSF-2.0) except certifi, which uses MPL-2.0. MPL-2.0 is a
file-level license: it applies only to certifi's own files, which FixProof installs unmodified
as a dependency and does not copy into its source. All licenses are therefore compatible with
releasing FixProof under MIT. FixProof vendors no third-party code.

## Models and services

- NVIDIA Nemotron models are used through the Nebius Token Factory API under Nebius's and
  NVIDIA's terms. FixProof distributes no model weights.
- Token Factory Sandboxes and the optional Tavily search are used as services under their own
  terms.

## Benchmark data

- The tasks in `bench/tasks.toml` come from SWE-bench Verified
  (`princeton-nlp/SWE-bench_Verified`) and the SWE-bench test split (`princeton-nlp/SWE-bench`),
  both under the MIT License: instance IDs, base commits, issue text, and the lists of hidden
  tests.
- The files in `bench/hidden/` are the official test patches of those fixes, taken from the
  projects themselves and kept under the projects' licenses: Requests (Apache-2.0) and Flask
  (BSD-3-Clause).
