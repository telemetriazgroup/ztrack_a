"""
app/middleware/auth.py — Seguridad Progresiva para ZTRACK.
"""
from typing import Callable, Optional, Type, TypeVar

from fastapi import Body, Depends
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import AUTH_FAILURE, AUTH_SUCCESS, DEVICES_LEGACY, DEVICES_SECURED

logger = get_logger(__name__)

_api_key_header = APIKeyHeader(name="X-Device-Key", auto_error=False)

T = TypeVar("T", bound=BaseModel)


class DeviceAuthResult:
    """Resultado de la evaluación de seguridad."""

    def __init__(
        self,
        authenticated: bool = True,
        imei: str = "",
        secured: bool = False,
        reason: Optional[str] = None,
        from_cache: bool = False,
        tipo_dispositivo: str = "TermoKing",
    ):
        self.authenticated = authenticated
        self.imei = imei
        self.secured = secured
        self.reason = reason
        self.from_cache = from_cache
        self.tipo_dispositivo = tipo_dispositivo


async def _find_device_record(imei: str, tipo: str) -> Optional[dict]:
    """Busca dispositivo en la colección mensual del tipo; respaldo en el otro tipo."""
    from app.database.mongodb import get_dispositivos_collection

    col = get_dispositivos_collection(tipo)
    device = await col.find_one({"imei": imei, "estado": 1}, {"_id": 0})
    if device:
        return device

    if tipo not in ("TermoKing", "Tunel"):
        return None

    otro = "Tunel" if tipo == "TermoKing" else "TermoKing"
    col_otro = get_dispositivos_collection(otro)
    return await col_otro.find_one({"imei": imei, "estado": 1}, {"_id": 0})


async def _validate_api_key(imei: str, api_key: str, tipo: str) -> DeviceAuthResult:
    """Valida API Key contra Redis (cache) y MongoDB (colección del tipo)."""
    from passlib.context import CryptContext

    from app.services import redis_service

    settings = get_settings()
    cache_key = f"{tipo}:{imei}"

    cached = await redis_service.get_auth_cache(cache_key)
    if cached:
        AUTH_SUCCESS.labels(source="cache").inc()
        return DeviceAuthResult(
            authenticated=True,
            imei=imei,
            secured=True,
            from_cache=True,
            tipo_dispositivo=tipo,
        )

    pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    device = await _find_device_record(imei, tipo)

    if not device:
        AUTH_FAILURE.labels(reason="imei_not_registered").inc()
        return DeviceAuthResult(
            authenticated=False,
            imei=imei,
            secured=False,
            reason="imei_not_registered",
            tipo_dispositivo=tipo,
        )

    stored_hash = device.get("api_key_hash")
    if not stored_hash:
        return DeviceAuthResult(
            authenticated=True,
            imei=imei,
            secured=False,
            reason="no_key_assigned",
            tipo_dispositivo=tipo,
        )

    if not pwd_ctx.verify(api_key, stored_hash):
        AUTH_FAILURE.labels(reason="invalid_key").inc()
        return DeviceAuthResult(
            authenticated=False,
            imei=imei,
            secured=False,
            reason="invalid_key",
            tipo_dispositivo=tipo,
        )

    await redis_service.set_auth_cache(
        cache_key,
        {"validated": True, "tipo": tipo},
        ttl=settings.redis_auth_cache_ttl,
    )
    AUTH_SUCCESS.labels(source="database").inc()
    return DeviceAuthResult(
        authenticated=True,
        imei=imei,
        secured=True,
        tipo_dispositivo=tipo,
    )


async def evaluate_progressive_auth(
    *,
    imei: str,
    api_key: Optional[str],
    tipo_dispositivo: str,
    client_ip: Optional[str] = None,
) -> DeviceAuthResult:
    """
    Clasifica el dispositivo (legacy vs secured) sin re-leer el body HTTP.
    """
    settings = get_settings()

    if not settings.enable_auth:
        return DeviceAuthResult(
            authenticated=True,
            imei=imei,
            secured=False,
            reason="auth_disabled",
            tipo_dispositivo=tipo_dispositivo,
        )

    if not api_key:
        DEVICES_LEGACY.inc()
        return DeviceAuthResult(
            authenticated=True,
            imei=imei,
            secured=False,
            reason="legacy_no_key",
            tipo_dispositivo=tipo_dispositivo,
        )

    imei_clean = (imei or "").strip()
    if not imei_clean or not api_key.startswith("tk_"):
        DEVICES_LEGACY.inc()
        return DeviceAuthResult(
            authenticated=True,
            imei=imei_clean,
            secured=False,
            reason="unknown_key_format",
            tipo_dispositivo=tipo_dispositivo,
        )

    result = await _validate_api_key(imei=imei_clean, api_key=api_key, tipo=tipo_dispositivo)

    if result.secured:
        DEVICES_SECURED.inc()
        logger.info(
            "Dispositivo autenticado",
            imei=imei_clean,
            tipo=tipo_dispositivo,
            from_cache=result.from_cache,
        )
    else:
        DEVICES_LEGACY.inc()
        logger.warning(
            "API Key inválida - aceptando como legacy",
            imei=imei_clean,
            tipo=tipo_dispositivo,
            reason=result.reason,
            ip=client_ip,
        )

    return result


def make_progressive_auth(schema_cls: Type[T], tipo_dispositivo: str) -> Callable:
    """
    Dependency factory: valida el body con schema_cls y auth por tipo de módulo.
    """

    async def _progressive_auth(
        datos: schema_cls = Body(...),
        api_key: Optional[str] = Depends(_api_key_header),
    ) -> DeviceAuthResult:
        return await evaluate_progressive_auth(
            imei=datos.i,
            api_key=api_key,
            tipo_dispositivo=tipo_dispositivo,
        )

    return _progressive_auth
