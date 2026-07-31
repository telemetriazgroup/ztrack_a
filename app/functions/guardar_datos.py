"""
app/functions/guardar_datos.py

Implementa la función Guardar_Datos central, compartida por TermoKing y Tunel.
"""
import asyncio
from typing import Optional

from pymongo import ReturnDocument

from app.core.datetime_utils import server_now
from app.core.logging import get_logger
from app.core.metrics import (
    CONTROL_COMMANDS_DISPATCHED,
    DEVICE_AUTO_REGISTERED,
    MONGO_INSERT_ERRORS,
    REDIS_ENQUEUE_DURATION,
    REDIS_ERRORS,
    TELEMETRY_PERSIST,
)
from app.database.mongodb import (
    bd_gene,
    crear_indices_coleccion_dispositivo,
    get_control_collection,
    get_dispositivos_collection,
)
from app.functions.dashboard_equipos import registrar_equipo_por_ingesta
from app.functions.persist_trama import insert_trama_direct
from app.services import redis_service

logger = get_logger(__name__)

_MODULO_METRIC = {
    "TermoKing": "termoking",
    "Tunel": "tunel",
    "Starcool": "starcool",
}


async def guardar_datos(
    ztrack_data: dict,
    secured: bool = False,
    tipo_dispositivo: str = "TermoKing",
) -> str:
    """
    Función central equivalente a Guardar_Datos() del sistema original.
    """
    imei = ztrack_data.get("i", "")
    if not imei:
        return "sin comandos pendientes"

    modulo = _MODULO_METRIC.get(tipo_dispositivo, "termoking")
    ztrack_data["tipo_dispositivo"] = tipo_dispositivo

    await redis_service.register_imei_tipo(tipo_dispositivo, imei)

    # ── 1. Encolar en Redis; fallback síncrono a MongoDB si falla ───────────
    with REDIS_ENQUEUE_DURATION.time():
        enqueued = await redis_service.enqueue(ztrack_data)

    if enqueued:
        TELEMETRY_PERSIST.labels(modulo=modulo, path="redis").inc()
    else:
        REDIS_ERRORS.labels(operation="enqueue").inc()
        persisted = await insert_trama_direct(ztrack_data, tipo_dispositivo)
        if persisted:
            TELEMETRY_PERSIST.labels(modulo=modulo, path="mongo_fallback").inc()
        else:
            TELEMETRY_PERSIST.labels(modulo=modulo, path="failed").inc()
            MONGO_INSERT_ERRORS.inc()
            logger.error(
                "Trama no persistida (Redis caído y fallback Mongo falló)",
                imei=imei,
                tipo=tipo_dispositivo,
            )

    # ── 2. Sincronizar dispositivos + despachar comando (en paralelo) ───────
    _, comando = await asyncio.gather(
        _sync_dispositivos(
            imei=imei,
            ztrack_data=ztrack_data,
            secured=secured,
            tipo=tipo_dispositivo,
        ),
        _get_and_dispatch_command(imei=imei, tipo=tipo_dispositivo),
    )

    return comando


async def _sync_dispositivos(
    imei: str,
    ztrack_data: dict,
    secured: bool,
    tipo: str = "TermoKing",
) -> None:
    """Sincroniza en TK_dispositivos_MM_YYYY o TUNEL_dispositivos_MM_YYYY."""
    dispositivos_col = get_dispositivos_collection(tipo)
    ip_raw = ztrack_data.get("ip", "")
    ip_clean = ip_raw.split(",")[0].strip() if ip_raw else None

    dispositivo_encontrado = await dispositivos_col.find_one(
        {"imei": imei, "estado": 1}, {"_id": 0}
    )

    es_nuevo_en_mes = False
    if dispositivo_encontrado:
        update_fields = {"ultimo_dato": server_now()}
        if ip_clean:
            update_fields["last_ip"] = ip_clean
        if secured and not dispositivo_encontrado.get("secured", False):
            update_fields["secured"] = True
            logger.info("Dispositivo migrado a modo seguro", imei=imei)

        await dispositivos_col.update_one(
            {"imei": imei, "estado": 1},
            {"$set": update_fields},
        )
    else:
        now = server_now()
        try:
            await dispositivos_col.insert_one({
                "imei": imei,
                "estado": 1,
                "fecha": now,
                "tipo": tipo,
                "ultimo_dato": now,
                "last_ip": ip_clean,
                "secured": secured,
                "api_key_hash": None,
            })
            es_nuevo_en_mes = True
            DEVICE_AUTO_REGISTERED.labels(tipo=tipo).inc()
            col_name = bd_gene(imei, tipo)
            await crear_indices_coleccion_dispositivo(col_name)
            logger.info("Dispositivo auto-registrado", imei=imei, tipo=tipo, secured=secured)
        except Exception as e:
            if "duplicate key" not in str(e).lower():
                logger.error("Error al auto-registrar dispositivo", imei=imei, error=str(e))

    try:
        await registrar_equipo_por_ingesta(imei, tipo, es_nuevo_en_mes=es_nuevo_en_mes)
    except Exception as e:
        logger.warning("Catálogo dashboard no actualizado", imei=imei, tipo=tipo, error=str(e))


async def _get_and_dispatch_command(imei: str, tipo: str = "TermoKing") -> str:
    """
    Despacho atómico: find_one_and_update evita doble entrega con varios workers.
    """
    modulo = _MODULO_METRIC.get(tipo, "termoking")
    control_col = get_control_collection(tipo)
    now = server_now()

    try:
        control_encontrado = await control_col.find_one_and_update(
            {"imei": imei, "estado": {"$gt": 0}},
            {
                "$inc": {"estado": -1},
                "$set": {
                    "status": 2,
                    "fecha_ejecucion": now,
                },
            },
            return_document=ReturnDocument.BEFORE,
            projection={"_id": 0, "comando": 1, "estado": 1},
        )

        if not control_encontrado:
            return "sin comandos pendientes"

        comando = control_encontrado.get("comando") or "sin comandos pendientes"
        if not comando or comando == "sin comandos pendientes":
            return "sin comandos pendientes"

        estado_antes = control_encontrado.get("estado", 1)
        intentos_restantes = max(estado_antes - 1, 0)

        CONTROL_COMMANDS_DISPATCHED.labels(modulo=modulo).inc()
        logger.info(
            "Comando despachado",
            imei=imei,
            comando=comando,
            intentos_restantes=intentos_restantes,
            tipo=tipo,
        )
        return comando

    except Exception as e:
        logger.error("Error al consultar comandos", imei=imei, error=str(e))
        return "sin comandos pendientes"
