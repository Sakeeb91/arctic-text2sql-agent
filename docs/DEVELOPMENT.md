# Development Guide

## Setup

```bash
# Clone
git clone https://github.com/Sakeeb91/text2sql-agent.git
cd text2sql-agent

# Virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Or with constraints (recommended for CI)
bash scripts/install_with_constraints.sh
```

## Running Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=app --cov=db --cov=models --cov-report=term-missing

# Specific test file
pytest tests/unit/test_agent_engine.py -v

# By name pattern
pytest -k "test_config" -v

# Debug on failure
pytest --pdb
```

## Code Quality

```bash
# Format
black app/ db/ models/ tests/

# Lint
ruff check app/ db/ models/ tests/ --fix

# Type check
mypy app/ db/ models/

# Security scan
bandit -c pyproject.toml -r app/ db/ models/

# All checks
black . && ruff check . --fix && mypy app/ db/ models/
```

## Pre-commit Hooks

```bash
# Install
pre-commit install

# Run on all files
pre-commit run --all-files
```

## Project Structure

```
text2sql-agent/
├── app/                    # FastAPI application
│   ├── main.py            # Entry point
│   ├── config.py          # Settings (Pydantic)
│   ├── routes.py          # API endpoints
│   ├── agent/             # ReAct agent
│   │   ├── engine.py      # AgentText2SQL
│   │   ├── tools.py       # Agent tools
│   │   └── models.py      # Data models
│   ├── security/          # Auth, rate limiting
│   └── monitoring/        # Metrics, tracing
├── db/                    # Database layer
│   ├── connection.py      # DatabaseManager
│   ├── schema.py          # Schema introspection
│   └── executor.py        # Query execution
├── models/                # ML model layer
│   ├── loader.py          # Model loading
│   ├── inference.py       # Inference engine
│   └── prompts.py         # Prompt templates
└── tests/
    ├── unit/              # Unit tests
    ├── integration/       # Integration tests
    └── conftest.py        # Fixtures
```

## Key Patterns

### Singletons

```python
from app.config import get_settings
from db.connection import get_database
from models.loader import get_model_loader
from app.agent import get_agent_engine

settings = get_settings()
db = await get_database()
```

### Async-First

All I/O is async:

```python
async def my_endpoint():
    result = await engine.generate_sql(query, database_id)
    return result
```

### Exception Handling

Custom exceptions map to HTTP status codes:

```python
from app.exceptions import ValidationException, SchemaNotFoundException

raise ValidationException("Invalid SQL syntax")  # -> 400
raise SchemaNotFoundException("Database not found")  # -> 404
```

## Adding a New Endpoint

1. Define request/response models in `app/routes.py`
2. Add the endpoint function with `@router.get/post`
3. Add tests in `tests/unit/test_routes.py`
4. Update `docs/API.md`

## Adding a New Agent Tool

1. Create tool function in `app/agent/tools.py`
2. Register in `app/agent/tool_factory.py`
3. Add tests in `tests/unit/test_agent_tools.py`

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make changes and add tests
4. Run linting and tests
5. Commit: `git commit -m 'Add my feature'`
6. Push: `git push origin feature/my-feature`
7. Open a Pull Request

## CI/CD

GitHub Actions workflows:

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `ci.yml` | Push/PR | Lint, test, build |
| `release.yml` | Tag `v*` | Build and publish |

### CI Timing (Approximate)

| Job | Time |
|-----|------|
| Security Scan | ~10s |
| Lint & Format | ~18s |
| Tests | ~1m 20s |
| Build Check | ~12s |
| Docker Build | ~3-5m (cached) |
