"""
app/models/tunel.py

Portado del original server/models/tunel.py → TunelSchema.
Mismo patrón que TermoKingSchema con sus propios campos.
"""
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.termoking import HEX_REGEX, IMEI_FLEXIBLE, IMEI_STRICT


class TunelSchema(BaseModel):
    """Schema del dispositivo Túnel. Mismo patrón de campos que TermoKing."""
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
    fecha: Optional[datetime] = None

    model_config = {"populate_by_name": True, "extra": "allow"}

    @model_validator(mode="before")
    @classmethod
    def parse_fecha(cls, values: dict) -> dict:
        fecha = values.get("fecha")
        if fecha is None:
            return values
        if isinstance(fecha, dict):
            date_str = fecha.get("$date")
            if date_str:
                try:
                    values["fecha"] = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    values["fecha"] = None
        elif isinstance(fecha, str):
            try:
                values["fecha"] = datetime.fromisoformat(fecha.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                values["fecha"] = None
        return values

    @field_validator("i")
    @classmethod
    def validate_imei(cls, v: str) -> str:
        v = v.strip()
        if IMEI_STRICT.match(v) or IMEI_FLEXIBLE.match(v):
            return v
        raise ValueError(f"ID de dispositivo inválido: '{v}'")

    @field_validator("d02", "d03", "d04", "d05", "d06", "d07", "d08", "d1", "d2", "d3", "d4")
    @classmethod
    def normalize_hex(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        v_up = v.upper()
        return v_up if HEX_REGEX.match(v_up) else v

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
            received_at = datetime.now(timezone.utc)
        doc = self.model_dump(mode="python")
        doc["received_at"] = received_at
        if self.fecha is not None:
            device_ts = self.fecha
            if device_ts.tzinfo is None:
                device_ts = device_ts.replace(tzinfo=timezone.utc)
            recv = received_at if received_at.tzinfo else received_at.replace(tzinfo=timezone.utc)
            doc["clock_drift_seconds"] = round(abs((recv - device_ts).total_seconds()), 1)
        doc["secured"] = secured
        return doc
