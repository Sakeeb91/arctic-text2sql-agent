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
- Comprehensive test suite (300+ tests)

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
- **#12**: CI/CD Pipeline (needs deployment workflow)
