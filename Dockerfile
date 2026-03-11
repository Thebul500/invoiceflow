FROM python:3.12-alpine AS builder

RUN apk add --no-cache gcc musl-dev libffi-dev

WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .

FROM python:3.12-alpine

RUN apk upgrade --no-cache && \
    addgroup -S app && adduser -S app -G app

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .

RUN chown -R app:app /app
USER app

EXPOSE 8000
CMD ["uvicorn", "invoiceflow.app:app", "--host", "0.0.0.0", "--port", "8000"]
