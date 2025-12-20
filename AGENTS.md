# Repository Guidelines

## Project Structure & Module Organization
- `app/` contains the FastAPI service, agent runtime (`app/agent/`), routing (`app/routes*.py`), streaming, monitoring, and configuration.
- `db/` holds database connection utilities, schema inspection, executors, and migrations.
- `models/` covers model loading, prompts, and inference helpers.
- `tests/` is split into `tests/unit/` and `tests/integration/` with shared fixtures in `tests/conftest.py`.
- `docs/`, `scripts/`, and `deploy/` provide design notes, automation, and deployment artifacts.

## Build, Test, and Development Commands
Use these from the repo root:

```bash
# Install dependencies (recommended)
bash scripts/install_with_constraints.sh

# Run the API locally
uvicorn app.main:app --reload

# Run tests
pytest
pytest --cov=app tests/

# Format, lint, type check
black app/ tests/
ruff check app/ tests/
mypy app/ db/ models/ --ignore-missing-imports

# Bring up local services
docker-compose up -d
```

## Coding Style & Naming Conventions
- Python 3.10+, formatted with Black and linted with Ruff (see `pyproject.toml`).
- Prefer explicit type hints for public functions and Pydantic models for request/response schemas.
- Naming: `snake_case` for modules/functions/vars, `PascalCase` for classes, constants in `UPPER_SNAKE_CASE`.

## Testing Guidelines
- Pytest is the standard; use fixtures in `tests/conftest.py` for shared setup.
- Name tests `test_*.py` and functions `test_*`; keep unit vs integration coverage in their folders.
- For focused runs, use `pytest tests/unit/test_agent_engine.py` or `pytest -k "validation"`.

## Commit & Pull Request Guidelines
- Follow conventional commits, e.g. `feat(agent): add retry tool`, `fix(api): handle empty schema`, `docs: update env vars`.
- PRs should link issues, include tests and docs where applicable, and stay focused to one change set.
- Ensure CI checks pass before requesting review.

## Configuration & Security Notes
- Configuration is driven by environment variables; start from `.env.example` and document new settings in `README.md`.
- Avoid hardcoding secrets; use runtime config for tokens and database credentials.
