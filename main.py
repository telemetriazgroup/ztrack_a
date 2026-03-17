"""
main.py — Punto de entrada raíz.

REEMPLAZA el main.py original que solo lanzaba Uvicorn directamente.

ANTES (original):
    uvicorn.run("server.app:app", host="0.0.0.0", port=9050, reload=True)

AHORA — Dos modos:
  Desarrollo: python main.py  → Uvicorn con reload (igual que antes)
  Producción: gunicorn -c gunicorn.conf.py app.main:app  (nuevo)
"""
import uvicorn

if __name__ == "__main__":
    from app.core.config import get_settings
    settings = get_settings()

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_env == "development",
        log_level=settings.log_level.lower(),
    )
