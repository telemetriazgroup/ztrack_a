"""
app/functions/guardar_datos.py

Implementa la función Guardar_Datos central, compartida por TermoKing y Tunel.

LÓGICA ORIGINAL (portada sin cambios funcionales):
  1. Guarda la trama en la colección del dispositivo (por IMEI)
  2. Verifica/registra el dispositivo en 'dispositivos'
  3. Busca y despacha comando pendiente de 'control'
  4. Retorna el comando (o "sin comandos pendientes")

ADAPTACIONES:
  - La persistencia de la trama va por cola Redis (no bloquea el response)
  - La consulta de comandos es SÍNCRONA (el dispositivo necesita la respuesta ya)
  - Se agrega el campo 'secured' al registro de dispositivo
  - Motor → PyMongo async (misma API, distinto import)

CÓMO FUNCIONA EL FLUJO COMPLETO:
  Dispositivo → POST /TermoKing/ → Guardar_Datos() → Redis queue → batch writer → MongoDB
                                       ↓ síncrono
                                  Consulta 'control'
                                       ↓
                                  Response con comando
"""
from datetime import datetime, timezone
from typing import Optional

from app.core.logging import get_logger
from app.database.mongodb import (
    bd_gene,
    collection,
    crear_indices_coleccion_dispositivo,
    get_control_collection,
    get_dispositivos_collection,
)
from app.services import redis_service

logger = get_logger(__name__)


async def guardar_datos(
    ztrack_data: dict,
    secured: bool = False,
    tipo_dispositivo: str = "TermoKing",
) -> str:
    """
    Función central equivalente a Guardar_Datos() del sistema original.

    Args:
        ztrack_data:      Documento MongoDB ya preparado (con received_at, secured, etc.)
        secured:          True si el dispositivo autenticó con API Key.
        tipo_dispositivo: "TermoKing" o "Tunel" (para el registro en 'dispositivos').

    Returns:
        String del comando a ejecutar, o "sin comandos pendientes".

    DIFERENCIA CON EL ORIGINAL:
      El original hacía insert_one directamente en MongoDB aquí.
      Ahora hacemos lpush a Redis y el batch writer persiste de forma asíncrona.
      Esto desacopla la recepción de la persistencia y elimina el bloqueo.
    """
    imei = ztrack_data.get("i", "")
    if not imei:
        return "sin comandos pendientes"

    # ── 1. Encolar trama en Redis (no bloqueante, < 1ms) ────────────────────
    # Equivale al: await data_collection.insert_one(ztrack_data) del original
    # pero sin bloquear el response al dispositivo.
    enqueued = await redis_service.enqueue(ztrack_data)
    if not enqueued:
        # Redis caído: modo degradado, se loggea pero no se rechaza
        logger.error("No se pudo encolar trama - Redis caído", imei=imei)

    # ── 2. Sincronizar colección 'dispositivos' ──────────────────────────────
    # Replica exactamente el bloque dispositivo_encontrado del original.
    await _sync_dispositivos(imei=imei, ztrack_data=ztrack_data, secured=secured, tipo=tipo_dispositivo)

    # ── 3. Consultar y despachar comando pendiente ───────────────────────────
    # Replica exactamente el bloque control_encontrado del original.
    # Es síncrono porque el dispositivo necesita el comando en esta respuesta.
    comando = await _get_and_dispatch_command(imei=imei)

    return comando


async def _sync_dispositivos(
    imei: str,
    ztrack_data: dict,
    secured: bool,
    tipo: str = "TermoKing",
) -> None:
    """
    Replica el bloque del original:

      dispositivo_encontrado = await dispositivos_collection.find_one({"imei": imei, "estado": 1})
      if dispositivo_encontrado:
          Hay_dispositivo = dispositivo_encontrado['imei']
      verificar_dispositivo = await dispositivos_collection.update_one(...)
          if Hay_dispositivo else await dispositivos_collection.insert_one(...)
    """
    dispositivos_col = get_dispositivos_collection()
    ip_raw = ztrack_data.get("ip", "")
    ip_clean = ip_raw.split(",")[0].strip() if ip_raw else None

    dispositivo_encontrado = await dispositivos_col.find_one(
        {"imei": imei, "estado": 1}, {"_id": 0}
    )

    if dispositivo_encontrado:
        # Existe → actualizar ultimo_dato (igual que el original)
        update_fields = {"ultimo_dato": datetime.now(timezone.utc)}
        if ip_clean:
            update_fields["last_ip"] = ip_clean
        # Migración silenciosa: si el dispositivo acaba de activar seguridad
        if secured and not dispositivo_encontrado.get("secured", False):
            update_fields["secured"] = True
            logger.info("Dispositivo migrado a modo seguro", imei=imei)

        await dispositivos_col.update_one(
            {"imei": imei, "estado": 1},
            {"$set": update_fields},
        )
    else:
        # No existe → auto-registrar (igual que el original)
        # Original: insert_one({"imei":..., "estado":1, "fecha":..., "tipo":"TermoKing"})
        now = datetime.now(timezone.utc)
        try:
            await dispositivos_col.insert_one({
                "imei": imei,
                "estado": 1,
                "fecha": now,
                "tipo": tipo,
                "ultimo_dato": now,
                "last_ip": ip_clean,
                "secured": secured,
                "api_key_hash": None,  # None hasta que tenga firmware actualizado
            })
            # Crear índices en la nueva colección del dispositivo
            col_name = bd_gene(imei)
            await crear_indices_coleccion_dispositivo(col_name)
            logger.info("Dispositivo auto-registrado", imei=imei, tipo=tipo, secured=secured)
        except Exception as e:
            if "duplicate key" not in str(e).lower():
                logger.error("Error al auto-registrar dispositivo", imei=imei, error=str(e))


async def _get_and_dispatch_command(imei: str) -> str:
    """
    Replica el bloque del original:

      control_encontrado = await control_collection.find_one({"imei": imei, "estado": 1})
      if control_encontrado:
          veces_control = control_encontrado['estado'] - 1 if control_encontrado['comando'] else 0
          comando = control_encontrado['comando']
          await control_collection.update_one(..., {"$set": {"estado": veces_control, "status": 2, ...}})
      return comando
    """
    control_col = get_control_collection()

    try:
        control_encontrado = await control_col.find_one(
            {"imei": imei, "estado": {"$gt": 0}},
            {"_id": 0},
        )

        if not control_encontrado:
            return "sin comandos pendientes"

        comando = control_encontrado.get("comando", "sin comandos pendientes")
        estado_actual = control_encontrado.get("estado", 1)

        # Mismo cálculo que el original
        veces_control = estado_actual - 1 if comando else 0

        await control_col.update_one(
            {"imei": imei, "estado": {"$gt": 0}},
            {"$set": {
                "estado": veces_control,
                "status": 2,                    # status=2: ejecutado
                "fecha_ejecucion": datetime.now(timezone.utc),
            }},
        )

        logger.info("Comando despachado", imei=imei, comando=comando, intentos_restantes=veces_control)
        return comando

    except Exception as e:
        logger.error("Error al consultar comandos", imei=imei, error=str(e))
        return "sin comandos pendientes"
