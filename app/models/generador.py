"""
app/models/generador.py

Schema para el módulo Generador.
Colecciones: G_{imei}_MM_YYYY, G_dispositivos_MM_YYYY, G_control_MM_YYYY.
Mismo patrón que Starcool/Datos: fecha en servidor, estado=1, extra="allow".
"""
import re
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from app.core.datetime_utils import server_now

IMEI_STRICT = re.compile(r"^\d{15}$")
IMEI_COMPOSITE = re.compile(r"^[a-zA-Z0-9_,\.\-]{4,80}$")


class GeneradorSchema(BaseModel):
    """Schema para telemetría tipo Generador (d00-d05, r01-r02, d09, gps)."""
    i: str = Field(..., description="IMEI del dispositivo")
    d00: Optional[str] = None
    d01: Optional[str] = None
    d02: Optional[str] = None
    d03: Optional[str] = None
    d04: Optional[str] = None
    d05: Optional[str] = None
    r01: Optional[str] = None
    r02: Optional[str] = None
    gps: Optional[str] = None
    d09: Optional[str] = None
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
