"""
Modelos Pydantic del módulo Starcool.
Colecciones: S_{imei}_MM_YYYY, S_dispositivos_MM_YYYY, S_control_MM_YYYY.
"""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.datetime_utils import server_now
from app.models.termoking import IMEI_COMPOSITE, IMEI_STRICT


class StarcoolSchema(BaseModel):
    """Schema de telemetría Starcool (mismo perfil de canales que TermoKing/Túnel)."""
    i: str = Field(..., description="IMEI del dispositivo")
    ip: Optional[str] = None
    c: Optional[str] = None
    d00: Optional[str] = None
    d01: Optional[str] = None
    d02: Optional[str] = None
    d03: Optional[str] = None
    d04: Optional[str] = None
    d05: Optional[str] = None
    d06: Optional[str] = None
    d07: Optional[str] = None
    d08: Optional[str] = None
    d1: Optional[str] = None
    d2: Optional[str] = None
    d3: Optional[str] = None
    d4: Optional[str] = None
    gps: Optional[str] = None
    val: Optional[str] = None
    rs: Optional[str] = None
    r: Optional[Any] = None
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

    @field_validator(
        "d00", "d01", "d02", "d03", "d04", "d05", "d06", "d07", "d08",
        "d1", "d2", "d3", "d4",
        mode="before",
    )
    @classmethod
    def accept_any_string(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        clean = "".join(c for c in s if c in "0123456789ABCDEFabcdef")
        if len(clean) == len(s):
            return s.upper()
        return s

    @property
    def ip_address(self) -> Optional[str]:
        if not self.ip:
            return None
        return self.ip.split(",")[0].strip()

    def to_mongo_document(
        self,
        received_at: Optional[datetime] = None,
        secured: bool = False,
    ) -> dict:
        if received_at is None:
            received_at = server_now()
        doc = self.model_dump(mode="python")
        doc["fecha"] = received_at
        doc["estado"] = 1
        doc["received_at"] = received_at
        doc["secured"] = secured
        return doc


class StarcoolBuscarComandosSchema(BaseModel):
    imei: Optional[str] = None
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None


class StarcoolBuscarImeiSchema(BaseModel):
    imei: str = Field(...)
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None


class StarcoolDispositivosPeriodoSchema(BaseModel):
    mes: Optional[int] = Field(None, ge=1, le=12)
    anio: Optional[int] = Field(None, ge=2000, le=2100)


class StarcoolDispositivosRangoSchema(BaseModel):
    mes_desde: int = Field(..., ge=1, le=12)
    anio_desde: int = Field(..., ge=2000, le=2100)
    mes_hasta: int = Field(..., ge=1, le=12)
    anio_hasta: int = Field(..., ge=2000, le=2100)

    @model_validator(mode="after")
    def validar_rango_meses(self) -> "StarcoolDispositivosRangoSchema":
        inicio = self.anio_desde * 12 + self.mes_desde
        fin = self.anio_hasta * 12 + self.mes_hasta
        if fin < inicio:
            raise ValueError("mes_hasta/anio_hasta debe ser posterior a mes_desde/anio_desde")
        if fin - inicio + 1 > 36:
            raise ValueError("El rango no puede superar 36 meses")
        return self
