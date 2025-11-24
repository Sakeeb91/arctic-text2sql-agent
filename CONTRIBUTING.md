# Contributing to Arctic Text2SQL Agent

Thank you for your interest in contributing to Arctic Text2SQL Agent! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Code Style](#code-style)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Issue Guidelines](#issue-guidelines)

## Code of Conduct

This project adheres to a code of conduct. By participating, you are expected to uphold this code. Please be respectful and constructive in all interactions.

## Getting Started

### Prerequisites

- Python 3.10 or higher
- Git
- (Optional) Docker and Docker Compose
- (Optional) CUDA-capable GPU for model inference

### Fork and Clone

1. Fork the repository on GitHub
2. Clone your fork locally:

```bash
git clone https://github.com/YOUR_USERNAME/arctic-text2sql-agent.git
cd arctic-text2sql-agent
```

3. Add the upstream repository:

```bash
git remote add upstream https://github.com/Sakeeb91/arctic-text2sql-agent.git
```

## Development Setup

### Create Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### Install Dependencies

```bash
# Install all dependencies including dev tools
pip install -r requirements.txt

# Install async database drivers
pip install aiosqlite asyncpg aiomysql
```

### Configure Environment

```bash
cp .env.example .env
# Edit .env with your configuration
```

### Install Pre-commit Hooks

```bash
pip install pre-commit
pre-commit install
```

### Run the Application

```bash
uvicorn app.main:app --reload
```

Visit http://localhost:8000/docs for the API documentation.

## Making Changes

### Branch Naming

Use descriptive branch names:

- `feature/add-new-endpoint` - New features
- `fix/query-validation-bug` - Bug fixes
- `docs/update-readme` - Documentation
- `refactor/improve-schema-parsing` - Code refactoring
- `test/add-executor-tests` - Test additions

### Commit Messages

Follow conventional commit format:

```
type(scope): description

[optional body]

[optional footer]
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Formatting (no code change)
- `refactor`: Code restructuring
- `test`: Adding tests
- `chore`: Maintenance tasks
- `ci`: CI/CD changes

Examples:

```
feat(api): add query retry endpoint with correction hints

- Add POST /api/v1/agent/retry endpoint
- Support optional correction hints
- Include previous reasoning in retry

Closes #123
```

```
fix(executor): handle timeout in async query execution

Query execution now properly cancels on timeout
instead of hanging indefinitely.
```

## Code Style

### Python Style Guide

We follow PEP 8 with these tools:

- **Black**: Code formatting (line length: 88)
- **Ruff**: Linting and import sorting
- **MyPy**: Static type checking

### Pre-commit Checks

Pre-commit hooks automatically run on every commit:

```bash
# Run manually on all files
pre-commit run --all-files

# Run specific hook
pre-commit run black --all-files
```

### Type Hints

All public functions must have type hints:

```python
async def generate_sql(
    query: str,
    schema: SchemaInfo,
    dialect: str = "postgresql",
) -> SQLResult:
    """
    Generate SQL from natural language query.

    Args:
        query: Natural language question
        schema: Database schema information
        dialect: SQL dialect to use

    Returns:
        SQLResult with generated query
    """
    pass
```

### Docstrings

Use Google-style docstrings:

```python
def validate_query(sql: str, schema: dict[str, Any]) -> ValidationResult:
    """
    Validate SQL query against schema.

    Args:
        sql: SQL query to validate
        schema: Database schema dictionary

    Returns:
        ValidationResult with status and errors

    Raises:
        InvalidQueryException: If query is malformed
    """
    pass
```

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov=db --cov=models --cov-report=html

# Run specific test file
pytest tests/unit/test_config.py

# Run tests matching pattern
pytest -k "test_validation"

# Run with verbose output
pytest -v
```

### Test Structure

```
tests/
├── conftest.py           # Shared fixtures
├── unit/                 # Unit tests
│   ├── test_config.py
│   ├── test_exceptions.py
│   └── test_prompts.py
└── integration/          # Integration tests
    └── test_api.py
```

### Writing Tests

- Use pytest fixtures for setup
- Mock external dependencies
- Test edge cases and error conditions
- Aim for >80% coverage

```python
import pytest
from app.exceptions import InvalidQueryException

class TestQueryValidation:
    """Tests for query validation."""

    def test_valid_select_query(self) -> None:
        """Test that valid SELECT queries pass validation."""
        result = validate("SELECT * FROM users")
        assert result.valid is True

    def test_invalid_query_raises_exception(self) -> None:
        """Test that invalid queries raise appropriate exception."""
        with pytest.raises(InvalidQueryException):
            validate("INVALID SQL QUERY")

    @pytest.mark.asyncio
    async def test_async_execution(self, db_session) -> None:
        """Test async query execution."""
        result = await execute_query(db_session, "SELECT 1")
        assert result.success is True
```

## Pull Request Process

### Before Submitting

1. **Update your fork**:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

2. **Run all checks**:
   ```bash
   pre-commit run --all-files
   pytest
   ```

3. **Update documentation** if needed

### PR Guidelines

- Fill out the PR template completely
- Link related issues
- Add tests for new functionality
- Update documentation as needed
- Keep PRs focused (one feature/fix per PR)
- Ensure CI passes

### PR Title Format

Use conventional commit format for PR titles:

```
feat(api): add batch query endpoint
fix(model): handle empty schema gracefully
docs: update API documentation
```

### Review Process

1. Maintainers will review your PR
2. Address any requested changes
3. Once approved, maintainers will merge

## Issue Guidelines

### Bug Reports

Include:
- Python version and OS
- Steps to reproduce
- Expected vs actual behavior
- Error messages/logs
- Minimal reproduction code

### Feature Requests

Include:
- Use case description
- Proposed solution
- Alternative approaches considered
- Willingness to implement

### Questions

For questions, use [GitHub Discussions](https://github.com/Sakeeb91/arctic-text2sql-agent/discussions) instead of issues.

## Development Tips

### Running with Docker

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f api

# Rebuild after changes
docker-compose build api
```

### Debugging

```python
# Use structured logging
from app.logging_config import get_logger

logger = get_logger(__name__)
logger.debug("Processing query", query=query, schema_tables=len(schema.tables))
```

### Performance Testing

```bash
# Run benchmarks
pytest tests/ -m "slow" --benchmark-only
```

## Getting Help

- **Issues**: [GitHub Issues](https://github.com/Sakeeb91/arctic-text2sql-agent/issues)
- **Discussions**: [GitHub Discussions](https://github.com/Sakeeb91/arctic-text2sql-agent/discussions)
- **Email**: rahman.sakeeb@gmail.com

---

Thank you for contributing! 🎉

