# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Arctic Text2SQL Agent: A production-grade AI agent that converts natural language to SQL using Snowflake's Arctic-Text2SQL-R1-7B model with a ReAct (Reasoning + Acting) framework for multi-step reasoning and self-correction.

**Current State**: Full agent-based architecture implemented with smolagents integration. Both the core `Text2SQLEngine` and the new `AgentText2SQL` engine are available, with the agent version providing multi-step reasoning, self-correction, and query history for retry functionality.

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

### Directory Structure

```
app/
├── main.py              # FastAPI entry point, lifespan management
├── config.py            # 8 nested Pydantic settings classes
├── routes.py            # API endpoints (integrated with engine)
├── text2sql_engine.py   # Core orchestrator (Issue #4)
├── middleware.py        # CORS, logging, security headers
├── exceptions.py        # Custom exception hierarchy → HTTP status codes
├── error_handlers.py    # Global exception handlers, error response models (Issue #7)
├── retry.py             # Tenacity retry decorators and utilities (Issue #7)
├── resilience.py        # Circuit breaker pattern implementation
├── security/            # JWT auth, rate limiting, input validation
└── agent/               # Agent-based architecture (Issue #18)
    ├── __init__.py      # Module exports
    ├── models.py        # AgentResult, AgentStep, QueryHistoryEntry
    ├── tools.py         # SQL executor, validator, schema inspector tools
    └── engine.py        # AgentText2SQL with ReAct loop

db/
├── connection.py        # DatabaseManager singleton, async pooling
├── schema.py            # Schema introspection (ColumnInfo, TableInfo)
└── executor.py          # QueryValidator, SafeQueryExecutor

models/
├── loader.py            # ModelLoader with lazy loading, quantization
├── inference.py         # InferenceEngine, SQL extraction
└── prompts.py           # Schema-aware prompt templates
```

### Agent-Based Architecture (app/agent/)

The new agent module (Issue #18) provides self-correction capabilities:

```python
from app.agent import get_agent_engine, AgentText2SQL

engine = await get_agent_engine()
result = await engine.generate_sql(
    natural_query="Show all customers from California",
    database_id="my_db",
    execute=True,
    show_reasoning=True,
)
print(result.sql)              # Generated SQL
print(result.confidence)       # Overall confidence (0.0-1.0)
print(result.reasoning_trace)  # Full ReAct reasoning steps
print(result.validation_result)  # Validation outcome
```

**Key Components**:
- `AgentText2SQL`: Main engine with ReAct loop
- `AgentStep`: Individual reasoning step (thought, action, observation)
- `AgentResult`: Complete result with trace and validation
- `QueryHistoryEntry`: Stored queries for retry functionality
- Tools: `sql_executor`, `result_validator`, `schema_inspector`

**ReAct Loop Flow**:
1. **Thought**: Analyze query and determine approach
2. **Action**: Generate SQL using Text2SQL model
3. **Observation**: Execute and inspect results
4. **Validation**: Check if results answer the question
5. **Self-Correction**: If validation fails, iterate with hints

### Text2SQL Engine (app/text2sql_engine.py)

The original orchestrator (still available for simpler use cases):

```python
from app.text2sql_engine import get_text2sql_engine

engine = await get_text2sql_engine()
result = await engine.generate_sql(
    natural_query="Show all customers from California",
    database_id="my_db",
)
```

### Key Patterns

- **Singletons**: `get_database()`, `get_settings()`, `get_model_loader()`, `get_text2sql_engine()`, `get_agent_engine()`
- **Async-First**: All I/O is async; use `AsyncSession` from SQLAlchemy
- **Exception Mapping**: `Text2SQLException` subclasses map to HTTP status codes automatically
- **Rate Limiting**: Slowapi requires first parameter named exactly `request: Request`

### What's Implemented

**Fully Working**:
- Agent-based Text2SQL with ReAct framework (Issue #18)
- Multi-step reasoning with self-correction
- Query history and retry functionality
- Result validation (checks if SQL answers the question)
- Text2SQL Engine with orchestration pipeline
- Query intent classification (SELECT, AGGREGATE, JOIN, SUBQUERY)
- SQL validation (syntax, security, schema alignment)
- Confidence-based retry logic with prompt variation
- FastAPI app with middleware, CORS, security headers
- Database connection pooling (PostgreSQL/MySQL/SQLite)
- Schema introspection
- Model loading with quantization
- JWT authentication, rate limiting
- Global exception handlers with standard error responses (Issue #7)
- Tenacity retry decorators for resilient operations (Issue #7)
- Circuit breaker pattern for fault tolerance (Issue #7)
- Comprehensive test suite (396+ tests)

**API Endpoints**:
- `POST /api/v1/query` - Generate SQL with optional execution
- `POST /api/v1/validate` - Validate SQL syntax and schema
- `GET /api/v1/schema/{database_id}` - Get database schema
- `GET /api/v1/agent/reasoning/{query_id}` - Get reasoning trace
- `POST /api/v1/agent/retry` - Retry with correction hints
- `POST /api/v1/auth/token` - JWT authentication
- `GET /api/v1/health` - Health check

**Partially Implemented**:
- `POST /api/v1/schema/register` - Basic placeholder

## Configuration

Settings loaded via Pydantic from environment variables:

```python
settings = get_settings()
settings.huggingface.token        # HUGGINGFACE_TOKEN
settings.database.url             # DATABASE_URL
settings.api.debug                # API_DEBUG
settings.agent.max_steps          # AGENT_MAX_STEPS (default: 5)
settings.agent.min_confidence     # AGENT_MIN_CONFIDENCE (default: 0.7)
settings.agent.enable_validation  # AGENT_ENABLE_VALIDATION (default: True)
settings.agent.enable_self_correction  # AGENT_ENABLE_SELF_CORRECTION (default: True)
settings.agent.verbosity          # AGENT_VERBOSITY (default: 1)
settings.security.secret_key      # SECRET_KEY
```

**Required env vars**: `HUGGINGFACE_TOKEN`, `DATABASE_URL`

## Testing

```bash
pytest                                     # All tests
pytest tests/unit/test_agent_engine.py -v  # Agent tests
pytest tests/unit/test_agent_tools.py -v   # Agent tools tests
pytest tests/unit/test_agent_models.py -v  # Agent models tests
pytest tests/unit/test_text2sql_engine.py -v  # Core engine tests
pytest -k "test_config" -v                 # By name pattern
pytest --pdb                               # Debug on failure
```

**Fixtures** (in `tests/conftest.py`): `test_settings`, `async_engine`, `db_manager`, `sample_schema`, `test_client`

**Async tests** require `@pytest.mark.asyncio` decorator.

## Code Quality

- **Black**: 88 char lines
- **Ruff**: Rules E, W, F, I, B, C4, UP, ARG, SIM
- **MyPy**: Strict typing required; use `dict[str, Any]` not `Dict`, `str | None` not `Optional[str]`
- **Bandit**: `# nosec B105` must be on the EXACT line with the flagged code

## CI/CD

GitHub Actions (`.github/workflows/ci.yml`):
1. Lint (Black, Ruff, MyPy)
2. Security (Bandit)
3. Tests (pytest + Codecov)
4. Build (package validation)
5. Docker (build only, no push yet)

**Missing**: Docker push, deployment workflow, automated versioning.

### CI Performance Optimizations

The CI uses **`uv`** instead of `pip` for dependency installation, reducing install time from **1h45m+ to ~30 seconds**.

```yaml
# In CI workflow - use uv for fast dependency resolution
- name: Install uv
  run: pip install uv

- name: Install dependencies
  run: uv pip install -r requirements.txt
```

**Why `uv`?**
- Rust-based pip replacement (10-100x faster)
- Better dependency resolution algorithm
- Aggressive caching
- Quickly identifies dependency conflicts (vs pip hanging for hours)

### CI Troubleshooting

#### 1. Dependency Resolution Issues ("pip resolution-too-deep")

**Symptom**: CI hangs for hours on `pip install -r requirements.txt`

**Root Cause**: Complex ML dependencies (torch, transformers, smolagents) create massive dependency trees that pip's backtracking resolver can't handle efficiently.

**Solution**: Use `uv` instead of pip (already configured in CI):
```yaml
- run: |
    pip install uv
    uv pip install -r requirements.txt
```

#### 2. Incompatible Dependencies

**Symptom**: `uv` fails fast with clear error about version conflicts

**Example Error**:
```
smolagents>=1.0.0 requires huggingface-hub>=0.28.0
But requirements.txt has huggingface_hub==0.20.3
```

**Solution**: Update `requirements.txt` with compatible versions:
```txt
# ML & NLP - versions must be compatible with smolagents
transformers>=4.40.0
huggingface_hub>=0.31.2
accelerate>=0.30.0
smolagents>=1.0.0
```

#### 3. Docker Build "No space left on device"

**Symptom**: Docker build fails with disk space error

**Root Cause**: GitHub Actions runners have ~14GB free. PyTorch Docker images need ~10GB+.

**Solution**: Add disk cleanup step before Docker build (already configured):
```yaml
- name: Free up disk space
  run: |
    sudo rm -rf /usr/share/dotnet      # ~2GB
    sudo rm -rf /usr/local/lib/android # ~10GB
    sudo rm -rf /opt/ghc               # ~5GB
    sudo rm -rf /opt/hostedtoolcache/CodeQL  # ~5GB
    sudo docker image prune --all --force
```

#### 4. MyPy Type Errors Across Environments

**Symptom**: MyPy passes locally but fails in CI (or vice versa)

**Root Cause**: Different versions of starlette/pydantic have different type stubs.

**Solution**: Add module-specific overrides in `pyproject.toml`:
```toml
[[tool.mypy.overrides]]
module = "app.error_handlers"
warn_unused_ignores = false

[[tool.mypy.overrides]]
module = "app.retry"
warn_unused_ignores = false
```

### CI Timing Benchmarks

| Job | Time |
|-----|------|
| Security Scan | ~10s |
| Lint & Format | ~18s |
| Tests (396 tests) | ~1m 20s |
| Build Check | ~12s |
| Docker Build | ~25m |
| **Total** | **~27m** |

## Critical Implementation Notes

### Slowapi Rate Limiting Gotcha

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

# CORRECT - nosec on same line as flagged code
if password == "demo":  # nosec B105
```

### Agent Self-Correction

The agent automatically attempts correction when validation fails:

```python
# Validation detects: "Question asks for aggregation but SQL has none"
# Agent will regenerate with hints:
# - "Previous SQL was: SELECT amount FROM orders"
# - "Consider using SUM(), COUNT(), AVG(), etc."
```

## Project Tracking

See GitHub Issues:
- **#17**: Meta tracker with all issues
- **#4**: Core Text2SQL Engine ✅ COMPLETED
- **#18**: smolagents Agent Framework ✅ COMPLETED
- **#7**: Error Handling & Resilience ✅ COMPLETED
- **#12**: CI/CD Pipeline (needs deployment workflow)
