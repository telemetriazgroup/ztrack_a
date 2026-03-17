"""
app/functions/tunel.py

Funciones de negocio para el módulo Túnel.
Mismo patrón que termoking.py pero para dispositivos de túnel de frío.
"""
from datetime import datetime
from typing import Optional

from app.core.logging import get_logger
from app.database.mongodb import bd_gene, collection, get_control_collection
from app.functions.guardar_datos import guardar_datos

logger = get_logger(__name__)


async def Guardar_Datos(ztrack_data: dict, secured: bool = False) -> str:
    """Entry point del POST /Tunel/. Delega a guardar_datos() con tipo="Tunel"."""
    return await guardar_datos(ztrack_data, secured=secured, tipo_dispositivo="Tunel")


async def insertar_comando(datos: dict) -> dict:
    control_col = get_control_collection()
    datos["fecha_creacion"] = datetime.now()
    if not datos.get("fecha_ejecucion"):
        datos["fecha_ejecucion"] = None
    result = await control_col.insert_one(datos)
    nuevo = await control_col.find_one({"_id": result.inserted_id}, {"_id": 0})
    return nuevo or {}


async def buscar_imei(datos: dict) -> list:
    imei = datos.get("imei", "")
    col = collection(bd_gene(imei))
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
    imei = datos.get("imei", "")
    col = collection(bd_gene(imei))
    cursor = col.find({}, {"_id": 0}).sort("fecha", -1).limit(500)
    return await cursor.to_list(length=500)


async def datos_totales_ok(datos: dict) -> list:
    imei = datos.get("imei", "")
    col = collection(bd_gene(imei))
    cursor = col.find({}, {"_id": 0, "i": 1, "estado": 1, "fecha": 1}).sort("fecha", -1).limit(200)
    return await cursor.to_list(length=200)


async def grafica_total(datos: dict) -> list:
    return await datos_totales(datos)


async def grafica_total_ok(datos: dict) -> list:
    return await datos_totales_ok(datos)


async def buscar_live(datos: dict) -> Optional[dict]:
    imei = datos.get("imei", "")
    col = collection(bd_gene(imei))
    return await col.find_one({}, {"_id": 0}, sort=[("fecha", -1)])


async def Procesar_Trama() -> dict:
    return {"status": "ok", "mensaje": "Procesamiento de tramas Túnel programado"}


async def procesar_data_termoking() -> dict:
    return {"status": "ok", "mensaje": "Pre-procesamiento Túnel"}
