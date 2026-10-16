# Single-stage image, intentionally simple for the scaffold.
# Multi-stage builds, image scanning and a minimal production image land with
# KAN-61 (Dockerisation and the CI pipeline).

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/app

# Dependencies first, so edits to application code do not invalidate this layer.
COPY requirements.txt ./
RUN python -m pip install --upgrade pip && \
    python -m pip install -r requirements.txt

COPY app ./app
COPY pyproject.toml ./

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser && \
    chown -R appuser:appuser /srv/app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
