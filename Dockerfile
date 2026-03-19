# ==============================================================================
# ZTRACK API - Dockerfile multi-stage
# Python 3.12, Gunicorn + Uvicorn workers
# ==============================================================================

FROM python:3.12-slim AS builder

WORKDIR /app

# Dependencias de compilación (opcionales para wheels nativos)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ------------------------------------------------------------------------------
# Imagen final
# ------------------------------------------------------------------------------
FROM python:3.12-slim

WORKDIR /app

# Usuario no-root (con home para pip --user)
RUN groupadd -r ztrack && useradd -r -g ztrack -m -d /home/ztrack ztrack

# Copiar dependencias del builder
COPY --from=builder /root/.local /home/ztrack/.local
RUN chown -R ztrack:ztrack /home/ztrack/.local
ENV PATH=/home/ztrack/.local/bin:$PATH

# Copiar código
COPY --chown=ztrack:ztrack app/ ./app/
COPY --chown=ztrack:ztrack main.py gunicorn.conf.py ./

USER ztrack

EXPOSE 9050

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9050/health')" || exit 1

# Gunicorn como proceso principal (--reload para desarrollo)
CMD ["gunicorn", "-c", "gunicorn.conf.py", "--reload", "app.main:app"]
