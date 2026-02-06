# =============================================================================
# Multi-stage Dockerfile for Arbitrage Engine
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: Builder
# -----------------------------------------------------------------------------
FROM python:3.11-slim as builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
ENV POETRY_VERSION=1.7.1
ENV POETRY_HOME=/opt/poetry
ENV POETRY_VENV=/opt/poetry-venv
ENV POETRY_CACHE_DIR=/opt/.cache

RUN python -m venv $POETRY_VENV \
    && $POETRY_VENV/bin/pip install -U pip setuptools \
    && $POETRY_VENV/bin/pip install poetry==$POETRY_VERSION

ENV PATH="${POETRY_VENV}/bin:${PATH}"

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml ./

# Install dependencies (no dev)
RUN poetry config virtualenvs.in-project true \
    && poetry install --no-interaction --no-ansi --no-root --only main

# Copy source code
COPY src/ src/

# Install the project
RUN poetry install --no-interaction --no-ansi --only main

# -----------------------------------------------------------------------------
# Stage 2: Runtime
# -----------------------------------------------------------------------------
FROM python:3.11-slim as runtime

# Create non-root user
RUN groupadd --gid 1000 arbitrage \
    && useradd --uid 1000 --gid arbitrage --shell /bin/bash --create-home arbitrage

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PATH="/app/.venv/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

# Copy scripts
COPY scripts/ scripts/

# Change ownership
RUN chown -R arbitrage:arbitrage /app

# Switch to non-root user
USER arbitrage

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import arbitrage; print('healthy')" || exit 1

# Default command
CMD ["python", "-m", "arbitrage"]

# Labels
LABEL org.opencontainers.image.title="Arbitrage Engine" \
      org.opencontainers.image.description="High-Frequency Triangular Arbitrage Bot" \
      org.opencontainers.image.vendor="Tim" \
      org.opencontainers.image.source="https://github.com/tim/arbitrage-engine"
