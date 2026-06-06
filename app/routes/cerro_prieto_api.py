"""
API REST para el panel Cerro Prieto.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.functions.cerro_prieto import (
    CERRO_PRIETO_ACCIONES,
    CERRO_PRIETO_IMEI,
    aplicar_objetivos_panel,
    enviar_comando_panel,
    listar_historial_objetivos,
    obtener_objetivos_guardados,
    obtener_panel_estado,
)

router = APIRouter(prefix="/api/cerro-prieto", tags=["Cerro Prieto"])


class EnviarComandoBody(BaseModel):
    accion_id: str | None = Field(None, description="ID de acción predefinida")
    comando: str | None = Field(None, description="Comando PANTALLA (debe estar en whitelist)")
    user: str | None = Field("cerro_prieto_panel", max_length=64)


class ObjetivosBody(BaseModel):
    co2: dict[str, float] | None = Field(
        None,
        description="Objetivos CO₂ % por zona: {\"1\": 8, \"2\": 10, \"3\": 12}",
    )
    o2: dict[str, float] | None = Field(
        None,
        description="Objetivos O₂ % por zona: {\"1\": 4, \"2\": 4, \"3\": 8}",
    )
    user: str | None = Field("cerro_prieto_panel", max_length=64)


@router.get("", include_in_schema=True)
async def redirect_panel():
    return RedirectResponse(url="/cerro-prieto/", status_code=302)


@router.get("/estado")
async def estado_panel():
    """Última trama (rs, d02), comandos y acciones disponibles."""
    return await obtener_panel_estado()


@router.get("/acciones")
async def listar_acciones():
    return {
        "imei": CERRO_PRIETO_IMEI,
        "acciones": CERRO_PRIETO_ACCIONES,
    }


@router.get("/objetivos")
async def get_objetivos():
    """Objetivos guardados (o predeterminados) y tolerancias de color."""
    objetivos = await obtener_objetivos_guardados()
    historial = await listar_historial_objetivos()
    return {"objetivos": objetivos, "historial": historial}


@router.get("/objetivos/historial")
async def get_historial_objetivos():
    return {"historial": await listar_historial_objetivos()}


@router.post("/objetivos/aplicar")
async def aplicar_objetivos(body: ObjetivosBody):
    """Encola comandos de objetivo CO₂ y O₂ para las 3 zonas."""
    return await aplicar_objetivos_panel(
        co2=body.co2,
        o2=body.o2,
        user=body.user or "cerro_prieto_panel",
    )


@router.post("/comando")
async def enviar_comando(body: EnviarComandoBody):
    if not body.accion_id and not body.comando:
        raise HTTPException(status_code=400, detail="Indique accion_id o comando")
    result = await enviar_comando_panel(
        accion_id=body.accion_id,
        comando=body.comando,
        user=body.user or "cerro_prieto_panel",
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Error al encolar"))
    return result
