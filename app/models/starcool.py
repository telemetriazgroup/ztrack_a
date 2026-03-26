"""
app/models/starcool.py

Schema para el módulo Starcool.
Colecciones: S_{imei}_MM_YYYY, S_dispositivos_MM_YYYY, S_control_MM_YYYY.
Mismo patrón que TermoKing/Tunel/Datos: fecha en servidor, estado=1, extra="allow".
"""
import re
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.datetime_utils import server_now

IMEI_STRICT = re.compile(r"^\d{15}$")
IMEI_COMPOSITE = re.compile(r"^[a-zA-Z0-9_,\.\-]{4,80}$")


class StarcoolSchema(BaseModel):
    """Schema para telemetría tipo Starcool (campos d00-d04, gps)."""
    i: str = Field(..., description="IMEI del dispositivo")
    d00: Optional[str] = None
    d01: Optional[str] = None
    d02: Optional[str] = None
    d03: Optional[str] = None
    d04: Optional[str] = None
    gps: Optional[str] = None
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
        received_at: Optional[Any] = None,
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


class StarcoolDispositivosPeriodoSchema(BaseModel):
    """
    Mes y año de la colección S_dispositivos_MM_YYYY.
    Si se omite mes o año, se usa el mes/año actual del servidor (APP_TIMEZONE).
    """
    mes: Optional[int] = Field(
        None,
        ge=1,
        le=12,
        description="Mes 1–12 (ej. 3 para marzo)",
    )
    anio: Optional[int] = Field(
        None,
        ge=2000,
        le=2100,
        description="Año de cuatro dígitos",
    )

    model_config = {
        "json_schema_extra": {
            "example": {"mes": 3, "anio": 2026},
        }
    }


def _cantidad_meses_inclusivo(
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


class StarcoolDispositivosRangoSchema(BaseModel):
    """
    Rango inclusivo de meses para reporte global (varias S_dispositivos_MM_YYYY).
    """
    mes_desde: int = Field(..., ge=1, le=12, description="Mes inicial (1–12)")
    anio_desde: int = Field(..., ge=2000, le=2100, description="Año inicial")
    mes_hasta: int = Field(..., ge=1, le=12, description="Mes final (1–12)")
    anio_hasta: int = Field(..., ge=2000, le=2100, description="Año final")

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
    def validar_rango(self) -> "StarcoolDispositivosRangoSchema":
        if (self.anio_desde, self.mes_desde) > (self.anio_hasta, self.mes_hasta):
            raise ValueError(
                "Periodo inválido: mes_desde/anio_desde debe ser anterior o igual a mes_hasta/anio_hasta"
            )
        n = _cantidad_meses_inclusivo(
            self.anio_desde, self.mes_desde, self.anio_hasta, self.mes_hasta
        )
        if n > 36:
            raise ValueError("El rango no puede superar 36 meses")
        return self


class StarcoolBuscarComandosSchema(BaseModel):
    """
    Búsqueda en S_control_MM_YYYY (recorre los meses que cruce el intervalo).

    Sin **fecha_inicio** / **fecha_fin**: últimas 12 horas respecto a `server_now()`.
    Con ambas fechas: rango personalizado (máximo ~24 meses).
    """
    imei: Optional[str] = Field(
        None,
        description="Opcional: filtrar por IMEI del dispositivo",
    )
    fecha_inicio: Optional[str] = Field(
        None,
        description="Inicio del rango: ISO 8601 o dd-mm-yyyy_hh-mm-ss (mismo formato que /imei/)",
    )
    fecha_fin: Optional[str] = Field(
        None,
        description="Fin del rango (misma convención que fecha_inicio)",
    )

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
    def fechas_en_par(self) -> "StarcoolBuscarComandosSchema":
        def _non_empty(v: Optional[str]) -> bool:
            return bool(v and str(v).strip())

        if _non_empty(self.fecha_inicio) != _non_empty(self.fecha_fin):
            raise ValueError(
                "Envíe fecha_inicio y fecha_fin juntas, u omita ambas para usar las últimas 12 horas"
            )
        return self


class StarcoolBuscarImeiSchema(BaseModel):
    """
    Tramas del dispositivo en S_{imei}_MM_YYYY (se consultan todos los meses del rango).

    Sin **fecha_inicio** / **fecha_fin**: últimas 12 horas según campo `fecha`.
    Con ambas: rango personalizado (hasta ~24 meses).
    """
    imei: str = Field(..., description="IMEI del dispositivo (mismo que en el campo `i` de la trama)")
    fecha_inicio: Optional[str] = Field(
        None,
        description="Inicio: ISO 8601 o dd-mm-yyyy_hh-mm-ss",
    )
    fecha_fin: Optional[str] = Field(
        None,
        description="Fin del rango (misma convención)",
    )

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
    def fechas_en_par(self) -> "StarcoolBuscarImeiSchema":
        def _non_empty(v: Optional[str]) -> bool:
            return bool(v and str(v).strip())

        if _non_empty(self.fecha_inicio) != _non_empty(self.fecha_fin):
            raise ValueError(
                "Envíe fecha_inicio y fecha_fin juntas, u omita ambas para usar las últimas 12 horas"
            )
        return self
