"""
app/functions/termoking.py

Funciones de negocio para el módulo TermoKing.
Portadas del original server/functions/termoking.py.

Las funciones de consulta (buscar_imei, datos_totales, grafica_total, etc.)
mantienen la misma firma y lógica. Solo cambia el origen de las colecciones:
  ANTES: from server.database import collection → colección de Motor
  AHORA: from app.database.mongodb import collection → colección de PyMongo async

La API de las colecciones es idéntica (async, mismos métodos find/find_one/etc.)
por lo que el código de consultas no requiere cambios.

ESTRUCTURA:
  - Guardar_Datos()         → delega a guardar_datos() compartido
  - insertar_comando()      → inserta en colección 'control'
  - buscar_imei()           → consulta colección del dispositivo
  - datos_totales()         → lista paginada con fechas
  - grafica_total()         → datos para gráfica
  - buscar_live()           → último dato del dispositivo
  - consultar_trama_ultimo()
  - ultimo_estado_dispositivos_termoking()
  - [funciones de análisis de trama - stubs pendientes de lógica propietaria]
"""
from datetime import datetime
from typing import Any, Optional

from bson.objectid import ObjectId

from app.core.datetime_utils import server_now
from app.core.logging import get_logger
from app.database.mongodb import (
    bd_gene,
    collection,
    get_control_collection,
    get_dispositivos_collection,
    guardar_evento_telemetria,
)
from app.functions.guardar_datos import guardar_datos
from app.functions.decodificado_queries import (
    buscar_decodificado_imei_rango,
    buscar_live_oficial_parcial,
)
from app.functions.live_helpers import buscar_live_telemetria_parcial
from app.functions.device_queries import (
    buscar_comandos_control_multimes,
    buscar_imei_multimes,
    dispositivos_periodo_multimes,
    dispositivos_reporte_clasificado,
    reporte_global_dispositivos_multimes,
)

logger = get_logger(__name__)

_TIPO = "TermoKing"


# ── RECEPCIÓN DE DATOS ───────────────────────────────────────────────────────

async def Guardar_Datos(ztrack_data: dict, secured: bool = False) -> str:
    """
    Entry point del POST /TermoKing/.
    Delega a la función compartida guardar_datos() con tipo="TermoKing".
    """
    return await guardar_datos(ztrack_data, secured=secured, tipo_dispositivo="TermoKing")


# ── COMANDOS DE CONTROL ──────────────────────────────────────────────────────

async def insertar_comando(datos: dict) -> dict:
    """
    Inserta un comando de control en TK_control_MM_YYYY.
    El comando se retorna al dispositivo en la próxima llamada POST.
    """
    control_col = get_control_collection("TermoKing")
    datos["fecha_creacion"] = server_now()
    if not datos.get("fecha_ejecucion"):
        datos["fecha_ejecucion"] = None

    result = await control_col.insert_one(datos)
    nuevo = await control_col.find_one({"_id": result.inserted_id}, {"_id": 0})
    return nuevo or {}


# ── CONSULTAS DE DISPOSITIVO ─────────────────────────────────────────────────

async def buscar_imei(datos: dict) -> list:
    """
    Busca tramas por IMEI en TK_{imei}_MM_YYYY, recorriendo varios meses si el rango lo cruza.
    Sin fechas (o "0"): últimas 12 h. Con mes_desde/anio_desde/mes_hasta/anio_hasta: rango por meses.
    """
    return await buscar_imei_multimes(_TIPO, datos)


async def buscar_comandos_termoking(datos: dict) -> dict:
    """Comandos en TK_control_* con el mismo criterio de fechas / meses."""
    return await buscar_comandos_control_multimes(_TIPO, datos)


async def dispositivos_periodo_termoking(datos: dict) -> dict:
    """Lista dispositivos en TK_dispositivos_* en el rango indicado."""
    return await dispositivos_periodo_multimes(_TIPO, datos)


async def reporte_global_termoking(datos: dict) -> dict:
    """Resumen agregado de dispositivos en el periodo."""
    return await reporte_global_dispositivos_multimes(_TIPO, datos)


async def dispositivos_reporte_termoking(datos: dict) -> dict:
    """Clasificación online / wait / offline en TK_dispositivos_MM_YYYY."""
    return await dispositivos_reporte_clasificado(_TIPO, datos)


async def buscar_live_decodificado(datos: dict) -> dict:
    """Último dato en {IMEI}_OFICIAL_{año}; búsqueda parcial ≥5 caracteres vía Redis."""
    return await buscar_live_oficial_parcial(datos, "TermoKing")


async def buscar_imei_decodificado(datos: dict) -> dict:
    """Rango de fechas en colecciones OFICIAL por año (12 h por defecto sin fechas)."""
    return await buscar_decodificado_imei_rango(datos)


async def datos_totales(datos: dict) -> list:
    """Lista paginada de registros del dispositivo."""
    imei = datos.get("imei", "")
    col = collection(bd_gene(imei, "TermoKing"))
    fecha_inicio = datos.get("fecha_inicio", "0")
    fecha_fin = datos.get("fecha_fin", "0")

    query = {}
    if fecha_inicio and fecha_inicio != "0":
        try:
            fi = datetime.strptime(fecha_inicio, "%d-%m-%Y_%H-%M-%S")
            ff = datetime.strptime(fecha_fin, "%d-%m-%Y_%H-%M-%S")
            query["fecha"] = {"$gte": fi, "$lte": ff}
        except ValueError:
            pass

    cursor = col.find(query, {"_id": 0}).sort("fecha", -1).limit(500)
    return await cursor.to_list(length=500)


async def datos_totales_ok(datos: dict) -> list:
    """Alias de datos_totales con proyección reducida para dashboard."""
    imei = datos.get("imei", "")
    col = collection(bd_gene(imei, "TermoKing"))
    cursor = col.find({}, {"_id": 0, "i": 1, "estado": 1, "fecha": 1, "d02": 1, "d03": 1}).sort("fecha", -1).limit(200)
    return await cursor.to_list(length=200)


async def grafica_total(datos: dict) -> list:
    """Datos preparados para gráfica de línea."""
    return await datos_totales(datos)


async def grafica_total_ok(datos: dict) -> list:
    """Datos reducidos para gráfica del dashboard."""
    return await datos_totales_ok(datos)


async def buscar_live(datos: dict) -> Any:
    """Última trama TK_*; IMEI parcial ≥5 caracteres vía Redis + dispositivos."""
    return await buscar_live_telemetria_parcial(datos, "TermoKing")


async def consultar_trama_ultimo(imei: str) -> Optional[dict]:
    """Retorna la última trama del dispositivo."""
    col = collection(bd_gene(imei, "TermoKing"))
    return await col.find_one({}, {"_id": 0}, sort=[("fecha", -1)])


async def datos_general(datos: dict) -> list:
    """Consulta general con rango de fechas y límite configurable."""
    imei = datos.get("imei", "")
    limit = datos.get("limit", 100)
    col = collection(bd_gene(imei, "TermoKing"))
    start_date = datos.get("start_date", "0")
    end_date = datos.get("end_date", "0")

    query = {}
    if start_date and start_date != "0" and end_date and end_date != "0":
        try:
            fi = datetime.strptime(start_date, "%d-%m-%Y_%H-%M-%S")
            ff = datetime.strptime(end_date, "%d-%m-%Y_%H-%M-%S")
            query["fecha"] = {"$gte": fi, "$lte": ff}
        except ValueError:
            pass

    cursor = col.find(query, {"_id": 0}).sort("fecha", -1).limit(limit)
    return await cursor.to_list(length=limit)


async def consultar_starcool_cerro_prieto(datos: dict) -> list:
    """Consulta específica para dispositivos Starcool."""
    return await datos_general(datos)


# ── ESTADO GLOBAL DE DISPOSITIVOS ───────────────────────────────────────────

async def ultimo_estado_dispositivos_termoking() -> list:
    """
    Retorna el resumen y último estado de todos los dispositivos TermoKing.
    Consulta TK_dispositivos_MM_YYYY y para cada uno obtiene la última trama de TK_{imei}_MM_YYYY.
    """
    dispositivos_col = get_dispositivos_collection("TermoKing")
    cursor = dispositivos_col.find(
        {"tipo": "TermoKing"},
        {"_id": 0, "imei": 1, "estado": 1, "tipo": 1, "ultimo_dato": 1, "last_ip": 1, "secured": 1}
    )
    dispositivos = await cursor.to_list(length=500)

    result = []
    for disp in dispositivos:
        imei = disp.get("imei", "")
        try:
            col = collection(bd_gene(imei, "TermoKing"))
            ultima_trama = await col.find_one({}, {"_id": 0}, sort=[("fecha", -1)])
            disp["ultima_trama"] = ultima_trama
        except Exception:
            disp["ultima_trama"] = None
        result.append(disp)

    return result


# ── FUNCIONES DE ANÁLISIS DE TRAMA ──────────────────────────────────────────
# Stubs: la lógica de decodificación del protocolo propietario va aquí.
# Se implementan como stubs para mantener la firma del router original.

async def Procesar_Trama() -> dict:
    """Procesa y decodifica tramas pendientes. Stub - implementar con lógica propietaria."""
    return {"status": "ok", "mensaje": "Procesamiento de tramas programado"}


async def procesar_data_termoking() -> dict:
    """Pre-procesamiento de datos TermoKing. Stub."""
    return {"status": "ok", "mensaje": "Pre-procesamiento TermoKing"}


async def controlar_etileno_miami_ics() -> dict:
    """Control de etileno Miami ICS. Stub."""
    return {"status": "ok", "mensaje": "Control de etileno"}


async def procesar_data_madurador_miami() -> dict:
    """Procesamiento de datos del madurador Miami. Stub."""
    return {"status": "ok", "mensaje": "Procesamiento madurador"}


async def procesos_madurador(datos: dict) -> dict:
    """Solicitar proceso al madurador. Stub."""
    return {"status": "ok", "mensaje": "Proceso solicitado", "datos": datos}


async def get_proceso(id: str) -> Optional[dict]:
    """Obtiene el estado de un proceso por ID. Stub."""
    return {"id": id, "status": "pending", "mensaje": "Proceso en ejecución"}
