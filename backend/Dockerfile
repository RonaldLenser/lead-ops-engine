# ---------- Stage 1: builder ----------
# Has uv and build tooling. Installs dependencies into /app/.venv.
FROM python:3.12-slim-trixie AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, in their own layer: Docker reuses it from cache until
# pyproject.toml or uv.lock change, so code-only edits rebuild in seconds.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

# Then our own code.
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# ---------- Stage 2: runtime ----------
# Only Python and the finished virtualenv: no uv, no build tools, no source
# tree. Smaller image, smaller attack surface.
FROM python:3.12-slim-trixie AS runtime

RUN groupadd --system app && useradd --system --gid app --no-create-home app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app migrations ./migrations

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Never run as root: a compromised app process does not get root.
USER app
EXPOSE 8000

# Liveness only (no database), matching /healthz semantics.
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]

# Exec form: uvicorn is PID 1 and receives shutdown signals directly.
# --no-access-log: the app writes its own structured access log line.
# --no-proxy-headers: client IP handling is decided explicitly in M2, when
# rate limiting needs it, instead of trusting X-Forwarded-For by default.
CMD ["uvicorn", "leadops.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
