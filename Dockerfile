FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml setup.cfg* setup.py* ./
COPY requirements*.txt* ./

RUN pip install --no-cache-dir -e ".[dev]" uvicorn[standard] 2>/dev/null || \
    pip install --no-cache-dir -r requirements.txt uvicorn[standard] 2>/dev/null || \
    pip install --no-cache-dir uvicorn[standard] fastapi pydantic pydantic-settings python-dotenv

COPY . .
RUN pip install --no-cache-dir -e . 2>/dev/null || true

ENV WAREHOUSE_DB_PATH=/data/warehouse.db
ENV SEC_CACHE_DB_PATH=/data/sec_cache.db

EXPOSE 8000

CMD uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}
