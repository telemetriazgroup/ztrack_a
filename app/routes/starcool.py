"""
app/routes/starcool.py

Rutas del módulo Starcool.
Colecciones: S_{imei}_MM_YYYY, S_dispositivos_MM_YYYY, S_control_MM_YYYY.
"""
from fastapi import APIRouter, Body, Depends

from fastapi.encoders import jsonable_encoder

from app.core.datetime_utils import server_now
from app.functions.starcool import (
    Guardar_Datos,
    buscar_imei,
    buscar_live,
    datos_totales,
    insertar_comando,
)
from app.models.starcool import StarcoolSchema
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


@router.post("/comando/", response_description="Insertar comando.")
async def add_comando(datos: ComandoSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await insertar_comando(datos)


@router.post("/imei/", response_description="Buscar por IMEI.")
async def buscar_imei_ok(datos: BusquedaSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await buscar_imei(datos)


@router.post("/ListarTabla/", response_description="Listar tabla.")
async def buscar_tabla_ok(datos: BusquedaSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await datos_totales(datos)


@router.post("/live/", response_description="Datos en vivo.")
async def buscar_live_ok(datos: BusquedaSchema = Body(...)):
    datos = jsonable_encoder(datos)
    result = await buscar_live(datos)
    return ResponseModel(result, "Último dato recuperado." if result else "Sin datos.")
