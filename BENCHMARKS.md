# InvoiceFlow API Performance Benchmarks

Performance benchmarks for key API endpoints, measuring throughput and latency.

## Environment

- **Date**: 2026-03-11
- **Python**: 3.12.3
- **Framework**: FastAPI + Uvicorn
- **Database**: SQLite (aiosqlite, async)
- **Method**: Sequential requests via `TestClient` (single-threaded)

## Results Summary

| Scenario | Req/s | p50 (ms) | p95 (ms) | p99 (ms) | Mean (ms) |
|----------|------:|---------:|---------:|---------:|----------:|
| Health Check (GET /health) | 1266.5 | 0.654 | 1.181 | 1.793 | 0.787 |
| Readiness Probe (GET /ready) | 1141.2 | 0.825 | 1.295 | 1.603 | 0.873 |
| Create Invoice (POST /api/invoices) | 13.9 | 47.819 | 89.185 | 1108.092 | 71.909 |
| List Invoices (GET /api/invoices) | 98.1 | 9.408 | 12.275 | 21.5 | 10.185 |
| Get Invoice by ID (GET /api/invoices/1) | 243.2 | 3.935 | 5.285 | 6.577 | 4.107 |
| Create Purchase Order (POST /api/purchase-orders) | 27.7 | 16.848 | 23.966 | 1067.57 | 36.132 |
| List Invoices Filtered (GET /api/invoices?status=pending) | 98.0 | 9.627 | 11.745 | 14.433 | 10.198 |
| Update Invoice Status (PATCH /api/invoices/1/status) | 169.2 | 5.595 | 7.765 | 9.648 | 5.907 |

## Detailed Results

### 1. Health Check (GET /health)

- **Endpoint**: `GET /health`
- **Iterations**: 1000
- **Errors**: 0
- **Throughput**: 1266.5 req/s
- **Latency**:
  - Mean: 0.787 ms
  - p50: 0.654 ms
  - p95: 1.181 ms
  - p99: 1.793 ms
  - Min: 0.509 ms
  - Max: 39.61 ms
  - Stdev: 1.256 ms

### 2. Readiness Probe (GET /ready)

- **Endpoint**: `GET /ready`
- **Iterations**: 1000
- **Errors**: 0
- **Throughput**: 1141.2 req/s
- **Latency**:
  - Mean: 0.873 ms
  - p50: 0.825 ms
  - p95: 1.295 ms
  - p99: 1.603 ms
  - Min: 0.487 ms
  - Max: 4.316 ms
  - Stdev: 0.295 ms

### 3. Create Invoice (POST /api/invoices)

- **Endpoint**: `POST /api/invoices`
- **Iterations**: 500
- **Errors**: 0
- **Throughput**: 13.9 req/s
- **Latency**:
  - Mean: 71.909 ms
  - p50: 47.819 ms
  - p95: 89.185 ms
  - p99: 1108.092 ms
  - Min: 29.458 ms
  - Max: 1497.378 ms
  - Stdev: 156.015 ms

### 4. List Invoices (GET /api/invoices)

- **Endpoint**: `GET /api/invoices`
- **Iterations**: 500
- **Errors**: 0
- **Throughput**: 98.1 req/s
- **Latency**:
  - Mean: 10.185 ms
  - p50: 9.408 ms
  - p95: 12.275 ms
  - p99: 21.5 ms
  - Min: 7.749 ms
  - Max: 51.243 ms
  - Stdev: 3.564 ms

### 5. Get Invoice by ID (GET /api/invoices/1)

- **Endpoint**: `GET /api/invoices/1`
- **Iterations**: 500
- **Errors**: 0
- **Throughput**: 243.2 req/s
- **Latency**:
  - Mean: 4.107 ms
  - p50: 3.935 ms
  - p95: 5.285 ms
  - p99: 6.577 ms
  - Min: 3.192 ms
  - Max: 10.561 ms
  - Stdev: 0.653 ms

### 6. Create Purchase Order (POST /api/purchase-orders)

- **Endpoint**: `POST /api/purchase-orders`
- **Iterations**: 500
- **Errors**: 0
- **Throughput**: 27.7 req/s
- **Latency**:
  - Mean: 36.132 ms
  - p50: 16.848 ms
  - p95: 23.966 ms
  - p99: 1067.57 ms
  - Min: 12.984 ms
  - Max: 2310.626 ms
  - Stdev: 167.049 ms

### 7. List Invoices Filtered (GET /api/invoices?status=pending)

- **Endpoint**: `GET /api/invoices?status=pending`
- **Iterations**: 500
- **Errors**: 0
- **Throughput**: 98.0 req/s
- **Latency**:
  - Mean: 10.198 ms
  - p50: 9.627 ms
  - p95: 11.745 ms
  - p99: 14.433 ms
  - Min: 7.942 ms
  - Max: 53.08 ms
  - Stdev: 3.349 ms

### 8. Update Invoice Status (PATCH /api/invoices/1/status)

- **Endpoint**: `PATCH /api/invoices/1/status`
- **Iterations**: 500
- **Errors**: 0
- **Throughput**: 169.2 req/s
- **Latency**:
  - Mean: 5.907 ms
  - p50: 5.595 ms
  - p95: 7.765 ms
  - p99: 9.648 ms
  - Min: 4.562 ms
  - Max: 11.42 ms
  - Stdev: 0.896 ms

## Methodology

- Benchmarks run using FastAPI `TestClient` (synchronous, single-threaded)
- Each scenario includes a warmup phase (5-10 requests) before measurement
- Latency measured per-request using `time.perf_counter()` (high-resolution timer)
- Percentiles calculated from raw latency distributions
- Database is SQLite with async driver (aiosqlite) — production deployments with PostgreSQL will differ
- Tests run against a fresh database; write benchmarks create unique records per iteration

## Notes

- Health/readiness endpoints are stateless and do not hit the database
- Write operations (Create Invoice, Create PO) include ORM serialization and DB commit
- List endpoints return all records; latency may increase with larger datasets
- Invoice creation includes line item relationship handling (2 line items per invoice)
- These are single-client sequential benchmarks; concurrent load testing would show different characteristics
