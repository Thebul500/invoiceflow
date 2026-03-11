# Contributing to InvoiceFlow

Thank you for your interest in contributing to InvoiceFlow! This guide will help you get started.

## Setup

### Prerequisites

- Python 3.11 or later
- Git

### Development Environment

1. Clone the repository and create a virtual environment:

```bash
git clone https://github.com/your-org/invoiceflow.git
cd invoiceflow
python -m venv .venv
source .venv/bin/activate
```

2. Install the package with development dependencies:

```bash
pip install -e ".[dev]"
```

This installs all runtime dependencies (FastAPI, SQLAlchemy, etc.) plus dev tools: pytest, ruff, mypy, and bandit.

3. InvoiceFlow uses SQLite by default for local development — no database setup required. To use PostgreSQL instead, set the environment variable:

```bash
export INVOICEFLOW_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/invoiceflow
```

Or run the full stack with Docker Compose:

```bash
docker compose up
```

## Test

Run the full test suite:

```bash
pytest -v
```

Run tests with coverage:

```bash
pytest --cov=src/invoiceflow -v
```

### Linting and Type Checks

The project uses ruff for linting (line length: 100), mypy for type checking, and bandit for security scanning:

```bash
ruff check src/
mypy src/invoiceflow/ --ignore-missing-imports
bandit -r src/invoiceflow/ -q
```

All of these checks run in CI on every pull request. Make sure they pass locally before pushing.

## Pull Request Process

1. **Create a branch** from `main` with a descriptive name:

```bash
git checkout -b fix/duplicate-detection-threshold
```

2. **Make your changes.** Follow existing code patterns:
   - FastAPI routes go in `src/invoiceflow/routes/`
   - Core processing logic goes in `src/invoiceflow/engine/`
   - Use async/await for all database operations and HTTP handlers
   - Add Pydantic schemas for request/response models in `schemas.py`
   - Include proper HTTP status codes and error handling

3. **Write tests** for new functionality. Tests use pytest-asyncio with `asyncio_mode = "auto"`.

4. **Run the full check suite** before submitting:

```bash
pytest --cov=src/invoiceflow -v
ruff check src/
mypy src/invoiceflow/ --ignore-missing-imports
bandit -r src/invoiceflow/ -q
```

5. **Open a pull request** against `main`. In your PR description:
   - Summarize what the change does and why
   - Reference any related issues
   - Note any breaking changes or migration steps

6. **CI must pass.** The GitHub Actions pipeline runs tests, linting, type checks, and security scans automatically. PRs with failing checks will not be merged.

## Code Style

- Line length: 100 characters (enforced by ruff)
- Use type annotations for function signatures
- Follow existing patterns in the codebase — consistency matters more than personal preference

## Reporting Issues

If you find a bug or have a feature request, please open a GitHub issue with:
- Steps to reproduce (for bugs)
- Expected vs actual behavior
- Your Python version and OS
