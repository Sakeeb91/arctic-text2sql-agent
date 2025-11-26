# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Arctic Text2SQL Agent: A production-grade AI agent that converts natural language to SQL using Snowflake's Arctic-Text2SQL-R1-7B model with a ReAct (Reasoning + Acting) framework for multi-step reasoning and self-correction.

**Key Innovation**: Unlike single-shot text-to-SQL pipelines, this uses an agent-based approach achieving 50-70% higher accuracy on complex queries through iterative reasoning, validation, and self-correction.

## Commands

### Development
```bash
# Setup environment
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Run development server (with auto-reload)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run single test
pytest tests/unit/test_config.py::TestSettings::test_default_values -v

# Run specific test category
pytest -m unit          # Unit tests only
pytest -m integration   # Integration tests only
pytest -m "not slow"    # Skip slow tests
```

### Testing & Quality
```bash
# Run all tests with coverage
pytest --cov=app --cov=db --cov=models --cov-report=term-missing

# Format and lint
black . && ruff check . --fix && mypy app/ db/ models/

# Security scan
bandit -c pyproject.toml -r app/ db/ models/

# Install pre-commit hooks
pre-commit install && pre-commit run --all-files
```

### Docker
```bash
# Full stack (API + PostgreSQL + Redis + Prometheus + Grafana)
docker-compose up -d

# API only
docker-compose up api -d

# View logs
docker-compose logs -f api

# Cleanup
docker-compose down -v
```

### Database Migrations
```bash
# Create migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

## Architecture

### Core Components

1. **app/** - FastAPI application
   - `main.py`: Application entry point with lifespan management (startup: load model/db, shutdown: cleanup)
   - `config.py`: 8 nested Pydantic settings models (HuggingFace, Database, API, Agent, Security, Logging, Monitoring, Cache)
   - `routes.py`: REST API endpoints with Pydantic request/response models
   - `middleware.py`: Request logging, CORS, error handling, security headers
   - `security/`: JWT auth, rate limiting (slowapi), input validation, SQL injection prevention

2. **db/** - Database layer (fully async)
   - `connection.py`: DatabaseManager singleton with async connection pooling (PostgreSQL/MySQL/SQLite)
   - `schema.py`: Schema introspection (ColumnInfo, TableInfo, ForeignKeyInfo dataclasses)
   - `executor.py`: Safe SQL execution with QueryValidator, parameterized queries, retry logic

3. **models/** - ML model integration
   - `loader.py`: ModelLoader with lazy loading, device auto-detection (cuda/mps/cpu), 8-bit/4-bit quantization
   - `inference.py`: InferenceEngine with GenerationConfig, SQL extraction from model output
   - `prompts.py`: Schema-aware prompt templates for SQL generation

4. **tests/** - Comprehensive test suite
   - `conftest.py`: Shared pytest fixtures (test_settings, async_engine, db_manager, test_client)
   - `unit/`: 8 test files covering all modules
   - `integration/`: End-to-end API and database tests

### Key Design Patterns

- **Singleton**: `get_database()`, `get_settings()`, `get_model_loader()` with LRU caching
- **Async-First**: All I/O operations are non-blocking, AsyncSession throughout
- **Dependency Injection**: FastAPI Depends for auth, database sessions, settings
- **Exception Hierarchy**: Custom `Text2SQLException` base with HTTP status mapping
- **DataClasses**: Pydantic models for validation, standard dataclasses for internal data

### Configuration Management

Settings are loaded from environment variables using Pydantic with validation:

```python
# app/config.py structure
Settings
├── HuggingFaceSettings     # Model config (HUGGINGFACE_TOKEN, TEXT2SQL_MODEL, etc.)
├── DatabaseSettings        # DB connection (DATABASE_URL, pool config)
├── APISettings            # Server config (host, port, CORS, rate limits)
├── AgentSettings          # Agent behavior (max_steps=5, min_confidence=0.7)
├── SecuritySettings       # Auth (SECRET_KEY, JWT config)
├── LoggingSettings        # Logging (level, format, requests)
├── MonitoringSettings     # Metrics (Prometheus)
└── CacheSettings          # Caching (Redis URL, TTL)
```

Access via: `settings = get_settings()`

### Database Layer

**Multi-Database Support**: Automatically detects dialect from DATABASE_URL:
- PostgreSQL: `asyncpg` driver with connection pooling
- MySQL: `aiomysql` driver with connection pooling
- SQLite: `aiosqlite` driver with StaticPool (special handling)

**Connection Pooling Config**:
- `pool_size=5`: Initial connections
- `max_overflow=10`: Additional connections when needed
- `pool_timeout=30`: Wait time for connection

**Schema Introspection**: Extracts table/column metadata including foreign keys for prompt context.

### Model Integration

**Loading Strategy**:
1. Lazy load on first inference request
2. Device auto-detection: cuda → mps → cpu
3. Optional 8-bit/4-bit quantization (50% memory reduction)
4. Warmup with sample input to prepare GPU
5. Singleton instance cached globally

**Quantization Options**:
- `ENABLE_8BIT_QUANTIZATION=true`: 8-bit quantization (bitsandbytes)
- `ENABLE_4BIT_QUANTIZATION=true`: 4-bit quantization (more aggressive)
- Neither: Full precision (requires ~14GB GPU memory)

### Security Implementation (Phase 2.2)

**Authentication**:
- JWT tokens: `POST /api/v1/auth/token` → returns `access_token`
- API keys: Via `X-API-Key` header
- Bearer tokens: Via `Authorization: Bearer {token}` header

**Rate Limiting**:
- Per-endpoint limits (slowapi)
- Default: 60 requests/minute per IP
- Burst allowance: 10 requests
- Tracked by IP, API key, or JWT token hash

**Input Validation**:
- Pydantic request validation (types, length, format)
- SQL injection pattern detection (DROP, DELETE, UNION, etc.)
- Natural language query validation (length, suspicious patterns)
- Database ID format validation (alphanumeric + underscore/hyphen only)

**SQL Injection Prevention**:
- Parameterized queries with SQLAlchemy
- Pattern matching for dangerous keywords
- Query whitelisting for production (SELECT-only mode)
- Timing attack detection (SLEEP, BENCHMARK, WAITFOR)

**Security Headers**:
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- Content-Security-Policy: restrictive for API
- Referrer-Policy: strict-origin-when-cross-origin
- Permissions-Policy: disables unnecessary features

## Testing Strategy

### Test Structure

**Unit Tests** (`tests/unit/`): Test individual components in isolation
- Mock external dependencies (database, model)
- Fast execution (<1s per test)
- Use `@pytest.mark.asyncio` for async functions

**Integration Tests** (`tests/integration/`): Test component interactions
- Use real database (in-memory SQLite)
- Test full request/response cycles
- Slower but more comprehensive

### Key Fixtures (conftest.py)

```python
test_settings        # Mock Settings object with test values
async_engine         # In-memory SQLite async engine
db_session          # Async database session
db_manager          # DatabaseManager instance
sample_schema       # Pre-populated test schema
test_client         # FastAPI TestClient for API tests
```

### Running Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=app --cov=db --cov=models --cov-report=html

# Specific markers
pytest -m unit                    # Unit tests only
pytest -m integration             # Integration tests only
pytest -m "not slow"              # Skip slow tests

# Single test
pytest tests/unit/test_config.py::TestSettings::test_default_values -v

# With debugging
pytest --pdb                      # Drop into debugger on failure
pytest -vv                        # Very verbose output
```

### Writing Tests

**Pattern for Async Tests**:
```python
@pytest.mark.asyncio
async def test_database_operation(db_manager):
    result = await db_manager.execute_query("SELECT 1")
    assert result.success
```

**Pattern for API Tests**:
```python
def test_query_endpoint(test_client):
    response = test_client.post("/api/v1/query", json={
        "query": "Show all users",
        "database_id": "test_db"
    })
    assert response.status_code == 200
```

## CI/CD Pipeline

**Workflow** (`.github/workflows/ci.yml`):
1. **Lint & Format**: Black, Ruff, MyPy (runs first)
2. **Security Scan**: Bandit (parallel with tests)
3. **Tests**: pytest with coverage upload to Codecov (depends on Lint)
4. **Build Check**: Python package validation (depends on Tests)
5. **Docker Build**: Multi-stage image build with caching (depends on Tests)

**All checks must pass** before merging to main.

## Code Quality Standards

### Formatting & Linting

- **Black**: 88 character line length, auto-formatting
- **Ruff**: Fast linting with auto-fix (E, W, F, I, B, C4, UP, ARG, SIM rules)
- **MyPy**: Strict type checking (`disallow_untyped_defs=true`)
- **Pre-commit**: Hooks run automatically on commit

### Type Hints

**Required** for all functions:
```python
def process_query(query: str, database_id: str) -> QueryResult:
    ...

async def fetch_schema(db_id: str) -> SchemaInfo:
    ...
```

**Common patterns**:
- Use `dict[str, Any]` not `Dict[str, Any]` (PEP 585)
- Use `list[str]` not `List[str]`
- Use `str | None` not `Optional[str]` (PEP 604)
- Always annotate return types, even for `None`

### Logging

Use structured logging with contextual fields:

```python
from app.logging_config import get_logger

logger = get_logger(__name__)

# Info logging
logger.info("query_executed",
    database_id=db_id,
    execution_time_ms=elapsed,
    row_count=len(results)
)

# Error logging
logger.error("query_failed",
    error=str(e),
    error_type=type(e).__name__,
    database_id=db_id
)
```

**Log levels**:
- `DEBUG`: Detailed diagnostic info
- `INFO`: Normal operations (query execution, model loading)
- `WARNING`: Recoverable errors (model load skip, validation warnings)
- `ERROR`: Errors requiring attention (database connection failure)
- `CRITICAL`: System-level failures (app cannot start)

### Exception Handling

Use custom exceptions from `app.exceptions`:

```python
from app.exceptions import (
    DatabaseConnectionException,
    QueryExecutionException,
    ModelInferenceException
)

# Raise with context
raise QueryExecutionException(
    message="Query timed out",
    details={"timeout_seconds": 30, "query": sql}
)
```

All custom exceptions map to HTTP status codes automatically.

## Security Implementation Guide

### Critical Linting Issues and Solutions

When implementing security features, you will encounter several CI/CD linting issues. Here's how to resolve them:

#### 1. Bandit Security Scanner (B105, B106)

**Issue**: Bandit flags hardcoded passwords/secrets even in demo code.

**Solution**: Use `# nosec B105` or `# nosec B106` comments **on the exact line** containing the flagged code:

```python
# WRONG - Comment not on same line as flagged code
if credentials.password == "demo_password":
    # nosec B105

# CORRECT - Comment on same line
if credentials.password == "demo_password":  # nosec B105

# CORRECT - Multi-line handling
if (
    credentials.username == "demo"
    and credentials.password == "demo_password"  # nosec B105
):
```

**Important**: The `# nosec` comment must be on the line containing the password string, not on a closing parenthesis or separate line.

#### 2. Black Formatting

**Issue**: Black reformats code, potentially moving `# nosec` comments to wrong lines.

**Solution**: Run Black after adding nosec comments, then verify placement:

```bash
black app/routes.py
# Check if nosec comment is still on correct line
grep -n "nosec" app/routes.py
```

#### 3. Ruff Linting (E402: Module Import Not at Top)

**Issue**: Slowapi requires importing `setup_rate_limiting` in `main.py`, but Ruff wants all imports at top.

**Solution**: Move the import to the top of the file with other imports:

```python
# WRONG - Import in middle of file after setup_middleware()
setup_middleware(app)
from app.security.rate_limiting import setup_rate_limiting
setup_rate_limiting(app)

# CORRECT - Import at top with other imports
from app.security.rate_limiting import setup_rate_limiting
...
setup_middleware(app)
setup_rate_limiting(app)
```

#### 4. MyPy Type Checking

**Issue**: Functions returning `Any` from third-party libraries (jose.jwt, slowapi).

**Solution**: Add explicit type annotations:

```python
# WRONG - Implicit Any return type
encoded_jwt = jwt.encode(data, key, algorithm)
return encoded_jwt

# CORRECT - Explicit type annotation
encoded_jwt: str = jwt.encode(data, key, algorithm)
return encoded_jwt

# WRONG - Dict with nested types
def handler() -> dict[str, str]:
    return {
        "error": {
            "code": "ERROR",
            "details": {"retry_after": value}  # Nested dict causes type error
        }
    }

# CORRECT - Use dict[str, Any] for nested structures
def handler() -> dict[str, Any]:
    return {
        "error": {
            "code": "ERROR",
            "details": {"retry_after": value}
        }
    }
```

**Required type annotations**:
```python
from typing import Any

# JWT operations
encoded_jwt: str = jwt.encode(...)
payload: dict[str, Any] = jwt.decode(...)

# Slowapi operations
ip_address: str = get_remote_address(request)
retry_after: str | None = exc.retry_after if hasattr(exc, "retry_after") else None
```

#### 5. Slowapi Rate Limiting

**Issue**: Slowapi decorators require the first parameter to be named exactly `request`.

**Solution**: Use `request: Request` not `http_request: Request`:

```python
# WRONG - Slowapi won't find request parameter
@router.post("/query")
@limiter.limit("10/minute")
async def generate_sql(http_request: Request, query: QueryRequest):
    pass

# CORRECT - First parameter named "request"
@router.post("/query")
@limiter.limit("10/minute")
async def generate_sql(request: Request, query_request: QueryRequest):
    pass
```

**Note**: Rename other parameters to avoid conflicts (e.g., `query_request` instead of `request` for Pydantic models).

### Testing Security Features

Create comprehensive tests in `tests/unit/test_security.py`:

```python
class TestJWTAuthentication:
    def test_create_access_token(self):
        """Test JWT token creation."""
        token = create_access_token(data={"sub": "test_user"})
        assert token is not None
        assert isinstance(token, str)

class TestInputValidation:
    def test_validate_database_id_valid(self):
        """Test database ID validation with valid IDs."""
        is_valid, error = validate_database_id("my_database")
        assert is_valid is True
        assert error is None

class TestSQLInjectionDetection:
    def test_scan_drop_table_injection(self):
        """Test detection of DROP TABLE injection."""
        sql = "SELECT * FROM users; DROP TABLE users;"
        warnings = scan_for_injection_patterns(sql)
        assert len(warnings) > 0
        assert any("DROP" in w for w in warnings)
```

**Test coverage requirements**:
- All authentication functions (JWT, API key)
- All input validation functions
- All SQL injection patterns
- All rate limiting configurations

### CI/CD Workflow for Security Implementation

**Typical commit sequence** (based on successful Phase 2.2 implementation):

1. Add dependencies → `feat(security): add security dependencies`
2. Implement auth → `feat(security): implement JWT and API key authentication`
3. Implement rate limiting → `feat(security): implement request rate limiting`
4. Implement validation → `feat(security): implement SQL injection prevention and input validation`
5. Add headers → `feat(security): add security headers middleware`
6. Create package → `feat(security): create security module package`
7. Integrate middleware → `feat(security): integrate security headers into middleware`
8. Integrate main app → `feat(security): integrate rate limiting into application`
9. Update routes → `feat(security): add input validation to all API endpoints`
10. Update config → `feat(security): update environment configuration with security settings`
11. Add tests → `test(security): add comprehensive security test suite`
12. Fix formatting → `style(security): fix Black formatting and Bandit warnings`
13. Fix linting → `fix(lint): resolve Ruff and Bandit linting issues`
14. Fix types → `fix(types): add type annotations for MyPy compliance`
15. Final fixes → `fix(security): correct nosec comment placement for Bandit`

**Each commit should be atomic** - one logical change per commit. Use conventional commit messages.

### Common Pitfalls

1. **Circular imports**: Import security middleware inside functions, not at module level
2. **Nosec placement**: Must be on exact line with flagged code, not on closing brackets
3. **Parameter naming**: Slowapi requires `request: Request` as first parameter name
4. **Type annotations**: Add explicit types for all JWT/slowapi return values
5. **Black formatting**: Always run Black last, then verify nosec comment placement

## Common Development Tasks

### Adding a New API Endpoint

1. Define Pydantic models in `app/routes.py`:
```python
class NewRequest(BaseModel):
    field: str = Field(..., description="Field description")

class NewResponse(BaseModel):
    result: str = Field(..., description="Result description")
```

2. Add endpoint with security decorators:
```python
@router.post("/new-endpoint", response_model=NewResponse)
@limiter.limit("10/minute")
async def new_endpoint(
    request: Request,
    req_data: NewRequest,
    current_user: dict = Depends(get_current_user)  # If auth required
) -> NewResponse:
    """Endpoint description."""
    # Implementation
    return NewResponse(result="...")
```

3. Add tests in `tests/unit/test_api.py` or `tests/integration/test_api.py`

4. Run tests and linting before committing

### Adding a New Database Table

1. Create migration:
```bash
alembic revision --autogenerate -m "Add new_table"
```

2. Review generated migration in `db/migrations/versions/`

3. Apply migration:
```bash
alembic upgrade head
```

4. Update `db/schema.py` if schema introspection needs changes

5. Add tests for new table operations

### Modifying Model Inference

1. Update prompt templates in `models/prompts.py`
2. Modify `InferenceEngine` in `models/inference.py` if needed
3. Update `GenerationConfig` for new parameters
4. Add tests in `tests/unit/test_inference.py`
5. Test with real model: `pytest tests/integration/ -v`

## Debugging

### Common Issues

**Database Connection Failures**:
- Check `DATABASE_URL` format: `postgresql://user:pass@host:port/dbname`
- Verify database is running: `docker-compose ps`
- Check logs: `docker-compose logs db`
- Test connection: `curl http://localhost:8000/api/v1/health`

**Model Loading Failures**:
- Verify `HUGGINGFACE_TOKEN` is set correctly
- Check device availability: `python -c "import torch; print(torch.cuda.is_available())"`
- Try CPU mode: `MODEL_DEVICE=cpu`
- Enable quantization for memory: `ENABLE_8BIT_QUANTIZATION=true`

**API Errors**:
- Check structured logs: `docker-compose logs api | grep error`
- Use request IDs: `X-Request-ID` header in response
- Test with curl:
```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Show all users", "database_id": "test"}'
```

### Logging and Monitoring

**View structured logs**:
```bash
# JSON format (production)
docker-compose logs -f api

# Console format (development)
LOG_FORMAT=console uvicorn app.main:app --reload
```

**Health check endpoint**:
```bash
curl http://localhost:8000/api/v1/health
```

Returns status of API, database, and model.

**Prometheus metrics** (if enabled):
```bash
curl http://localhost:9090/metrics
```

## Important Notes

### Environment Variables

**Required**:
- `HUGGINGFACE_TOKEN`: For model access (get from https://huggingface.co/settings/tokens)
- `DATABASE_URL`: Database connection string

**Optional but recommended**:
- `SECRET_KEY`: Generate with `openssl rand -hex 32`
- `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`: Token lifetime (default 30)
- `API_DEBUG`: Enable debug mode (never in production)

### Performance Optimization

**For faster inference**:
1. Use GPU: `MODEL_DEVICE=cuda`
2. Enable 8-bit quantization: `ENABLE_8BIT_QUANTIZATION=true`
3. Reduce max steps: `AGENT_MAX_STEPS=3`
4. Enable Redis caching: `REDIS_URL=redis://localhost:6379`

**For lower memory usage**:
1. Enable 4-bit quantization: `ENABLE_4BIT_QUANTIZATION=true`
2. Reduce database pool: `DB_POOL_SIZE=3`
3. Disable model loading: Don't set `HUGGINGFACE_TOKEN` (API still works, just no inference)

### Production Checklist

- [ ] Change `SECRET_KEY` from default
- [ ] Use PostgreSQL or MySQL (not SQLite)
- [ ] Enable `AGENT_ENABLE_VALIDATION=true`
- [ ] Set `API_DEBUG=false`
- [ ] Configure proper `CORS_ORIGINS`
- [ ] Enable HTTPS and uncomment HSTS header in `app/security/headers.py`
- [ ] Set up Prometheus/Grafana for monitoring
- [ ] Configure Redis for caching
- [ ] Use environment-specific `.env` files
- [ ] Set up database backups
- [ ] Configure log aggregation (ELK, CloudWatch, etc.)

## Project Status

**Current Phase**: 1.5 - Agent Framework Architecture (CRITICAL)
**Version**: 0.1.0 (Alpha)
**Test Coverage**: 30% (target for alpha)

**Completed**:
- Core API with FastAPI ✅
- Database layer with async support ✅
- Model loading and inference ✅
- Security implementation (Phase 2.2) ✅
- Comprehensive test suite ✅
- CI/CD pipeline ✅
- Docker containerization ✅

**In Progress**:
- Agent framework (ReAct loop implementation)
- Output validation and semantic checking
- Performance optimization
