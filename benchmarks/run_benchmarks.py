"""API performance benchmarks for invoiceflow.

Measures requests/sec and p50/p95/p99 latency for key endpoints.
"""

import asyncio
import os
import statistics
import sys
import tempfile
import time

# Set up test environment before importing app
os.environ["INVOICEFLOW_DATA_DIR"] = tempfile.mkdtemp(prefix="invoiceflow_bench_")

from fastapi.testclient import TestClient  # noqa: E402

from invoiceflow.app import create_app  # noqa: E402
from invoiceflow.database import Base, engine  # noqa: E402


def percentile(data: list[float], p: float) -> float:
    """Calculate percentile from sorted data."""
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[f]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def run_benchmark(client: TestClient, name: str, method: str, url: str,
                  iterations: int = 500, json_body: dict | None = None,
                  setup_fn=None) -> dict:
    """Run a single benchmark scenario."""
    if setup_fn:
        setup_fn(client)

    # Warmup
    for _ in range(10):
        if method == "GET":
            client.get(url)
        elif method == "POST":
            client.post(url, json=json_body)
        elif method == "PATCH":
            client.patch(url, json=json_body)

    latencies_ms = []
    errors = 0

    start_wall = time.perf_counter()
    for _ in range(iterations):
        t0 = time.perf_counter()
        if method == "GET":
            resp = client.get(url)
        elif method == "POST":
            resp = client.post(url, json=json_body)
        elif method == "PATCH":
            resp = client.patch(url, json=json_body)
        t1 = time.perf_counter()

        latency_ms = (t1 - t0) * 1000
        latencies_ms.append(latency_ms)

        if resp.status_code >= 400:
            errors += 1
    end_wall = time.perf_counter()

    total_time = end_wall - start_wall
    rps = iterations / total_time

    return {
        "name": name,
        "method": method,
        "url": url,
        "iterations": iterations,
        "errors": errors,
        "rps": round(rps, 1),
        "mean_ms": round(statistics.mean(latencies_ms), 3),
        "p50_ms": round(percentile(latencies_ms, 50), 3),
        "p95_ms": round(percentile(latencies_ms, 95), 3),
        "p99_ms": round(percentile(latencies_ms, 99), 3),
        "min_ms": round(min(latencies_ms), 3),
        "max_ms": round(max(latencies_ms), 3),
        "stdev_ms": round(statistics.stdev(latencies_ms), 3) if len(latencies_ms) > 1 else 0,
    }


def reset_db():
    """Reset the database for benchmarks."""
    loop = asyncio.new_event_loop()

    async def _reset():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    loop.run_until_complete(_reset())
    loop.close()


SAMPLE_INVOICE = {
    "invoice_number": "INV-BENCH-001",
    "vendor_name": "Benchmark Supplies Inc.",
    "vendor_address": "456 Test Ave, Chicago, IL 60601",
    "invoice_date": "2026-03-01",
    "due_date": "2026-03-31",
    "subtotal": 1000.00,
    "tax_amount": 80.00,
    "total_amount": 1080.00,
    "currency": "USD",
    "po_number": "PO-BENCH-001",
    "line_items": [
        {"description": "Widget A", "quantity": 10, "unit_price": 50.00, "amount": 500.00},
        {"description": "Widget B", "quantity": 5, "unit_price": 100.00, "amount": 500.00},
    ],
}

SAMPLE_PO = {
    "po_number": "PO-BENCH-001",
    "vendor_name": "Benchmark Supplies Inc.",
    "total_amount": 1080.00,
    "description": "Benchmark test PO",
}


def main():
    print("=" * 70)
    print("InvoiceFlow API Performance Benchmarks")
    print("=" * 70)
    print()

    reset_db()
    app = create_app()

    results = []

    with TestClient(app) as client:
        # --- Scenario 1: Health check (lightweight, no DB) ---
        r = run_benchmark(client, "Health Check (GET /health)", "GET", "/health",
                          iterations=1000)
        results.append(r)

        # --- Scenario 2: Readiness probe (lightweight, no DB) ---
        r = run_benchmark(client, "Readiness Probe (GET /ready)", "GET", "/ready",
                          iterations=1000)
        results.append(r)

        # --- Scenario 3: Create Invoice (POST, DB write with line items) ---
        # Each iteration creates a unique invoice to avoid conflicts
        latencies_ms = []
        errors = 0
        iterations = 500

        # Warmup
        for i in range(5):
            payload = {**SAMPLE_INVOICE, "invoice_number": f"INV-WARM-{i}"}
            client.post("/api/invoices", json=payload)

        start_wall = time.perf_counter()
        for i in range(iterations):
            payload = {**SAMPLE_INVOICE, "invoice_number": f"INV-BENCH-{i:05d}"}
            t0 = time.perf_counter()
            resp = client.post("/api/invoices", json=payload)
            t1 = time.perf_counter()
            latencies_ms.append((t1 - t0) * 1000)
            if resp.status_code >= 400:
                errors += 1
        end_wall = time.perf_counter()

        total_time = end_wall - start_wall
        results.append({
            "name": "Create Invoice (POST /api/invoices)",
            "method": "POST",
            "url": "/api/invoices",
            "iterations": iterations,
            "errors": errors,
            "rps": round(iterations / total_time, 1),
            "mean_ms": round(statistics.mean(latencies_ms), 3),
            "p50_ms": round(percentile(latencies_ms, 50), 3),
            "p95_ms": round(percentile(latencies_ms, 95), 3),
            "p99_ms": round(percentile(latencies_ms, 99), 3),
            "min_ms": round(min(latencies_ms), 3),
            "max_ms": round(max(latencies_ms), 3),
            "stdev_ms": round(statistics.stdev(latencies_ms), 3),
        })

        # --- Scenario 4: List Invoices (GET, DB read with populated data) ---
        r = run_benchmark(client, "List Invoices (GET /api/invoices)", "GET",
                          "/api/invoices", iterations=500)
        results.append(r)

        # --- Scenario 5: Get Single Invoice (GET by ID, DB read) ---
        r = run_benchmark(client, "Get Invoice by ID (GET /api/invoices/1)", "GET",
                          "/api/invoices/1", iterations=500)
        results.append(r)

        # --- Scenario 6: Create Purchase Order (POST, DB write) ---
        latencies_ms = []
        errors = 0
        iterations = 500

        for i in range(5):
            payload = {**SAMPLE_PO, "po_number": f"PO-WARM-{i}"}
            client.post("/api/purchase-orders", json=payload)

        start_wall = time.perf_counter()
        for i in range(iterations):
            payload = {**SAMPLE_PO, "po_number": f"PO-BENCH-{i:05d}"}
            t0 = time.perf_counter()
            resp = client.post("/api/purchase-orders", json=payload)
            t1 = time.perf_counter()
            latencies_ms.append((t1 - t0) * 1000)
            if resp.status_code >= 400:
                errors += 1
        end_wall = time.perf_counter()

        total_time = end_wall - start_wall
        results.append({
            "name": "Create Purchase Order (POST /api/purchase-orders)",
            "method": "POST",
            "url": "/api/purchase-orders",
            "iterations": iterations,
            "errors": errors,
            "rps": round(iterations / total_time, 1),
            "mean_ms": round(statistics.mean(latencies_ms), 3),
            "p50_ms": round(percentile(latencies_ms, 50), 3),
            "p95_ms": round(percentile(latencies_ms, 95), 3),
            "p99_ms": round(percentile(latencies_ms, 99), 3),
            "min_ms": round(min(latencies_ms), 3),
            "max_ms": round(max(latencies_ms), 3),
            "stdev_ms": round(statistics.stdev(latencies_ms), 3),
        })

        # --- Scenario 7: List Invoices with Filter (DB read + filter) ---
        r = run_benchmark(client, "List Invoices Filtered (GET /api/invoices?status=pending)",
                          "GET", "/api/invoices?status=pending", iterations=500)
        results.append(r)

        # --- Scenario 8: Update Invoice Status (PATCH, DB write) ---
        r = run_benchmark(
            client,
            "Update Invoice Status (PATCH /api/invoices/1/status)",
            "PATCH", "/api/invoices/1/status",
            iterations=500,
            json_body={"status": "approved"},
        )
        results.append(r)

    # Print results
    for r in results:
        print(f"### {r['name']}")
        print(f"  {r['method']} {r['url']}")
        print(f"  Iterations: {r['iterations']}  |  Errors: {r['errors']}")
        print(f"  Throughput: {r['rps']} req/s")
        print(f"  Latency (ms): mean={r['mean_ms']}  p50={r['p50_ms']}  "
              f"p95={r['p95_ms']}  p99={r['p99_ms']}")
        print(f"  Range (ms): min={r['min_ms']}  max={r['max_ms']}  stdev={r['stdev_ms']}")
        print()

    # Write markdown results
    write_benchmarks_md(results)
    print(f"Results written to BENCHMARKS.md")


def write_benchmarks_md(results: list[dict]):
    """Write benchmark results to BENCHMARKS.md."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    md_path = os.path.join(project_root, "BENCHMARKS.md")

    lines = [
        "# InvoiceFlow API Performance Benchmarks",
        "",
        "Performance benchmarks for key API endpoints, measuring throughput and latency.",
        "",
        "## Environment",
        "",
        f"- **Date**: {time.strftime('%Y-%m-%d')}",
        f"- **Python**: {sys.version.split()[0]}",
        "- **Framework**: FastAPI + Uvicorn",
        "- **Database**: SQLite (aiosqlite, async)",
        "- **Method**: Sequential requests via `TestClient` (single-threaded)",
        "",
        "## Results Summary",
        "",
        "| Scenario | Req/s | p50 (ms) | p95 (ms) | p99 (ms) | Mean (ms) |",
        "|----------|------:|---------:|---------:|---------:|----------:|",
    ]

    for r in results:
        lines.append(
            f"| {r['name']} | {r['rps']} | {r['p50_ms']} | "
            f"{r['p95_ms']} | {r['p99_ms']} | {r['mean_ms']} |"
        )

    lines.extend([
        "",
        "## Detailed Results",
        "",
    ])

    for i, r in enumerate(results, 1):
        lines.extend([
            f"### {i}. {r['name']}",
            "",
            f"- **Endpoint**: `{r['method']} {r['url']}`",
            f"- **Iterations**: {r['iterations']}",
            f"- **Errors**: {r['errors']}",
            f"- **Throughput**: {r['rps']} req/s",
            f"- **Latency**:",
            f"  - Mean: {r['mean_ms']} ms",
            f"  - p50: {r['p50_ms']} ms",
            f"  - p95: {r['p95_ms']} ms",
            f"  - p99: {r['p99_ms']} ms",
            f"  - Min: {r['min_ms']} ms",
            f"  - Max: {r['max_ms']} ms",
            f"  - Stdev: {r['stdev_ms']} ms",
            "",
        ])

    lines.extend([
        "## Methodology",
        "",
        "- Benchmarks run using FastAPI `TestClient` (synchronous, single-threaded)",
        "- Each scenario includes a warmup phase (5-10 requests) before measurement",
        "- Latency measured per-request using `time.perf_counter()` (high-resolution timer)",
        "- Percentiles calculated from raw latency distributions",
        "- Database is SQLite with async driver (aiosqlite) — "
        "production deployments with PostgreSQL will differ",
        "- Tests run against a fresh database; write benchmarks create unique records per iteration",
        "",
        "## Notes",
        "",
        "- Health/readiness endpoints are stateless and do not hit the database",
        "- Write operations (Create Invoice, Create PO) include ORM serialization and DB commit",
        "- List endpoints return all records; latency may increase with larger datasets",
        "- Invoice creation includes line item relationship handling (2 line items per invoice)",
        "- These are single-client sequential benchmarks; "
        "concurrent load testing would show different characteristics",
        "",
    ])

    with open(md_path, "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
