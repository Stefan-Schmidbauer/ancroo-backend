# Ancroo Backend
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY packages/backend/requirements.txt .
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt

COPY packages/backend/src/ ./src/

ARG BUILD_COMMIT=dev
ARG BUILD_VERSION=dev
RUN echo "$BUILD_COMMIT" > ./src/BUILD_COMMIT && \
    echo "$BUILD_VERSION" > ./src/BUILD_VERSION

COPY packages/backend/alembic/ ./alembic/
COPY packages/backend/alembic.ini .

RUN useradd --create-home --shell /bin/bash appuser

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn src.main:app --host 0.0.0.0 --port 8000"]
