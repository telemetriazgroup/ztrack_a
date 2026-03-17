"""
app/middleware/auth.py — Seguridad Progresiva para ZTRACK.

CONTEXTO REAL:
  Los 300 dispositivos existentes NO pueden actualizar firmware.
  El sistema DEBE aceptarlos sin API Key ahora mismo.
  Cuando un técnico actualice físicamente el firmware de un equipo,
  ese dispositivo empieza a enviar X-Device-Key y pasa a "secured".

MODOS:
  Legacy  (secured=False) — Sin header → acepta, marca como inseguro.
  Seguro  (secured=True)  — Con header válido → acepta, marca como seguro.
  Inválido (secured=False) — Con header inválido → acepta como legacy + log.

El campo 'secured' viaja al documento MongoDB y a las métricas Prometheus.
"""
import secrets
from typing import Optional

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import AUTH_FAILURE, AUTH_SUCCESS, DEVICES_LEGACY, DEVICES_SECURED

logger = get_logger(__name__)

_api_key_header = APIKeyHeader(name="X-Device-Key", auto_error=False)


class DeviceAuthResult:
    """Resultado de la evaluación de seguridad."""
    def __init__(
        self,
        authenticated: bool = True,
        imei: str = "",
        secured: bool = False,
        reason: Optional[str] = None,
        from_cache: bool = False,
    ):
        self.authenticated = authenticated
        self.imei = imei
        self.secured = secured
        self.reason = reason
        self.from_cache = from_cache


def _extract_client_ip(request: Request) -> Optional[str]:
    """IP real considerando Nginx como reverse proxy."""
    return (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else None)
    )


async def _validate_api_key(imei: str, api_key: str) -> DeviceAuthResult:
    """
    Valida la API Key contra Redis (cache) y MongoDB.
    Solo se llama cuando el dispositivo envía el header X-Device-Key.
    """
    from app.services import redis_service
    settings = get_settings()

    # 1. Buscar en cache Redis
    cached = await redis_service.get_auth_cache(imei)
    if cached:
        AUTH_SUCCESS.labels(source="cache").inc()
        return DeviceAuthResult(authenticated=True, imei=imei, secured=True, from_cache=True)

    # 2. Buscar en MongoDB y verificar hash bcrypt
    from app.database.mongodb import get_dispositivos_collection
    from passlib.context import CryptContext

    pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    dispositivos_col = get_dispositivos_collection()
    device = await dispositivos_col.find_one({"imei": imei, "estado": 1}, {"_id": 0})

    if not device:
        AUTH_FAILURE.labels(reason="imei_not_registered").inc()
        return DeviceAuthResult(authenticated=False, imei=imei, secured=False, reason="imei_not_registered")

    stored_hash = device.get("api_key_hash")
    if not stored_hash:
        # Dispositivo registrado pero sin API Key asignada aún → trátar como legacy
        return DeviceAuthResult(authenticated=True, imei=imei, secured=False, reason="no_key_assigned")

    if not pwd_ctx.verify(api_key, stored_hash):
        AUTH_FAILURE.labels(reason="invalid_key").inc()
        return DeviceAuthResult(authenticated=False, imei=imei, secured=False, reason="invalid_key")

    # Válido → cachear
    await redis_service.set_auth_cache(imei, {"validated": True}, ttl=settings.redis_auth_cache_ttl)
    AUTH_SUCCESS.labels(source="database").inc()
    return DeviceAuthResult(authenticated=True, imei=imei, secured=True)


async def progressive_auth(
    request: Request,
    api_key: Optional[str] = Depends(_api_key_header),
) -> DeviceAuthResult:
    """
    Dependency FastAPI de Seguridad Progresiva.

    Acepta TODOS los dispositivos pero los clasifica:
      - Sin X-Device-Key        → secured=False (legacy, firmware sin actualizar)
      - Con X-Device-Key válida → secured=True  (nuevo firmware)
      - Con X-Device-Key inválida → secured=False + log (no se rechaza)

    Si ENABLE_AUTH=false en .env, bypass completo (modo desarrollo).
    """
    settings = get_settings()
    client_ip = _extract_client_ip(request)

    # Bypass completo en modo desarrollo
    if not settings.enable_auth:
        return DeviceAuthResult(authenticated=True, imei="", secured=False, reason="auth_disabled")

    # Sin API Key → dispositivo legacy
    if not api_key:
        DEVICES_LEGACY.inc()
        logger.debug("Dispositivo legacy sin API Key", ip=client_ip)
        return DeviceAuthResult(authenticated=True, imei="", secured=False, reason="legacy_no_key")

    # Con API Key → intentar validar
    # El IMEI se extrae del body sin consumirlo (FastAPI cachea request.json())
    try:
        body = await request.json()
        imei = str(body.get("i", "")).strip()
    except Exception:
        DEVICES_LEGACY.inc()
        return DeviceAuthResult(authenticated=True, imei="", secured=False, reason="parse_error")

    if not imei or not api_key.startswith("tk_"):
        DEVICES_LEGACY.inc()
        return DeviceAuthResult(authenticated=True, imei=imei, secured=False, reason="unknown_key_format")

    result = await _validate_api_key(imei=imei, api_key=api_key)

    if result.secured:
        DEVICES_SECURED.inc()
        logger.info("Dispositivo autenticado", imei=imei, from_cache=result.from_cache)
    else:
        # API Key inválida → no rechazar, degradar a legacy y loggear
        DEVICES_LEGACY.inc()
        logger.warning(
            "API Key inválida - aceptando como legacy",
            imei=imei,
            reason=result.reason,
            ip=client_ip,
        )

    return result
