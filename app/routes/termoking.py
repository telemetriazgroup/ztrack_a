"""
app/routes/termoking.py

Rutas del módulo TermoKing.
ADAPTACIÓN del original server/routes/termoking.py.

CAMBIOS:
  1. Imports actualizados a la nueva estructura de paquetes
  2. El POST "/" ahora usa progressive_auth (acepta legacy y nuevos)
  3. Todas las demás rutas se mantienen idénticas al original
  4. Se agrega el campo 'comando' y 'secured' en la respuesta del POST
"""
from fastapi import APIRouter, Body, Depends, Request
from fastapi.encoders import jsonable_encoder

from app.functions.termoking import (
    Guardar_Datos,
    Procesar_Trama,
    buscar_imei,
    insertar_comando,
    datos_totales,
    grafica_total,
    datos_totales_ok,
    grafica_total_ok,
    buscar_live,
    datos_general,
    procesar_data_termoking,
    controlar_etileno_miami_ics,
    procesar_data_madurador_miami,
    procesos_madurador,
    get_proceso,
    consultar_trama_ultimo,
    consultar_starcool_cerro_prieto,
    ultimo_estado_dispositivos_termoking,
    buscar_comandos_termoking,
    dispositivos_periodo_termoking,
    reporte_global_termoking,
    dispositivos_reporte_termoking,
)
from app.models.termoking import TermoKingSchema
from app.models.common import (
    ErrorResponseModel,
    ResponseModel,
    BusquedaSchema,
    BusquedaGeneral,
    ComandoSchema,
    BusquedaSchema_proceso,
    BuscarComandosSchema,
    DispositivosPeriodoSchema,
    DispositivosReporteSchema,
)
from app.middleware.auth import progressive_auth

router = APIRouter()


# ── RECEPCIÓN PRINCIPAL DE TELEMETRÍA ────────────────────────────────────────

@router.post("/", response_description="Datos agregados a la base de datos.")
async def add_data(
    request: Request,
    datos: TermoKingSchema = Body(...),
    device=Depends(progressive_auth),
):
    """
    Endpoint principal de recepción de telemetría TermoKing.

    CAMBIO vs. original: Usa progressive_auth (acepta dispositivos legacy
    sin API Key Y dispositivos nuevos con API Key).

    La respuesta incluye el campo 'comando' con el comando de control
    pendiente para el dispositivo (equivalente al return del Guardar_Datos original).
    """
    datos_dict = jsonable_encoder(datos)

    # Agregar received_at y secured al documento
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


# ── CONSULTAS ────────────────────────────────────────────────────────────────
# Idénticas al original - solo se actualizan los imports

@router.post("/ConsultarStarcool/", response_description="Datos agregados a la base de datos.")
async def consultar_starcool_cerro_prieto_ok(datos: BusquedaGeneral = Body(...)):
    datos = jsonable_encoder(datos)
    return await consultar_starcool_cerro_prieto(datos)


@router.get("/ConsultarUltimaTrama/{imei}", response_description="Datos recuperados")
async def consultar_trama_ultimo_ok(imei: str):
    result = await consultar_trama_ultimo(imei)
    if result:
        return ResponseModel(result, "Datos recuperados exitosamente.")
    return ResponseModel(result, "Lista vacía devuelta")


@router.post("/General/", response_description="Datos agregados a la base de datos.")
async def buscar_tabla_ok(datos: BusquedaGeneral = Body(...)):
    datos = jsonable_encoder(datos)
    return await datos_general(datos)


@router.get("/PreTermoking/", response_description="Datos agregados a la base de datos.")
async def pre_termoking():
    return await procesar_data_termoking()


@router.post("/live/", response_description="Datos agregados a la base de datos.")
async def buscar_live_ok(datos: BusquedaSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await buscar_live(datos)


@router.post("/comando/", response_description="Datos agregados a la base de datos.")
async def add_comando(datos: ComandoSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await insertar_comando(datos)


@router.post("/comando/buscar/", response_description="Buscar comandos en TK_control (multi-mes).")
async def buscar_comandos_ok(datos: BuscarComandosSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await buscar_comandos_termoking(datos)


@router.post("/dispositivos/periodo/", response_description="Listar dispositivos en rango de fechas o meses.")
async def dispositivos_periodo_ok(datos: DispositivosPeriodoSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await dispositivos_periodo_termoking(datos)


@router.post("/dispositivos/reporte_global/", response_description="Resumen agregado de dispositivos en el periodo.")
async def dispositivos_reporte_global_ok(datos: DispositivosPeriodoSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await reporte_global_termoking(datos)


@router.post("/dispositivos/reporte/", response_description="Clasificación online / wait / offline por colección mensual.")
async def dispositivos_reporte_ok(datos: DispositivosReporteSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await dispositivos_reporte_termoking(datos)


@router.post("/imei/", response_description="Datos agregados a la base de datos.")
async def buscar_imei_ok(datos: BusquedaSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await buscar_imei(datos)


@router.post("/ListarTabla/", response_description="Datos agregados a la base de datos.")
async def buscar_tabla_listar(datos: BusquedaSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await datos_totales(datos)


@router.post("/ListarTablaOK/", response_description="Datos agregados a la base de datos.")
async def buscar_tabla_okok(datos: BusquedaSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await datos_totales_ok(datos)


@router.post("/ListarGrafica/", response_description="Datos agregados a la base de datos.")
async def buscar_grafica_ok(datos: BusquedaSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await grafica_total(datos)


@router.post("/ListarGraficaOK/", response_description="Datos agregados a la base de datos.")
async def buscar_grafica_okok(datos: BusquedaSchema = Body(...)):
    datos = jsonable_encoder(datos)
    return await grafica_total_ok(datos)


@router.get("/procesar_termo_king", response_description="Datos agregados a la base de datos.")
async def procesar_termo():
    return await Procesar_Trama()


@router.get("/controlar_etileno_ics", response_description="Control de etileno.")
async def controlar_etileno_ics_ok():
    return await controlar_etileno_miami_ics()


@router.get("/procesar_data_madurador_miami", response_description="Datos del madurador.")
async def procesar_madurador_ok():
    return await procesar_data_madurador_miami()


@router.post("/SolicitarProceso/", response_description="Proceso solicitado.")
async def procesos_madurador_ok(datos: BusquedaSchema_proceso = Body(...)):
    datos = jsonable_encoder(datos)
    return await procesos_madurador(datos)


@router.get("/datos_proceso/{id}", response_description="Datos recuperados")
async def get_proceso_ok(id: str):
    result = await get_proceso(id)
    if result:
        return ResponseModel(result, "Datos recuperados exitosamente.")
    return ResponseModel(result, "Lista vacía devuelta")


@router.get(
    "/ultimo_estado_dispositivos/",
    response_description="Resumen y último estado por dispositivo.",
)
async def ultimo_estado_dispositivos_ok():
    """
    Resumen global: total de dispositivos, último estado de cada uno.
    Incluye campo 'secured' para ver cuántos ya tienen firmware actualizado.
    """
    data = await ultimo_estado_dispositivos_termoking()
    return ResponseModel(data, "Último estado por dispositivo recuperado correctamente.")
