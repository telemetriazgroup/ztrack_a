"""
Persistencia directa de tramas en MongoDB (fallback cuando Redis no está disponible).
"""
from datetime import datetime

from app.core.datetime_utils import server_now
from app.core.logging import get_logger
from app.database.mongodb import bd_gene, collection

logger = get_logger(__name__)


def normalize_trama_datetimes(doc: dict) -> None:
    """Normaliza fecha/received_at (p. ej. tras serialización JSON en Redis)."""
    now = server_now()
    raw = doc.get("received_at") or doc.get("fecha") or now
    if isinstance(raw, datetime):
        dt = raw
    else:
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            dt = now
    doc["fecha"] = dt
    doc["received_at"] = dt
    doc.setdefault("estado", 1)


async def insert_trama_direct(doc: dict, tipo_dispositivo: str) -> bool:
    """
    insert_one en TK_{imei}_MM_YYYY o TUNEL_{imei}_MM_YYYY.
    Usado cuando falla enqueue a Redis.
    """
    imei = doc.get("i", "")
    if not imei:
        return False

    normalize_trama_datetimes(doc)
    col_name = bd_gene(imei, tipo_dispositivo, doc.get("received_at"))
    col = collection(col_name)
    try:
        await col.insert_one(doc)
        logger.warning(
            "Trama persistida por fallback MongoDB (Redis no disponible)",
            imei=imei,
            coleccion=col_name,
            tipo=tipo_dispositivo,
        )
        return True
    except Exception as e:
        logger.error(
            "Fallback MongoDB falló",
            imei=imei,
            coleccion=col_name,
            error=str(e),
        )
        return False
