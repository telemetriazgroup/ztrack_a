"""
app/routes/generador.py

Rutas del módulo Generador.
Colecciones: G_{imei}_MM_YYYY, G_dispositivos_MM_YYYY, G_control_MM_YYYY.
"""
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.encoders import jsonable_encoder

from app.core.datetime_utils import server_now
from app.functions.generador import (
    Guardar_Datos,
    buscar_comandos_generador,
    buscar_imei_generador,
    buscar_live,
    datos_totales,
    insertar_comando,
    listar_dispositivos_generador,
    reporte_dispositivos_generador,
    reporte_dispositivos_generador_global,
)
from app.models.generador import (
    GeneradorSchema,
    GeneradorBuscarComandosSchema,
    GeneradorBuscarImeiSchema,
    GeneradorDispositivosPeriodoSchema,
    GeneradorDispositivosRangoSchema,
)
from app.models.common import ResponseModel, BusquedaSchema, ComandoSchema
from app.middleware.auth import progressive_auth

router = APIRouter()


@router.post("/", response_description="Datos Generador agregados a la base de datos.")
async def add_data(
    datos: GeneradorSchema = Body(...),
    device=Depends(progressive_auth),
):
    """Recepción de telemetría Generador (G_{imei}_MM_YYYY)."""
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
    response_description="Listar comandos en G_control (últimas 12 h o rango de fechas).",
)
async def buscar_comandos_generador_ok(
    filtro: Annotated[GeneradorBuscarComandosSchema, Body()] = GeneradorBuscarComandosSchema(),
):
    """
    Consulta **G_control_MM_YYYY** para cada mes que cubra el intervalo.

    - Sin **fecha_inicio** / **fecha_fin**: últimas **12 horas** (`fecha_creacion`).
    - Con ambas: rango inclusivo (hasta ~24 meses). ISO o `dd-mm-yyyy_hh-mm-ss`.
    - **imei** opcional.
    """
    try:
        return await buscar_comandos_generador(
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


@router.post("/imei/", response_description="Tramas por IMEI (12 h o rango; cruza G_{imei}_mes_año).")
async def buscar_imei_ok(filtro: GeneradorBuscarImeiSchema = Body(...)):
    """
    Colecciones **G_{imei}_MM_YYYY** por cada mes del intervalo.

    - Solo **imei**: últimas **12 horas** (`fecha`).
    - **fecha_inicio** y **fecha_fin**: rango inclusivo; ISO o `dd-mm-yyyy_hh-mm-ss`.
    """
    try:
        return await buscar_imei_generador(
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
    response_description="Lista equipos Generador en G_dispositivos_MES_AÑO.",
)
async def listar_dispositivos_generador_ok(
    periodo: Annotated[GeneradorDispositivosPeriodoSchema, Body()] = GeneradorDispositivosPeriodoSchema(),
):
    """Equipos con estado=1 en la colección mensual (mes/año actual si omiten campos)."""
    return await listar_dispositivos_generador(mes=periodo.mes, anio=periodo.anio)


@router.post(
    "/dispositivos/reporte/",
    response_description="Reporte online / wait / offline según ultimo_dato.",
)
async def reporte_dispositivos_generador_ok(
    periodo: Annotated[GeneradorDispositivosPeriodoSchema, Body()] = GeneradorDispositivosPeriodoSchema(),
):
    return await reporte_dispositivos_generador(mes=periodo.mes, anio=periodo.anio)


@router.post(
    "/dispositivos/reporte-global/",
    response_description="Reporte online/wait/offline cruzando varios meses (G_dispositivos).",
)
async def reporte_dispositivos_generador_global_ok(
    rango: GeneradorDispositivosRangoSchema = Body(...),
):
    """
    Recorre **G_dispositivos_MM_YYYY** entre mes_desde y mes_hasta (inclusivo).
    Por IMEI se usa el registro con **ultimo_dato** más reciente entre meses.
    """
    return await reporte_dispositivos_generador_global(
        mes_desde=rango.mes_desde,
        anio_desde=rango.anio_desde,
        mes_hasta=rango.mes_hasta,
        anio_hasta=rango.anio_hasta,
    )
