"""
app/routes/starcool.py

Rutas del módulo Starcool.
Colecciones: S_{imei}_MM_YYYY, S_dispositivos_MM_YYYY, S_control_MM_YYYY.
"""
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException

from fastapi.encoders import jsonable_encoder

from app.core.datetime_utils import server_now
from app.functions.starcool import (
    Guardar_Datos,
    buscar_comandos_starcool,
    buscar_imei_starcool,
    buscar_live,
    datos_totales,
    insertar_comando,
    listar_dispositivos_starcool,
    reporte_dispositivos_starcool,
    reporte_dispositivos_starcool_global,
)
from app.models.starcool import (
    StarcoolSchema,
    StarcoolBuscarComandosSchema,
    StarcoolBuscarImeiSchema,
    StarcoolDispositivosPeriodoSchema,
    StarcoolDispositivosRangoSchema,
)
from app.models.common import ResponseModel, BusquedaSchema, ComandoSchema
from app.middleware.auth import progressive_auth

router = APIRouter()


@router.post("/", response_description="Datos Starcool agregados a la base de datos.")
async def add_data(
    datos: StarcoolSchema = Body(...),
    device=Depends(progressive_auth),
):
    """Recepción de telemetría Starcool (S_{imei}_MM_YYYY)."""
    received_at = server_now()
    doc = datos.to_mongo_document(received_at=received_at, secured=device.secured)
    comando = await Guardar_Datos(doc, secured=device.secured)
    return {
        "status": "ok",
        "imei": datos.i,
        "secured": device.secured,
        "comando": comando,
        "received_at": received_at.isoformat(),
    }


@router.post(
    "/comando/buscar/",
    response_description="Listar comandos en S_control (últimas 12 h o rango de fechas).",
)
async def buscar_comandos_starcool_ok(
    filtro: Annotated[StarcoolBuscarComandosSchema, Body()] = StarcoolBuscarComandosSchema(),
):
    """
    Consulta **S_control_MM_YYYY** para cada mes que cubra el intervalo.

    - Sin **fecha_inicio** / **fecha_fin**: últimas **12 horas** según `fecha_creacion`.
    - Con ambas: rango inclusivo (hasta ~24 meses). Formatos: ISO 8601 o `dd-mm-yyyy_hh-mm-ss`.
    - **imei** opcional para filtrar un dispositivo.
    """
    try:
        return await buscar_comandos_starcool(
            imei=filtro.imei,
            fecha_inicio=filtro.fecha_inicio,
            fecha_fin=filtro.fecha_fin,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/comando/", response_description="Insertar comando.")
async def add_comando(datos: ComandoSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await insertar_comando(datos)


@router.post("/imei/", response_description="Tramas por IMEI (12 h o rango; cruza S_{imei}_mes_año).")
async def buscar_imei_ok(filtro: StarcoolBuscarImeiSchema = Body(...)):
    """
    Lee colecciones **S_{imei}_MM_YYYY** para cada mes que cubra el intervalo.

    - Solo **imei**: últimas **12 horas** (`fecha` entre ahora−12h y ahora).
    - **fecha_inicio** y **fecha_fin**: rango inclusivo; formatos ISO o `dd-mm-yyyy_hh-mm-ss`.
    """
    try:
        return await buscar_imei_starcool(
            imei=filtro.imei,
            fecha_inicio=filtro.fecha_inicio,
            fecha_fin=filtro.fecha_fin,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/ListarTabla/", response_description="Listar tabla.")
async def buscar_tabla_ok(datos: BusquedaSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await datos_totales(datos)


@router.post("/live/", response_description="Datos en vivo.")
async def buscar_live_ok(datos: BusquedaSchema = Body(...)):
    datos = jsonable_encoder(datos)
    result = await buscar_live(datos)
    return ResponseModel(result, "Último dato recuperado." if result else "Sin datos.")


@router.post(
    "/dispositivos/listar/",
    response_description="Lista equipos Starcool en S_dispositivos_MES_AÑO.",
)
async def listar_dispositivos_starcool_ok(
    periodo: Annotated[StarcoolDispositivosPeriodoSchema, Body()] = StarcoolDispositivosPeriodoSchema(),
):
    """
    Equipos dados de alta con estado=1 en la colección mensual indicada.
    Sin mes/año en el cuerpo se usa el mes y año actuales (APP_TIMEZONE).
    """
    return await listar_dispositivos_starcool(mes=periodo.mes, anio=periodo.anio)


@router.post(
    "/dispositivos/reporte/",
    response_description="Reporte online / wait / offline según ultimo_dato.",
)
async def reporte_dispositivos_starcool_ok(
    periodo: Annotated[StarcoolDispositivosPeriodoSchema, Body()] = StarcoolDispositivosPeriodoSchema(),
):
    """
    - **online**: `ultimo_dato` dentro de la última hora.
    - **wait**: entre 1 y 24 horas sin datos.
    - **offline**: más de 24 horas o sin fecha usable.

    La referencia temporal es `server_now()` (APP_TIMEZONE, mismo criterio que el resto de la API).
    """
    return await reporte_dispositivos_starcool(mes=periodo.mes, anio=periodo.anio)


@router.post(
    "/dispositivos/reporte-global/",
    response_description="Reporte online/wait/offline cruzando varios meses (S_dispositivos).",
)
async def reporte_dispositivos_starcool_global_ok(rango: StarcoolDispositivosRangoSchema = Body(...)):
    """
    Recorre cada `S_dispositivos_MM_YYYY` entre **mes_desde/anio_desde** y **mes_hasta/anio_hasta** (inclusivo).

    Si un IMEI aparece en varios meses, se usa el registro con **`ultimo_dato`** más reciente
    para clasificar online / wait / offline.

    Límite: 36 meses de rango (validado en el modelo).
    """
    return await reporte_dispositivos_starcool_global(
        mes_desde=rango.mes_desde,
        anio_desde=rango.anio_desde,
        mes_hasta=rango.mes_hasta,
        anio_hasta=rango.anio_hasta,
    )
