# InvoiceFlow Deployment Guide

## Quick Start (Docker Compose)

The fastest way to run InvoiceFlow with PostgreSQL:

```bash
git clone https://github.com/your-org/invoiceflow.git
cd invoiceflow

# Set a production secret key
export SECRET_KEY=$(openssl rand -hex 32)

# Start the stack
docker compose up -d

# Verify
curl http://localhost:8000/health
```

This starts:
- **app** on port 8000 — the FastAPI server
- **postgres** on port 5432 — PostgreSQL 16

## Local Development

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Run database migrations
alembic upgrade head

# Start the server
invoiceflow serve --host 127.0.0.1 --port 8000 --reload
```

## Configuration

All settings use environment variables with the `INVOICEFLOW_` prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `INVOICEFLOW_DATABASE_URL` | `sqlite+aiosqlite:///~/.invoiceflow/invoiceflow.db` | Database connection string |
| `INVOICEFLOW_SECRET_KEY` | `change-me-in-production` | JWT signing key |
| `INVOICEFLOW_OLLAMA_BASE_URL` | `http://10.0.3.144:11434` | Ollama API endpoint |
| `INVOICEFLOW_OLLAMA_MODEL` | `qwen2.5:14b` | LLM model for extraction |
| `INVOICEFLOW_WATCH_DIR` | `~/.invoiceflow/watch` | Watch folder path |
| `INVOICEFLOW_UPLOAD_DIR` | `~/.invoiceflow/uploads` | Uploaded file storage |
| `INVOICEFLOW_EXPORT_DIR` | `~/.invoiceflow/exports` | Export output directory |
| `INVOICEFLOW_DUPLICATE_THRESHOLD` | `85.0` | Fuzzy match threshold (%) |
| `INVOICEFLOW_WEBHOOK_URL` | *(empty)* | Webhook for status change notifications |
| `INVOICEFLOW_IMAP_HOST` | `localhost` | IMAP server for email ingestion |
| `INVOICEFLOW_IMAP_PORT` | `993` | IMAP port |
| `INVOICEFLOW_IMAP_USER` | *(empty)* | IMAP username |
| `INVOICEFLOW_IMAP_PASSWORD` | *(empty)* | IMAP password |
| `INVOICEFLOW_IMAP_FOLDER` | `INBOX` | IMAP folder to scan |
| `INVOICEFLOW_IMAP_USE_SSL` | `true` | Use SSL for IMAP |
| `INVOICEFLOW_DEBUG` | `false` | Enable debug logging |

## PostgreSQL (Production)

For production, use PostgreSQL instead of SQLite:

```bash
export INVOICEFLOW_DATABASE_URL="postgresql+asyncpg://invoiceflow:secret@db-host:5432/invoiceflow"
```

## Ollama Setup

InvoiceFlow requires an Ollama instance for LLM-powered extraction. The model must support structured JSON output.

```bash
# Install Ollama (on the GPU server)
curl -fsSL https://ollama.ai/install.sh | sh

# Pull the recommended model
ollama pull qwen2.5:14b

# Point InvoiceFlow to your Ollama instance
export INVOICEFLOW_OLLAMA_BASE_URL="http://your-gpu-server:11434"
export INVOICEFLOW_OLLAMA_MODEL="qwen2.5:14b"
```

**Hardware requirements for qwen2.5:14b:**
- GPU: 12GB+ VRAM (e.g., RTX 3060 12GB)
- RAM: 16GB+ system memory
- Disk: ~10GB for model weights

Smaller models like `qwen2.5:7b` work on 8GB VRAM with reduced accuracy.

## Directory Structure

InvoiceFlow creates the following directory tree at runtime:

```
~/.invoiceflow/
├── invoiceflow.db      # SQLite database (if using SQLite)
├── watch/              # Drop invoice files here for auto-ingestion
├── uploads/            # Processed files are stored here
└── exports/            # CSV and IIF export output
```

## Reverse Proxy (Nginx)

```nginx
server {
    listen 443 ssl;
    server_name invoiceflow.example.com;

    ssl_certificate     /etc/letsencrypt/live/invoiceflow.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/invoiceflow.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 50M;
    }
}
```

## Health Checks

Two endpoints for orchestrators and load balancers:

- `GET /health` — Returns status, version, and timestamp
- `GET /ready` — Readiness probe (checks database connectivity)

```bash
# Liveness
curl -f http://localhost:8000/health

# Readiness
curl -f http://localhost:8000/ready
```

## CLI Reference

```bash
invoiceflow ingest FILE           # Process a local invoice file
invoiceflow fetch URL             # Fetch and process from a URL
invoiceflow export [--format csv|iif]  # Export invoices
invoiceflow watch [--dir PATH]    # Start the watch folder monitor
invoiceflow email-ingest          # Poll IMAP inbox for invoices
invoiceflow serve                 # Run the API server
```

All commands accept `-v` / `--verbose` for debug logging.
