# FixProof judge demo (Hugging Face Spaces, Docker SDK) on port 7860.
#
# Live runs need these as Space secrets: NEBIUS_API_KEY, CONTREE_PROJECT (and CONTREE_TOKEN if it
# differs), and optionally GITHUB_TOKEN. Never set FIXPROOF_ALLOW_DEV here: the service refuses
# dev executors and non-Nebius model endpoints without it.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies first, so code changes do not reinstall them.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
COPY replays ./replays

RUN useradd --create-home --uid 1000 fixproof \
    && mkdir -p /app/runs \
    && chown -R fixproof /app/runs
USER fixproof

ENV PATH="/app/.venv/bin:${PATH}" \
    FIXPROOF_STATE_DIR=/app/runs

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/api/health', timeout=4)"
CMD ["fixproof", "serve", "--host", "0.0.0.0", "--port", "7860"]
