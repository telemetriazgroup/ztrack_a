"""
Reenvío fire-and-forget de telemetría Generador a un servidor remoto.

No bloquea la recepción local: se programa con create_task y errores de red
solo se registran en log.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_client: Optional[httpx.AsyncClient] = None
_forward_sem: Optional[asyncio.Semaphore] = None
_MAX_CONCURRENT_FORWARDS = 32


def _get_client() -> httpx.AsyncClient:
    global _client
    settings = get_settings()
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.generador_forward_timeout_seconds),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
    return _client


def _get_sem() -> asyncio.Semaphore:
    global _forward_sem
    if _forward_sem is None:
        _forward_sem = asyncio.Semaphore(_MAX_CONCURRENT_FORWARDS)
    return _forward_sem


async def close_generador_forward_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None


async def _post_forward(payload: dict[str, Any]) -> None:
    settings = get_settings()
    url = settings.generador_forward_url
    imei = payload.get("i", "")

    async with _get_sem():
        try:
            response = await _get_client().post(url, json=payload)
            if response.status_code >= 400:
                logger.warning(
                    "Reenvío Generador: respuesta remota no OK",
                    status=response.status_code,
                    url=url,
                    imei=imei,
                )
        except Exception as exc:
            logger.warning(
                "Reenvío Generador falló (recepción local no afectada)",
                error=str(exc),
                url=url,
                imei=imei,
            )


def programar_reenvio_generador(payload: dict[str, Any]) -> None:
    """Encola POST remoto sin await — la línea de recepción sigue de inmediato."""
    settings = get_settings()
    if not settings.generador_forward_enabled:
        return

    try:
        asyncio.get_running_loop().create_task(
            _post_forward(payload),
            name="generador_forward",
        )
    except RuntimeError:
        logger.error("No hay event loop activo para reenvío Generador")

