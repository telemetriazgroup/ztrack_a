"""
app/functions/datos.py

Funciones de negocio para el módulo Datos.
Acoplado a la lógica del proyecto: Redis → batch_writer, guardar_datos compartido.
Colecciones: D_{imei}_MM_YYYY, D_dispositivos_MM_YYYY, D_control_MM_YYYY.
"""
from datetime import datetime
from typing import Optional

from app.core.logging import get_logger
from app.database.mongodb import (
    bd_gene,
    collection,
    get_control_collection,
    get_dispositivos_collection,
)
from app.functions.guardar_datos import guardar_datos

logger = get_logger(__name__)


async def Guardar_Datos(ztrack_data: dict, secured: bool = False) -> str:
    """Entry point del POST /Datos/. Delega a guardar_datos() con tipo="Datos"."""
    return await guardar_datos(ztrack_data, secured=secured, tipo_dispositivo="Datos")


async def insertar_comando(datos: dict) -> dict:
    """Inserta comando en D_control_MM_YYYY."""
    from app.core.datetime_utils import server_now
    control_col = get_control_collection("Datos")
    datos["fecha_creacion"] = server_now()
    if not datos.get("fecha_ejecucion"):
        datos["fecha_ejecucion"] = None
    result = await control_col.insert_one(datos)
    nuevo = await control_col.find_one({"_id": result.inserted_id}, {"_id": 0})
    return nuevo or {}


async def buscar_imei(datos: dict) -> list:
    """Busca registros en D_{imei}_MM_YYYY con filtro de fechas."""
    imei = datos.get("imei", "")
    col = collection(bd_gene(imei, "Datos"))
    query = {}
    fi = datos.get("fecha_inicio", "0")
    ff = datos.get("fecha_fin", "0")
    if fi and fi != "0" and ff and ff != "0":
        try:
            query["fecha"] = {
                "$gte": datetime.strptime(fi, "%d-%m-%Y_%H-%M-%S"),
                "$lte": datetime.strptime(ff, "%d-%m-%Y_%H-%M-%S"),
            }
        except ValueError:
            pass
    cursor = col.find(query, {"_id": 0}).sort("fecha", -1).limit(100)
    return await cursor.to_list(length=100)


async def datos_totales(datos: dict) -> list:
    """Lista paginada de registros del dispositivo."""
    imei = datos.get("imei", "")
    col = collection(bd_gene(imei, "Datos"))
    cursor = col.find({}, {"_id": 0}).sort("fecha", -1).limit(500)
    return await cursor.to_list(length=500)


async def buscar_live(datos: dict) -> Optional[dict]:
    """Último registro del dispositivo (vista en vivo)."""
    imei = datos.get("imei", "")
    col = collection(bd_gene(imei, "Datos"))
    return await col.find_one({}, {"_id": 0}, sort=[("fecha", -1)])
