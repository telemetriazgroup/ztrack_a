"""
app/functions/generador.py

Funciones de negocio para el módulo Generador.
Acoplado a la lógica del proyecto: Redis → batch_writer, guardar_datos compartido.
Colecciones: G_{imei}_MM_YYYY, G_dispositivos_MM_YYYY, G_control_MM_YYYY.
"""
from datetime import datetime
from typing import Optional

from app.database.mongodb import (
    bd_gene,
    collection,
    get_control_collection,
)
from app.functions.guardar_datos import guardar_datos


async def Guardar_Datos(ztrack_data: dict, secured: bool = False) -> str:
    """Entry point del POST /Generador/. Delega a guardar_datos() con tipo="Generador"."""
    return await guardar_datos(ztrack_data, secured=secured, tipo_dispositivo="Generador")


async def insertar_comando(datos: dict) -> dict:
    """Inserta comando en G_control_MM_YYYY."""
    from app.core.datetime_utils import server_now
    control_col = get_control_collection("Generador")
    datos["fecha_creacion"] = server_now()
    if not datos.get("fecha_ejecucion"):
        datos["fecha_ejecucion"] = None
    result = await control_col.insert_one(datos)
    nuevo = await control_col.find_one({"_id": result.inserted_id}, {"_id": 0})
    return nuevo or {}


async def buscar_imei(datos: dict) -> list:
    """Busca registros en G_{imei}_MM_YYYY con filtro de fechas."""
    imei = datos.get("imei", "")
    col = collection(bd_gene(imei, "Generador"))
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
    col = collection(bd_gene(imei, "Generador"))
    cursor = col.find({}, {"_id": 0}).sort("fecha", -1).limit(500)
    return await cursor.to_list(length=500)


async def buscar_live(datos: dict) -> Optional[dict]:
    """Último registro del dispositivo (vista en vivo)."""
    imei = datos.get("imei", "")
    col = collection(bd_gene(imei, "Generador"))
    return await col.find_one({}, {"_id": 0}, sort=[("fecha", -1)])
