"""
app/models/common.py

Modelos compartidos portados del original server/models/termoking.py:
  - ComandoSchema
  - BusquedaSchema
  - BusquedaGeneral
  - BusquedaSchema_proceso
  - ResponseModel / ErrorResponseModel

Sin cambios funcionales. Solo se adapta para Pydantic v2 donde
'class Config' se reemplaza por model_config (pero se mantiene
compatibilidad con la sintaxis class Config también).
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ComandoSchema(BaseModel):
    """
    Esquema para insertar comandos de control a un dispositivo.
    El campo 'estado' actúa como contador de intentos restantes.
    """
    imei: str = Field(...)
    estado: Optional[int] = 1
    fecha_creacion: Optional[datetime] = None
    fecha_ejecucion: Optional[datetime] = None
    comando: str = Field(...)
    dispositivo: Optional[str] = "FAIL"
    evento: Optional[str] = "SIN REGISTRO"
    user: Optional[str] = "default"
    receta: Optional[str] = "sin receta"
    tipo: Optional[int] = 0
    status: Optional[int] = 1
    dato: Optional[float] = None
    id: Optional[int] = 0

    model_config = {
        "json_schema_extra": {
            "example": {
                "imei": "test01",
                "estado": 1,
                "fecha_creacion": "2024-08-17T14:43:11",
                "comando": "Trama_Readout(3)",
                "dispositivo": "ZGRU1234567"
            }
        }
    }


class BusquedaSchema(BaseModel):
    imei: str = Field(...)
    fecha_inicio: Optional[str] = "0"
    fecha_fin: Optional[str] = "0"
    mes_desde: Optional[int] = None
    anio_desde: Optional[int] = None
    mes_hasta: Optional[int] = None
    anio_hasta: Optional[int] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "imei": "867858039011138",
                "fecha_inicio": None,
                "fecha_fin": None
            }
        }
    }


class BusquedaGeneral(BaseModel):
    imei: str = Field(...)
    start_date: Optional[str] = "0"
    end_date: Optional[str] = "0"
    limit: Optional[int] = 100

    model_config = {
        "json_schema_extra": {
            "example": {
                "imei": "867858039011138",
                "limit": 100,
                "start_date": None,
                "end_date": None
            }
        }
    }


class BuscarComandosSchema(BaseModel):
    """Búsqueda de comandos en TK_control_* / TUNEL_control_* (multi-mes)."""
    imei: Optional[str] = None
    fecha_inicio: Optional[str] = "0"
    fecha_fin: Optional[str] = "0"
    mes_desde: Optional[int] = None
    anio_desde: Optional[int] = None
    mes_hasta: Optional[int] = None
    anio_hasta: Optional[int] = None


class DispositivosPeriodoSchema(BaseModel):
    """Listado de dispositivos en *_dispositivos_* para un rango de meses o fechas."""
    fecha_inicio: Optional[str] = "0"
    fecha_fin: Optional[str] = "0"
    mes_desde: Optional[int] = None
    anio_desde: Optional[int] = None
    mes_hasta: Optional[int] = None
    anio_hasta: Optional[int] = None


class BusquedaSchema_proceso(BaseModel):
    # Formato esperado: "%d-%m-%Y_%H-%M-%S"
    fecha_inicio: Optional[str] = "0"
    fecha_fin: Optional[str] = "0"
    limit: Optional[int] = 100

    model_config = {
        "json_schema_extra": {
            "example": {
                "fecha_inicio": "10-08-2025_00-00-00",
                "fecha_fin": "05-09-2025_23-59-59",
            }
        }
    }


# ── Helpers de respuesta (portados del original sin cambios) ─────────────────

def ResponseModel(data, message: str) -> dict:
    """Respuesta exitosa estándar de la API."""
    return {
        "data": data,
        "code": 200,
        "message": message,
    }


def ErrorResponseModel(error, code: int, message: str) -> dict:
    """Respuesta de error estándar de la API."""
    return {
        "error": error,
        "code": code,
        "message": message,
    }
