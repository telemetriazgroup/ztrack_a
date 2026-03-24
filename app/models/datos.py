"""
app/models/datos.py

Schema para el módulo Datos.
Colecciones: D_{imei}_MM_YYYY, D_dispositivos_MM_YYYY, D_control_MM_YYYY.
Mismo patrón que TermoKing/Tunel: fecha en servidor, estado=1, extra="allow".
"""
import re
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

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
