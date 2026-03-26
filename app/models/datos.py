"""
app/models/datos.py

Schema para el módulo Datos.
Colecciones: D_{imei}_MM_YYYY, D_dispositivos_MM_YYYY, D_control_MM_YYYY.
Mismo patrón que TermoKing/Tunel: fecha en servidor, estado=1, extra="allow".
"""
import re
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.datetime_utils import server_now

IMEI_STRICT = re.compile(r"^\d{15}$")
IMEI_COMPOSITE = re.compile(r"^[a-zA-Z0-9_,\.\-]{4,80}$")


class DatosSchema(BaseModel):
    """Schema para telemetría tipo Datos (campos d, d1-d10, g, c)."""
    i: str = Field(..., description="IMEI del dispositivo")
    d: Optional[str] = None
    d1: Optional[str] = None
    d2: Optional[str] = None
    d3: Optional[str] = None
    d4: Optional[str] = None
    d5: Optional[str] = None
    d6: Optional[str] = None
    d7: Optional[str] = None
    d8: Optional[str] = None
    d9: Optional[str] = None
    d10: Optional[str] = None
    g: Optional[str] = None
    c: Optional[str] = None
    estado: Optional[int] = 1
    fecha: Optional[Any] = None

    model_config = {"populate_by_name": True, "extra": "allow"}

    @field_validator("i")
    @classmethod
    def validate_imei(cls, v: str) -> str:
        v = str(v).strip()
        if not v:
            raise ValueError("Campo 'i' vacío")
        if IMEI_STRICT.match(v) or IMEI_COMPOSITE.match(v):
            return v
        if 4 <= len(v) <= 80:
            return v
        raise ValueError(f"ID de dispositivo inválido: '{v}'")

    def to_mongo_document(
        self,
        received_at: Optional[datetime] = None,
        secured: bool = False,
    ) -> dict:
        """
        Prepara el documento para MongoDB.
        fecha y estado se asignan en servidor (compatibilidad con proyecto).
        """
        if received_at is None:
            received_at = server_now()
        doc = self.model_dump(mode="python")
        doc["fecha"] = received_at
        doc["estado"] = 1
        doc["received_at"] = received_at
        doc["secured"] = secured
        return doc


class DatosDispositivosPeriodoSchema(BaseModel):
    """Mes y año de D_dispositivos_MM_YYYY (mes/año actual si se omiten)."""
    mes: Optional[int] = Field(None, ge=1, le=12)
    anio: Optional[int] = Field(None, ge=2000, le=2100)

    model_config = {"json_schema_extra": {"example": {"mes": 3, "anio": 2026}}}


def _cantidad_meses_inclusivo_datos(
    anio_desde: int, mes_desde: int, anio_hasta: int, mes_hasta: int
) -> int:
    n = 0
    y, m = anio_desde, mes_desde
    while (y, m) <= (anio_hasta, mes_hasta):
        n += 1
        m += 1
        if m > 12:
            m = 1
            y += 1
    return n


class DatosDispositivosRangoSchema(BaseModel):
    """Rango inclusivo para reporte global (varias D_dispositivos_MM_YYYY)."""
    mes_desde: int = Field(..., ge=1, le=12)
    anio_desde: int = Field(..., ge=2000, le=2100)
    mes_hasta: int = Field(..., ge=1, le=12)
    anio_hasta: int = Field(..., ge=2000, le=2100)

    model_config = {
        "json_schema_extra": {
            "example": {
                "mes_desde": 1,
                "anio_desde": 2025,
                "mes_hasta": 3,
                "anio_hasta": 2026,
            }
        }
    }

    @model_validator(mode="after")
    def validar_rango(self) -> "DatosDispositivosRangoSchema":
        if (self.anio_desde, self.mes_desde) > (self.anio_hasta, self.mes_hasta):
            raise ValueError(
                "Periodo inválido: mes_desde/anio_desde debe ser anterior o igual a mes_hasta/anio_hasta"
            )
        n = _cantidad_meses_inclusivo_datos(
            self.anio_desde, self.mes_desde, self.anio_hasta, self.mes_hasta
        )
        if n > 36:
            raise ValueError("El rango no puede superar 36 meses")
        return self


class DatosBuscarComandosSchema(BaseModel):
    """Búsqueda en D_control_MM_YYYY (cruza meses según el intervalo)."""
    imei: Optional[str] = Field(None, description="Opcional: filtrar por IMEI")
    fecha_inicio: Optional[str] = Field(None, description="ISO 8601 o dd-mm-yyyy_hh-mm-ss")
    fecha_fin: Optional[str] = Field(None, description="Fin del rango")

    model_config = {
        "json_schema_extra": {
            "example": {
                "imei": "867858039011138",
                "fecha_inicio": "01-03-2026_00-00-00",
                "fecha_fin": "24-03-2026_23-59-59",
            }
        }
    }

    @model_validator(mode="after")
    def fechas_en_par(self) -> "DatosBuscarComandosSchema":
        def _non_empty(v: Optional[str]) -> bool:
            return bool(v and str(v).strip())

        if _non_empty(self.fecha_inicio) != _non_empty(self.fecha_fin):
            raise ValueError(
                "Envíe fecha_inicio y fecha_fin juntas, u omita ambas para usar las últimas 12 horas"
            )
        return self


class DatosBuscarImeiSchema(BaseModel):
    """Tramas en D_{imei}_MM_YYYY; sin fechas → últimas 12 h por campo `fecha`."""
    imei: str = Field(..., description="IMEI (campo `i` en la trama)")
    fecha_inicio: Optional[str] = Field(None, description="ISO 8601 o dd-mm-yyyy_hh-mm-ss")
    fecha_fin: Optional[str] = Field(None, description="Fin del rango")

    model_config = {
        "json_schema_extra": {
            "example": {
                "imei": "867858039011138",
                "fecha_inicio": "01-03-2026_00-00-00",
                "fecha_fin": "24-03-2026_23-59-59",
            }
        }
    }

    @model_validator(mode="before")
    @classmethod
    def _normalizar_fechas_opcionales(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        for k in ("fecha_inicio", "fecha_fin"):
            v = out.get(k)
            if v is not None and str(v).strip() in ("", "0"):
                out[k] = None
        return out

    @model_validator(mode="after")
    def fechas_en_par(self) -> "DatosBuscarImeiSchema":
        def _non_empty(v: Optional[str]) -> bool:
            return bool(v and str(v).strip())

        if _non_empty(self.fecha_inicio) != _non_empty(self.fecha_fin):
            raise ValueError(
                "Envíe fecha_inicio y fecha_fin juntas, u omita ambas para usar las últimas 12 horas"
            )
        return self
