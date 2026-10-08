FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies go in a separate layer so that code changes don't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache

# The RAG engine of participant A (worker/) will be imported via RAG_ENGINE.
# When it is ready: add its dependencies (torch for BGE-M3 and others) to the image
# and copy worker/ here as well.
COPY api ./api

RUN useradd --system --no-create-home api
USER api

ENV PATH="/app/.venv/bin:$PATH" \
    API_HOST=0.0.0.0 \
    API_PORT=8000
EXPOSE 8000
CMD ["python", "-m", "api"]
