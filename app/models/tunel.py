"""
app/models/tunel.py

Portado del original server/models/tunel.py → TunelSchema.
Mismo patrón que TermoKingSchema: IMEI compuesto, canales hex o no, fecha en servidor.
"""
from datetime import datetime

from app.core.datetime_utils import server_now
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.termoking import IMEI_COMPOSITE, IMEI_STRICT


class TunelSchema(BaseModel):
    """Schema del dispositivo Túnel. Acepta UNIT222,ZGRU9999994 y canales hex o CSV."""
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
        """Acepta hex, CSV o cualquier string. No rechaza por formato."""
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
        """
        Prepara el documento para MongoDB.
        - fecha: siempre fecha actual del servidor
        - estado: siempre 1 (predefinido)
        """
        if received_at is None:
            received_at = server_now()
        doc = self.model_dump(mode="python")
        doc["fecha"] = received_at
        doc["estado"] = 1
        doc["received_at"] = received_at
        doc["secured"] = secured
        return doc
