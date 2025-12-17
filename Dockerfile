# Arctic Text2SQL Agent - Optimized Production Dockerfile
#
# Build Optimizations (Issue #8: Performance):
# - Uses uv instead of pip (10-100x faster dependency resolution)
# - Split requirements for better layer caching
# - BuildKit cache mounts for pip/uv cache
# - Optional CPU-only PyTorch for smaller images (~150MB vs ~1.8GB)
# - Skips development dependencies in production
#
# Build times:
# - First build: ~5-8 minutes (with cache mounts)
# - Subsequent builds (deps unchanged): ~1-2 minutes
# - Subsequent builds (deps changed): ~3-5 minutes
#
# Build options:
#   docker build -t arctic-text2sql .                           # Default (GPU PyTorch)
#   docker build --build-arg TORCH_CPU=true -t arctic-text2sql . # CPU-only (~1.5GB smaller)

# syntax=docker/dockerfile:1.4

# =============================================================================
# Stage 1: Builder - Install dependencies with optimal caching
# =============================================================================
FROM python:3.10-slim AS builder

# Build arguments
ARG TORCH_CPU=false
ARG UV_VERSION=0.5.6

# Environment for build
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=0 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_SYSTEM_PYTHON=1

WORKDIR /build

# Install build dependencies and uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install uv==${UV_VERSION}

# Copy requirements files (split for better caching)
COPY requirements-base.txt requirements-ml.txt ./

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Layer 1: Install base dependencies (rarely change)
# Using BuildKit cache mount for faster rebuilds
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,target=/root/.cache/pip \
    uv pip install -r requirements-base.txt

# Layer 2: Install ML dependencies (largest, rarely change)
# Optional: Use CPU-only PyTorch for smaller image
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,target=/root/.cache/pip \
    if [ "$TORCH_CPU" = "true" ]; then \
        echo "Installing CPU-only PyTorch..." && \
        uv pip install torch --index-url https://download.pytorch.org/whl/cpu && \
        uv pip install -r requirements-ml.txt --no-deps transformers accelerate huggingface_hub bitsandbytes smolagents numpy; \
    else \
        echo "Installing full PyTorch (with CUDA support)..." && \
        uv pip install -r requirements-ml.txt; \
    fi

# Layer 3: Install async database drivers
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install aiosqlite asyncpg aiomysql

# =============================================================================
# Stage 2: Production - Minimal runtime image
# =============================================================================
FROM python:3.10-slim AS production

# Environment for runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    LOG_LEVEL=INFO \
    LOG_FORMAT=json

WORKDIR /app

# Install only runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copy application code
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser db/ ./db/
COPY --chown=appuser:appuser models/ ./models/

# Create data directory with proper permissions
RUN mkdir -p /app/data && chown -R appuser:appuser /app/data

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:${API_PORT}/api/v1/health').raise_for_status()"

# Expose port
EXPOSE ${API_PORT}

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# =============================================================================
# Stage 3: Development - Includes dev tools
# =============================================================================
FROM production AS development

USER root

# Copy dev requirements
COPY requirements-dev.txt /tmp/

# Install development dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,target=/root/.cache/pip \
    pip install uv && \
    uv pip install -r /tmp/requirements-dev.txt

# Copy test files for development
COPY --chown=appuser:appuser tests/ ./tests/

# Switch back to non-root user
USER appuser

# Override command for development with hot reload
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
