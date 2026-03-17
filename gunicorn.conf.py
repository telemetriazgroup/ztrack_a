"""
gunicorn.conf.py — Configuración Gunicorn + Uvicorn workers.

Ejecutar:
    gunicorn -c gunicorn.conf.py app.main:app

Variables de entorno:
    APP_ENV=development → reload habilitado, 1 worker
    APP_ENV=production  → sin reload, múltiples workers
"""
import multiprocessing
import os

_is_development = os.environ.get("APP_ENV") == "development"

# ── Reload en desarrollo ─────────────────────────────────────────────────────
# reload incompatible con preload_app
reload = _is_development
preload_app = not _is_development

# ── Workers ──────────────────────────────────────────────────────────────────
# Desarrollo: 1 worker para reload | Producción: (2 x CPUs) + 1
workers = 1 if _is_development else int(
    os.environ.get("GUNICORN_WORKERS", (multiprocessing.cpu_count() * 2) + 1)
)
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 1000

# ── Red ──────────────────────────────────────────────────────────────────────
bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:9050")

# ── Timeouts ─────────────────────────────────────────────────────────────────
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 30))
keepalive = 5
graceful_timeout = 30

# ── Memoria (solo en producción) ─────────────────────────────────────────────
# preload_app=True: La app se carga UNA vez y se hace fork.
max_requests = 10_000        # Reiniciar workers para evitar memory leaks
max_requests_jitter = 1_000  # Evita reinicio sincronizado de todos los workers

# ── Logging ──────────────────────────────────────────────────────────────────
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s %(D)sµs'

# ── Hooks de ciclo de vida ───────────────────────────────────────────────────

def on_starting(server):
    mode = "desarrollo (reload)" if reload else "producción"
    server.log.info(f"ZTRACK API: {mode}, {workers} worker(s) en {bind}")


def post_fork(server, worker):
    # Aquí se pueden reinicializar recursos post-fork si fuera necesario
    server.log.info(f"Worker {worker.pid} listo")


def worker_exit(server, worker):
    server.log.info(f"Worker {worker.pid} terminado")


def on_exit(server):
    server.log.info("ZTRACK API: Gunicorn terminado")
