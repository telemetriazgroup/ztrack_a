"""
app/main.py — Punto de entrada de la aplicación ZTRACK.

REEMPLAZA: server/app.py del proyecto original.

CAMBIOS vs. original:
  1. Se agrega lifespan para gestionar conexiones MongoDB y Redis
     (antes Motor creaba la conexión al importar database.py — frágil)
  2. Se mantienen los mismos routers y prefijos del original:
       /TermoKing  y  /Tunel
  3. Se agrega endpoint /health para monitoreo
  4. Se agrega endpoint /metrics para Prometheus/Grafana
  5. CORS idéntico al original (allow_origins=["*"])
  6. Docs Swagger activos en desarrollo, desactivados en producción

USO CON GUNICORN (producción, reemplaza el main.py original):
    gunicorn -c gunicorn.conf.py app.main:app

USO DIRECTO (desarrollo):
    uvicorn app.main:app --reload --port 9050
"""
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging

# Configurar logging antes que todo
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    Gestiona el ciclo de vida de la aplicación.

    ANTES: Motor abría la conexión al importar database.py (nivel de módulo).
    Esto causaba que una falla de conexión al iniciar crasheara el import.

    AHORA: La conexión se abre aquí, después del fork de Gunicorn.
    Cada worker tiene su propio pool de conexiones independiente.
    """
    from app.database import mongodb
    from app.services import redis_service

    settings = get_settings()
    logger.info(
        "Iniciando ZTRACK API",
        env=settings.app_env,
        port=settings.app_port,
        auth_enabled=settings.enable_auth,
    )

    # ── Conectar Redis (buffer de escrituras) ────────────────────────────────
    try:
        await redis_service.connect()
        logger.info("Redis listo")
    except Exception as e:
        logger.warning(
            "Redis no disponible — modo degradado (escritura directa a MongoDB)",
            error=str(e),
        )

    # ── Conectar MongoDB ─────────────────────────────────────────────────────
    try:
        await mongodb.connect()
        logger.info("MongoDB listo")
    except Exception as e:
        logger.error("MongoDB no disponible — la aplicación no puede arrancar", error=str(e))
        raise  # MongoDB es crítico, no podemos operar sin él

    # ── Batch writer como background task en desarrollo ──────────────────────
    # En producción, el batch writer corre como proceso separado (systemd).
    batch_task = None
    if settings.app_env == "development":
        from app.workers.batch_writer import run_batch_writer
        batch_task = asyncio.create_task(run_batch_writer(), name="batch_writer")
        logger.info("Batch writer iniciado como background task (modo desarrollo)")

    logger.info("ZTRACK API lista para recibir telemetría", port=settings.app_port)

    yield  # ← La aplicación corre aquí

    # ── Shutdown limpio ──────────────────────────────────────────────────────
    logger.info("Iniciando shutdown...")

    if batch_task:
        batch_task.cancel()
        try:
            await asyncio.wait_for(batch_task, timeout=10.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    await redis_service.disconnect()
    await mongodb.disconnect()
    logger.info("Shutdown completo")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="ZTRACK API",
        summary="Sistema de telemetría IoT bidireccional — TermoKing, Túnel y Datos",
        version="2.0.0",
        lifespan=lifespan,
        # Documentación: ENABLE_DOCS=true o APP_ENV != production
        docs_url="/docs" if settings.show_docs else None,
        redoc_url="/redoc" if settings.show_docs else None,
        openapi_url="/openapi.json" if settings.show_docs else None,
    )

    # ── CORS — idéntico al original ──────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],       # Igual que el original
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ────────────────────────────────────────────────────────────────
    from app.routes.termoking import router as TermoKingRouter
    from app.routes.tunel import router as TunelRouter
    from app.routes.datos import router as DatosRouter
    from app.routes.starcool import router as StarcoolRouter
    from app.routes.generador import router as GeneradorRouter

    app.include_router(TermoKingRouter, tags=["TermoKing"], prefix="/TermoKing")
    app.include_router(TunelRouter, tags=["Tunel"], prefix="/Tunel")
    app.include_router(DatosRouter, tags=["Datos"], prefix="/Datos")
    app.include_router(StarcoolRouter, tags=["Starcool"], prefix="/Starcool")
    app.include_router(GeneradorRouter, tags=["Generador"], prefix="/Generador")

    # ── Root — idéntico al original ──────────────────────────────────────────
    @app.get("/", tags=["Root"])
    async def read_root():
        return {"message": "Welcome to app ztrack by 2.0!"}

    # ── Health check (nuevo) ─────────────────────────────────────────────────
    @app.get("/health", tags=["Sistema"])
    async def health_check():
        from app.database import mongodb
        from app.services import redis_service

        mongo_ok = await mongodb.health_check()
        redis_ok = await redis_service.health_check()
        queues = await redis_service.get_queue_lengths()

        is_healthy = mongo_ok  # MongoDB es crítico; Redis es opcional
        body = {
            "status": "healthy" if is_healthy else "degraded",
            "components": {
                "mongodb": "ok" if mongo_ok else "error",
                "redis": "ok" if redis_ok else "degraded",
            },
            "queues": queues,
        }
        if not is_healthy:
            return JSONResponse(content=body, status_code=503)
        return body

    # ── Métricas Prometheus (nuevo) ──────────────────────────────────────────
    if settings.metrics_enabled:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        @app.get(settings.metrics_path, include_in_schema=False)
        async def metrics():
            return PlainTextResponse(
                generate_latest().decode("utf-8"),
                media_type=CONTENT_TYPE_LATEST,
            )

    # ── Manejo global de errores ─────────────────────────────────────────────
    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        return JSONResponse(
            status_code=404,
            content={"error": "Endpoint no encontrado", "path": request.url.path},
        )

    @app.exception_handler(500)
    async def server_error(request: Request, exc):
        logger.error("Error interno no manejado", error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": "Error interno del servidor"},
        )

    return app


# Instancia principal — referenciada por Gunicorn y uvicorn
app = create_app()
