"""
app/routes/tunel.py
Rutas del módulo Túnel. Adaptación del original server/routes/tunel.py.
"""
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder

from app.core.datetime_utils import server_now
from app.functions.tunel import (
    Guardar_Datos,
    Procesar_Trama,
    buscar_comandos_tunel,
    buscar_imei_tunel,
    insertar_comando,
    datos_totales,
    datos_totales_ok,
    grafica_total,
    grafica_total_ok,
    buscar_live,
    procesar_data_termoking,
    listar_dispositivos_tunel,
    reporte_dispositivos_tunel,
    reporte_dispositivos_tunel_global,
)
from app.models.tunel import (
    TunelSchema,
    TunelBuscarComandosSchema,
    TunelBuscarImeiSchema,
    TunelDispositivosPeriodoSchema,
    TunelDispositivosRangoSchema,
)
from app.models.common import (
    ResponseModel,
    BusquedaSchema,
    ComandoSchema,
)
from app.middleware.auth import progressive_auth

router = APIRouter()


@router.post("/", response_description="Datos agregados a la base de datos.")
async def add_data(
    request: Request,
    datos: TunelSchema = Body(...),
    device=Depends(progressive_auth),
):
    """Recepción de telemetría Túnel con Seguridad Progresiva."""
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


@router.get("/PreTermoking/", response_description="Pre-procesamiento.")
async def pre_termoking():
    return await procesar_data_termoking()


@router.post("/live/", response_description="Datos en vivo.")
async def buscar_live_ok(datos: BusquedaSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await buscar_live(datos)


@router.post(
    "/comando/buscar/",
    response_description="Listar comandos TUNEL_control (12 h o rango).",
)
async def buscar_comandos_tunel_ok(
    filtro: Annotated[TunelBuscarComandosSchema, Body()] = TunelBuscarComandosSchema(),
):
    try:
        return await buscar_comandos_tunel(
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


@router.post("/imei/", response_description="Tramas por IMEI (12 h o rango; TUNEL_{imei}_mes_año).")
async def buscar_imei_ok(filtro: TunelBuscarImeiSchema = Body(...)):
    try:
        return await buscar_imei_tunel(
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


@router.post("/ListarTablaOK/", response_description="Listar tabla OK.")
async def buscar_tabla_okok(datos: BusquedaSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await datos_totales_ok(datos)


@router.post("/ListarGrafica/", response_description="Listar gráfica.")
async def buscar_grafica_ok(datos: BusquedaSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await grafica_total(datos)


@router.post("/ListarGraficaOK/", response_description="Listar gráfica OK.")
async def buscar_grafica_okok(datos: BusquedaSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await grafica_total_ok(datos)


@router.post(
    "/dispositivos/listar/",
    response_description="Lista equipos Túnel en TUNEL_dispositivos_MES_AÑO.",
)
async def listar_dispositivos_tunel_ok(
    periodo: Annotated[TunelDispositivosPeriodoSchema, Body()] = TunelDispositivosPeriodoSchema(),
):
    return await listar_dispositivos_tunel(mes=periodo.mes, anio=periodo.anio)


@router.post(
    "/dispositivos/reporte/",
    response_description="Reporte online / wait / offline (ultimo_dato).",
)
async def reporte_dispositivos_tunel_ok(
    periodo: Annotated[TunelDispositivosPeriodoSchema, Body()] = TunelDispositivosPeriodoSchema(),
):
    return await reporte_dispositivos_tunel(mes=periodo.mes, anio=periodo.anio)


@router.post(
    "/dispositivos/reporte-global/",
    response_description="Reporte multi-mes (TUNEL_dispositivos).",
)
async def reporte_dispositivos_tunel_global_ok(rango: TunelDispositivosRangoSchema = Body(...)):
    return await reporte_dispositivos_tunel_global(
        mes_desde=rango.mes_desde,
        anio_desde=rango.anio_desde,
        mes_hasta=rango.mes_hasta,
        anio_hasta=rango.anio_hasta,
    )


@router.get("/procesar_termo_king", response_description="Procesar tramas.")
async def procesar_termo():
    return await Procesar_Trama()
