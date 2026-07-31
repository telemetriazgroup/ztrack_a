"""
POST compartido de telemetría para TermoKing y Tunel.
"""
from typing import Any

from app.core.datetime_utils import server_now
from app.core.logging import get_logger
from app.core.metrics import (
    TELEMETRY_PAYLOAD_SIZE,
    TELEMETRY_PROCESSING_DURATION,
    TELEMETRY_RECEIVED,
)
from app.functions.guardar_datos import guardar_datos
from app.middleware.auth import DeviceAuthResult

logger = get_logger(__name__)

_MODULO_METRIC = {
    "TermoKing": "termoking",
    "Tunel": "tunel",
    "Starcool": "starcool",
}


async def handle_telemetry_post(
    datos: Any,
    device: DeviceAuthResult,
    tipo_dispositivo: str,
) -> dict:
    """
    Flujo unificado: documento Mongo → guardar_datos → respuesta al dispositivo.
    """
    modulo = _MODULO_METRIC.get(tipo_dispositivo, "termoking")
    received_at = server_now()

    with TELEMETRY_PROCESSING_DURATION.labels(modulo=modulo).time():
        doc = datos.to_mongo_document(received_at=received_at, secured=device.secured)
        try:
            payload_size = len(str(doc).encode("utf-8", errors="replace"))
            TELEMETRY_PAYLOAD_SIZE.observe(payload_size)
        except Exception:
            pass

        try:
            comando = await guardar_datos(
                doc,
                secured=device.secured,
                tipo_dispositivo=tipo_dispositivo,
            )
            TELEMETRY_RECEIVED.labels(modulo=modulo, status="ok").inc()
        except Exception:
            TELEMETRY_RECEIVED.labels(modulo=modulo, status="error").inc()
            logger.exception("Error en ingesta de telemetría", tipo=tipo_dispositivo, imei=datos.i)
            raise

    return {
        #"status": "ok",
        #"imei": datos.i,
        #"secured": device.secured,
        "comando": comando,
        #"received_at": received_at.isoformat(),
    }
