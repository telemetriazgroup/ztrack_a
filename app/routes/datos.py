"""
app/routes/datos.py

Rutas del módulo Datos.
Colecciones: D_{imei}_MM_YYYY, D_dispositivos_MM_YYYY, D_control_MM_YYYY.
"""
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.encoders import jsonable_encoder

from app.core.datetime_utils import server_now
from app.functions.datos import (
    Guardar_Datos,
    buscar_comandos_datos,
    buscar_imei_datos,
    buscar_live,
    datos_totales,
    insertar_comando,
    listar_dispositivos_datos,
    reporte_dispositivos_datos,
    reporte_dispositivos_datos_global,
)
from app.models.datos import (
    DatosSchema,
    DatosBuscarComandosSchema,
    DatosBuscarImeiSchema,
    DatosDispositivosPeriodoSchema,
    DatosDispositivosRangoSchema,
)
from app.models.common import ResponseModel, BusquedaSchema, ComandoSchema
from app.middleware.auth import progressive_auth

router = APIRouter()


@router.post("/", response_description="Datos agregados a la base de datos.")
async def add_data(
    datos: DatosSchema = Body(...),
    device=Depends(progressive_auth),
):
    """Recepción de telemetría Datos (D_{imei}_MM_YYYY)."""
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
    response_description="Listar comandos en D_control (últimas 12 h o rango de fechas).",
)
async def buscar_comandos_datos_ok(
    filtro: Annotated[DatosBuscarComandosSchema, Body()] = DatosBuscarComandosSchema(),
):
    """
    Consulta **D_control_MM_YYYY** para cada mes que cubra el intervalo.

    - Sin fechas: últimas **12 horas** (`fecha_creacion`).
    - Con ambas: rango inclusivo (hasta ~24 meses). ISO o `dd-mm-yyyy_hh-mm-ss`.
    - **imei** opcional.
    """
    try:
        return await buscar_comandos_datos(
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


@router.post("/imei/", response_description="Tramas por IMEI (12 h o rango; cruza D_{imei}_mes_año).")
async def buscar_imei_ok(filtro: DatosBuscarImeiSchema = Body(...)):
    """
    Colecciones **D_{imei}_MM_YYYY** por cada mes del intervalo.

    - Solo **imei**: últimas **12 horas** (`fecha`).
    - **fecha_inicio** y **fecha_fin**: rango inclusivo; ISO o `dd-mm-yyyy_hh-mm-ss`.
    """
    try:
        return await buscar_imei_datos(
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
    response_description="Lista equipos Datos en D_dispositivos_MES_AÑO.",
)
async def listar_dispositivos_datos_ok(
    periodo: Annotated[DatosDispositivosPeriodoSchema, Body()] = DatosDispositivosPeriodoSchema(),
):
    """Equipos con estado=1 en la colección mensual (mes/año actual si omiten campos)."""
    return await listar_dispositivos_datos(mes=periodo.mes, anio=periodo.anio)


@router.post(
    "/dispositivos/reporte/",
    response_description="Reporte online / wait / offline según ultimo_dato.",
)
async def reporte_dispositivos_datos_ok(
    periodo: Annotated[DatosDispositivosPeriodoSchema, Body()] = DatosDispositivosPeriodoSchema(),
):
    return await reporte_dispositivos_datos(mes=periodo.mes, anio=periodo.anio)


@router.post(
    "/dispositivos/reporte-global/",
    response_description="Reporte online/wait/offline cruzando varios meses (D_dispositivos).",
)
async def reporte_dispositivos_datos_global_ok(
    rango: DatosDispositivosRangoSchema = Body(...),
):
    """
    Recorre **D_dispositivos_MM_YYYY** entre mes_desde y mes_hasta (inclusivo).
    Por IMEI se usa el registro con **ultimo_dato** más reciente entre meses.
    """
    return await reporte_dispositivos_datos_global(
        mes_desde=rango.mes_desde,
        anio_desde=rango.anio_desde,
        mes_hasta=rango.mes_hasta,
        anio_hasta=rango.anio_hasta,
    )
