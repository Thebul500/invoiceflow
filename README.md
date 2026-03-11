# invoiceflow

AI invoice processing pipeline. Ingests invoices (PDF, email, image) via watch folder or API, uses LLM (Ollama) to extract vendor, line items, amounts, dates, PO numbers. Validates against purchase orders, flags discrepancies, categorizes expenses, exports to CSV/QuickBooks format. Duplicate detection via fuzzy matching. Approval workflow with webhook notifications. REST API + CLI. FastAPI + SQLite.

[![CI](https://github.com/Thebul500/invoiceflow/actions/workflows/ci.yml/badge.svg)](https://github.com/Thebul500/invoiceflow/actions)

## Quick Start

```bash
docker compose up -d
curl http://localhost:8000/health
```

## Installation (Development)

```bash
pip install -e .[dev]
uvicorn invoiceflow.app:app --reload
```

## Usage

```bash
# Start with Docker Compose (recommended)
docker compose up -d

# Or run directly
uvicorn invoiceflow.app:app --host 0.0.0.0 --port 8000
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/ready` | Readiness probe |

## Configuration

Environment variables (prefix `INVOICEFLOW_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Database connection string |
| `SECRET_KEY` | `change-me` | JWT signing key |
| `DEBUG` | `false` | Enable debug mode |
