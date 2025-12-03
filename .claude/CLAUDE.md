# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Arctic Text2SQL Agent: A production-grade AI agent that converts natural language to SQL using Snowflake's Arctic-Text2SQL-R1-7B model with a ReAct (Reasoning + Acting) framework for multi-step reasoning and self-correction.

**Current State**: Core orchestration layer (`Text2SQLEngine`) is implemented with query intent classification, SQL validation, confidence-based retry logic, and schema alignment checking. The engine is integrated with API routes.

**Next Critical Piece**: Issue #18 (smolagents agent framework) for full ReAct loop implementation with self-correction capabilities.

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
├── text2sql_engine.py   # Core orchestrator (NEW - Issue #4)
├── middleware.py        # CORS, logging, security headers
├── exceptions.py        # Custom exception hierarchy → HTTP status codes
└── security/            # JWT auth, rate limiting, input validation

db/
├── connection.py        # DatabaseManager singleton, async pooling
├── schema.py            # Schema introspection (ColumnInfo, TableInfo)
└── executor.py          # QueryValidator, SafeQueryExecutor

models/
├── loader.py            # ModelLoader with lazy loading, quantization
├── inference.py         # InferenceEngine, SQL extraction
└── prompts.py           # Schema-aware prompt templates
```

### Text2SQL Engine (app/text2sql_engine.py)

The central orchestrator that coordinates all SQL generation:

```python
from app.text2sql_engine import get_text2sql_engine, Text2SQLEngine

engine = await get_text2sql_engine()
result = await engine.generate_sql(
    natural_query="Show all customers from California",
    database_id="my_db",
    execute=False,
    show_reasoning=True,
)
print(result.sql)           # Generated SQL
print(result.confidence)    # Model confidence (0.0-1.0)
print(result.valid_syntax)  # Validation result
print(result.intent)        # QueryIntent enum (SELECT, AGGREGATE, JOIN, SUBQUERY)
```

**Key Components**:
- `QueryIntent` enum: Classifies queries (SELECT, AGGREGATE, JOIN, SUBQUERY, UNKNOWN)
- `SQLValidator`: Syntax checks, injection detection, schema alignment
- `SchemaContext`: Database schema formatted for prompts
- `SQLResult`: Complete result with metadata, warnings, reasoning trace

### Key Patterns

- **Singletons**: `get_database()`, `get_settings()`, `get_model_loader()`, `get_text2sql_engine()` use `@lru_cache` or global instance
- **Async-First**: All I/O is async; use `AsyncSession` from SQLAlchemy
- **Exception Mapping**: `Text2SQLException` subclasses map to HTTP status codes automatically
- **Rate Limiting**: Slowapi requires first parameter named exactly `request: Request`

### What's Implemented

**Fully Working**:
- Text2SQL Engine with orchestration pipeline
- Query intent classification (SELECT, AGGREGATE, JOIN, SUBQUERY)
- SQL validation (syntax, security, schema alignment)
- Confidence-based retry logic with prompt variation
- FastAPI app with middleware, CORS, security headers
- Database connection pooling (PostgreSQL/MySQL/SQLite)
- Schema introspection
- Model loading with quantization
- JWT authentication, rate limiting
- Comprehensive test suite (277 tests)

**Partially Implemented**:
- `POST /api/v1/schema/register` - Basic placeholder
- `GET /api/v1/agent/reasoning/{query_id}` - Needs storage backend
- `POST /api/v1/agent/retry` - Returns 501 (needs query history storage)

**Planned for Issue #18**:
- Full smolagents ReAct loop
- Multi-step reasoning with self-correction
- Tool-based SQL execution and validation

## Configuration

Settings loaded via Pydantic from environment variables:

```python
settings = get_settings()
settings.huggingface.token      # HUGGINGFACE_TOKEN
settings.database.url           # DATABASE_URL
settings.api.debug              # API_DEBUG
settings.agent.max_steps        # AGENT_MAX_STEPS (default: 5)
settings.agent.min_confidence   # AGENT_MIN_CONFIDENCE (default: 0.7)
settings.security.secret_key    # SECRET_KEY
```

**Required env vars**: `HUGGINGFACE_TOKEN`, `DATABASE_URL`

## Testing

```bash
pytest                                    # All tests
pytest tests/unit/test_text2sql_engine.py -v  # Engine tests
pytest tests/unit/test_inference.py -v   # Single file
pytest -k "test_config" -v               # By name pattern
pytest --pdb                             # Debug on failure
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

## Project Tracking

See GitHub Issues:
- **#17**: Meta tracker with all issues
- **#4**: Core Text2SQL Engine ✅ COMPLETED
- **#18**: smolagents Agent Framework (CRITICAL - next priority)
- **#12**: CI/CD Pipeline (needs deployment workflow)
