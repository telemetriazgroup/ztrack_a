"""
app/routes/tunel.py
Rutas del módulo Túnel. Adaptación del original server/routes/tunel.py.
"""
from fastapi import APIRouter, Body, Depends, Request
from fastapi.encoders import jsonable_encoder

from app.functions.tunel import (
    Guardar_Datos,
    Procesar_Trama,
    buscar_imei,
    insertar_comando,
    datos_totales,
    grafica_total,
    datos_totales_ok,
    grafica_total_ok,
    buscar_live,
    procesar_data_termoking,
    buscar_comandos_tunel,
    dispositivos_periodo_tunel,
    reporte_global_tunel,
    dispositivos_reporte_tunel,
)
from app.models.tunel import TunelSchema
from app.models.common import (
    ResponseModel,
    BusquedaSchema,
    ComandoSchema,
    BuscarComandosSchema,
    DispositivosPeriodoSchema,
    DispositivosReporteSchema,
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
    from app.core.datetime_utils import server_now
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


@router.post("/comando/", response_description="Insertar comando.")
async def add_comando(datos: ComandoSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await insertar_comando(datos)


@router.post("/comando/buscar/", response_description="Buscar comandos en TUNEL_control (multi-mes).")
async def buscar_comandos_ok(datos: BuscarComandosSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await buscar_comandos_tunel(datos)


@router.post("/dispositivos/periodo/", response_description="Listar dispositivos en rango.")
async def dispositivos_periodo_ok(datos: DispositivosPeriodoSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await dispositivos_periodo_tunel(datos)


@router.post("/dispositivos/reporte_global/", response_description="Resumen agregado de dispositivos.")
async def dispositivos_reporte_global_ok(datos: DispositivosPeriodoSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await reporte_global_tunel(datos)


@router.post("/dispositivos/reporte/", response_description="Clasificación online / wait / offline por colección mensual.")
async def dispositivos_reporte_ok(datos: DispositivosReporteSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await dispositivos_reporte_tunel(datos)


@router.post("/imei/", response_description="Buscar por IMEI.")
async def buscar_imei_ok(datos: BusquedaSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await buscar_imei(datos)


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


@router.get("/procesar_termo_king", response_description="Procesar tramas.")
async def procesar_termo():
    return await Procesar_Trama()
