"""
API REST para el panel web de monitoreo de flota.
"""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.functions.dashboard import (
    obtener_comandos_ejecutados_dispositivo,
    obtener_flota_dashboard,
    obtener_ultima_trama_dispositivo,
)
from app.functions.decodificado_queries import _ultimo_oficial_for_imei
from app.functions.trama_decoder import decode_trama

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

TipoDispositivo = Literal["TermoKing", "Tunel"]


@router.get("", include_in_schema=True)
async def dashboard_redirect():
    return RedirectResponse(url="/dashboard/", status_code=302)


@router.get("/flota")
async def flota(
    tipo: TipoDispositivo = Query("TermoKing"),
    online_h: float = Query(1.0, ge=0, le=168, description="Horas para estado online"),
    wait_h: float = Query(24.0, ge=0, le=720, description="Horas máximas para estado wait"),
    incluir_trama: bool = Query(True, description="Incluir resumen de última trama"),
):
    """
    Lista dispositivos con estado (online / wait / offline) y último dato.
    El IMEI corresponde al campo `i` enviado por el dispositivo en el POST.
    """
    if wait_h < online_h:
        wait_h = online_h
    return await obtener_flota_dashboard(
        tipo=tipo,
        online_h=online_h,
        wait_h=wait_h,
        incluir_trama=incluir_trama,
    )


@router.get("/dispositivo/{imei}/ultima")
async def ultima_trama(
    imei: str,
    tipo: TipoDispositivo = Query("TermoKing"),
):
    """Última trama completa de un dispositivo."""
    if not imei.strip():
        raise HTTPException(status_code=400, detail="IMEI vacío")
    return await obtener_ultima_trama_dispositivo(imei=imei, tipo=tipo)


@router.get("/dispositivo/{imei}/comandos")
async def comandos_ejecutados(
    imei: str,
    tipo: TipoDispositivo = Query("TermoKing"),
    page: int = Query(1, ge=1, description="Página (10 comandos por página)"),
    page_size: int = Query(10, ge=1, le=50),
    dias: int = Query(90, ge=1, le=365, description="Días hacia atrás a buscar"),
):
    """Últimos comandos ejecutados (status=2), paginados."""
    if not imei.strip():
        raise HTTPException(status_code=400, detail="IMEI vacío")
    return await obtener_comandos_ejecutados_dispositivo(
        imei=imei,
        tipo=tipo,
        page=page,
        page_size=page_size,
        dias=dias,
    )


@router.post("/decodificar")
async def decodificar_trama(body: dict):
    """
    Decodifica canales hex/CSV/ASCII de una trama.
    Body: { "trama": { ... }, "tipo": "TermoKing", "incluir_oficial": true }
    """
    trama = body.get("trama")
    if not trama or not isinstance(trama, dict):
        raise HTTPException(status_code=400, detail="Se requiere objeto 'trama'")
    tipo = body.get("tipo", "TermoKing")
    if tipo not in ("TermoKing", "Tunel"):
        raise HTTPException(status_code=400, detail="tipo debe ser TermoKing o Tunel")

    resultado = decode_trama(trama)
    imei = (trama.get("i") or body.get("imei") or "").strip()
    resultado["imei"] = imei or resultado.get("imei")

    if body.get("incluir_oficial", True) and imei:
        oficial = await _ultimo_oficial_for_imei(imei, tipo)
        resultado["oficial"] = {
            "disponible": oficial.get("ultimo") is not None,
            "coleccion": oficial.get("coleccion"),
            "anio": oficial.get("anio"),
            "mensaje": oficial.get("mensaje"),
            "ultimo": oficial.get("ultimo"),
        }
    return resultado


@router.get("/dispositivo/{imei}/decodificar")
async def decodificar_dispositivo(
    imei: str,
    tipo: TipoDispositivo = Query("TermoKing"),
    usar_oficial: bool = Query(True, description="Incluir último documento OFICIAL si existe"),
):
    """Última trama del dispositivo + decodificación de canales."""
    if not imei.strip():
        raise HTTPException(status_code=400, detail="IMEI vacío")
    raw = await obtener_ultima_trama_dispositivo(imei=imei, tipo=tipo)
    trama = raw.get("ultima_trama")
    out = decode_trama(trama)
    out["trama_raw"] = trama
    out["coleccion_trama"] = raw.get("coleccion")
    out["zona_horaria"] = raw.get("zona_horaria")
    if usar_oficial:
        oficial = await _ultimo_oficial_for_imei(imei, tipo)
        out["oficial"] = {
            "disponible": oficial.get("ultimo") is not None,
            "coleccion": oficial.get("coleccion"),
            "anio": oficial.get("anio"),
            "mensaje": oficial.get("mensaje"),
            "ultimo": oficial.get("ultimo"),
        }
    return out
