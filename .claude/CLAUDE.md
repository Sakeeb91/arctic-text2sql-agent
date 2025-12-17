# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Arctic Text2SQL Agent: A production-grade AI agent that converts natural language to SQL using Snowflake's Arctic-Text2SQL-R1-7B model with a ReAct (Reasoning + Acting) framework for multi-step reasoning and self-correction.

## Commands

```bash
# Development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run all tests with coverage
pytest --cov=app --cov=db --cov=models --cov-report=term-missing

# Run single test
pytest tests/unit/test_config.py::TestSettings::test_default_values -v

# Format and lint (run before committing)
black . && ruff check . --fix && mypy app/ db/ models/

# Security scan
bandit -c pyproject.toml -r app/ db/ models/

# Docker full stack
docker-compose up -d

# Database migrations
alembic revision --autogenerate -m "description"
alembic upgrade head
```

## Architecture

```
app/              # FastAPI application
├── main.py       # Entry point, lifespan management
├── config.py     # Pydantic settings (8 nested classes)
├── routes.py     # API endpoints
├── exceptions.py # Custom exception hierarchy → HTTP status codes
├── error_handlers.py  # Global exception handlers
├── retry.py      # Tenacity retry decorators
├── resilience.py # Circuit breaker pattern
├── security/     # JWT auth, rate limiting, input validation
└── agent/        # ReAct agent with self-correction
    ├── engine.py # AgentText2SQL main class
    ├── tools.py  # sql_executor, result_validator, schema_inspector
    └── models.py # AgentResult, AgentStep, QueryHistoryEntry

db/               # Database layer
├── connection.py # DatabaseManager singleton, async pooling
├── schema.py     # Schema introspection
└── executor.py   # QueryValidator, SafeQueryExecutor

models/           # ML model layer
├── loader.py     # ModelLoader with lazy loading, quantization
├── inference.py  # InferenceEngine, SQL extraction
└── prompts.py    # Schema-aware prompt templates
```

### Key Patterns

- **Singletons**: `get_database()`, `get_settings()`, `get_model_loader()`, `get_text2sql_engine()`, `get_agent_engine()`
- **Async-First**: All I/O is async; use `AsyncSession` from SQLAlchemy
- **Exception Mapping**: `Text2SQLException` subclasses map to HTTP status codes automatically via global handlers

### Agent Usage

```python
from app.agent import get_agent_engine

engine = await get_agent_engine()
result = await engine.generate_sql(
    natural_query="Show all customers from California",
    database_id="my_db",
    execute=True,
    show_reasoning=True,
)
# result.sql, result.confidence, result.reasoning_trace, result.validation_result
```

### API Endpoints

- `POST /api/v1/query` - Generate SQL with optional execution
- `POST /api/v1/validate` - Validate SQL syntax and schema
- `GET /api/v1/schema/{database_id}` - Get database schema
- `GET /api/v1/agent/reasoning/{query_id}` - Get reasoning trace
- `POST /api/v1/agent/retry` - Retry with correction hints
- `POST /api/v1/auth/token` - JWT authentication
- `GET /api/v1/health` - Health check

## Configuration

Settings loaded via Pydantic from environment variables:

```python
settings = get_settings()
settings.huggingface.token        # HUGGINGFACE_TOKEN
settings.database.url             # DATABASE_URL
settings.api.debug                # API_DEBUG
settings.agent.max_steps          # AGENT_MAX_STEPS (default: 5)
settings.agent.min_confidence     # AGENT_MIN_CONFIDENCE (default: 0.7)
settings.security.secret_key      # SECRET_KEY
```

**Required env vars**: `HUGGINGFACE_TOKEN`, `DATABASE_URL`

## Testing

```bash
pytest                                     # All tests
pytest tests/unit/test_agent_engine.py -v  # Agent tests
pytest -k "test_config" -v                 # By name pattern
pytest --pdb                               # Debug on failure
```

**Fixtures** (in `tests/conftest.py`): `test_settings`, `async_engine`, `db_manager`, `sample_schema`, `test_client`

**Async tests** require `@pytest.mark.asyncio` decorator.

## Code Quality

- **Black**: 88 char lines
- **Ruff**: Rules E, W, F, I, B, C4, UP, ARG, SIM
- **MyPy**: Strict typing; use `dict[str, Any]` not `Dict`, `str | None` not `Optional[str]`
- **Bandit**: `# nosec B105` must be on the EXACT line with the flagged code

## CI/CD

GitHub Actions workflows in `.github/workflows/`:

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `ci.yml` | Push/PR | Lint → Security → Tests → Build → Docker |
| `release.yml` | Tag `v*.*.*` | Build, push to GHCR, create GitHub release |
| `deploy-staging.yml` | Push to `develop` | Deploy to staging environment |
| `deploy-production.yml` | Release published | Deploy to production (with approval) |
| `rollback.yml` | Manual | Rollback to previous version |
| `version-bump.yml` | Manual | Bump version and create tag |

### CI Notes

- Uses **`uv`** instead of pip (10-100x faster dependency resolution)
- Set `UV_SYSTEM_PYTHON=1` environment variable for system Python installation
- Docker build requires disk cleanup step (removes .NET SDK, Android SDK, GHC, CodeQL to free ~30GB)
- Docker images pushed to GitHub Container Registry (`ghcr.io`)

### CI Timing

| Job | Time (Cold) | Time (Cached) |
|-----|-------------|---------------|
| Security Scan | ~10s | ~10s |
| Lint & Format | ~18s | ~18s |
| Tests | ~1m 20s | ~1m 20s |
| Build Check | ~12s | ~12s |
| Docker Build | ~17m | ~3-5m |

### Docker Build Optimization

The Docker build has been optimized to reduce build times from ~25min to ~3-5min (cached):

**Split Requirements Files:**
- `requirements-base.txt` - API, database, utilities (rarely change)
- `requirements-ml.txt` - PyTorch, transformers (~2GB, rarely change)
- `requirements-dev.txt` - Testing, linting (excluded from production)

**Build Optimizations:**
- **uv package manager**: 10-100x faster than pip for dependency resolution
- **BuildKit cache mounts**: Persist pip/uv cache across builds
- **Layer caching**: Dependencies split into separate layers for optimal caching
- **GitHub Actions cache**: `cache-from: type=gha` for CI layer caching

**Build Options:**
```bash
# Default (with CUDA support) - ~1.8GB PyTorch
docker build -t arctic-text2sql .

# CPU-only (~150MB PyTorch) - saves ~1.5GB
docker build --build-arg TORCH_CPU=true -t arctic-text2sql .

# Use production target
docker build --target production -t arctic-text2sql .

# Use development target (includes test tools)
docker build --target development -t arctic-text2sql .
```

**Build Time Breakdown:**
| Layer | First Build | Cached |
|-------|-------------|--------|
| Base dependencies | ~2-3m | <10s |
| ML dependencies | ~8-12m | <10s |
| Async drivers | ~30s | <10s |
| App code | ~10s | ~10s |

## Deployment

### Docker Images

Images are published to GitHub Container Registry:

```bash
# Pull latest
docker pull ghcr.io/sakeeb91/arctic-text2sql-agent:latest

# Pull specific version
docker pull ghcr.io/sakeeb91/arctic-text2sql-agent:1.0.0

# Pull by commit SHA
docker pull ghcr.io/sakeeb91/arctic-text2sql-agent:sha-abc1234
```

### Environment Deployment

```bash
# Staging
docker-compose -f docker-compose.yml -f docker-compose.staging.yml up -d

# Production
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Release Process

1. **Version Bump**: Run `version-bump.yml` workflow (patch/minor/major)
2. **Auto-Release**: Tag push triggers `release.yml` → builds image → creates GitHub release
3. **Production Deploy**: Release publish triggers `deploy-production.yml` (requires approval)

### Rollback

Use the `rollback.yml` workflow:
- Select environment (staging/production)
- Specify target version (e.g., `v1.0.0` or `sha-abc1234`)
- Provide reason for rollback
- Production rollbacks require approval

### Required Secrets

| Secret | Description |
|--------|-------------|
| `GITHUB_TOKEN` | Auto-provided, used for GHCR push |
| `DATABASE_URL` | Production database connection |
| `HUGGINGFACE_TOKEN` | Model download access |
| `SECRET_KEY` | JWT signing key |

### GitHub Environments

Configure these environments in repository settings:
- `staging` - Auto-deploy from develop branch
- `production` - Manual approval required
- `production-approval` - Approval gate for production deploys

## Critical Implementation Notes

### Slowapi Rate Limiting

First parameter MUST be named `request`:

```python
# WRONG
async def endpoint(http_request: Request, data: Model): ...

# CORRECT
async def endpoint(request: Request, data: Model): ...
```

### Bandit Nosec Placement

```python
# WRONG - nosec on wrong line
if password == "demo":
    # nosec B105

# CORRECT - nosec on same line
if password == "demo":  # nosec B105
```

### Dependency Compatibility

ML dependencies must be compatible with smolagents:
```txt
transformers>=4.40.0
huggingface_hub>=0.31.2
accelerate>=0.30.0
smolagents>=1.0.0
```

If `uv` fails with version conflicts, update these versions in `requirements.txt`.
