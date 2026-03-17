"""
app/models/termoking.py

Portado del original server/models/termoking.py → TermoKingSchema.

CAMBIOS:
  - Se corrige el campo d08 duplicado del original (había dos definiciones)
  - Se agrega validación flexible de fecha (formato MongoDB {"$date":"..."})
  - Se agrega to_mongo_document() para preparar el documento antes de insertar
  - Se agrega campo 'secured' para Seguridad Progresiva
  - El campo 'estado' mantiene default=1 (igual que el original)
"""
import re
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

HEX_REGEX = re.compile(r"^[0-9A-Fa-f]+$")
IMEI_STRICT = re.compile(r"^\d{15}$")
IMEI_FLEXIBLE = re.compile(r"^[a-zA-Z0-9_-]{4,20}$")


class TermoKingSchema(BaseModel):
    """
    Schema del dispositivo TermoKing.
    Compatible con el payload real enviado via HTTP POST.

    NOTA SOBRE d08 DUPLICADO:
    El original tenía dos líneas 'd08'. Python solo toma la última,
    aquí se unifica correctamente en un solo campo.
    """
    i: str = Field(..., description="IMEI del dispositivo")
    ip: Optional[str] = None
    c: Optional[str] = None

    # Canales con cero (protocolo nuevo)
    d00: Optional[str] = None
    d01: Optional[str] = None
    d02: Optional[str] = None
    d03: Optional[str] = None
    d04: Optional[str] = None
    d05: Optional[str] = None
    d06: Optional[str] = None
    d07: Optional[str] = None
    d08: Optional[str] = None   # CORREGIDO: antes estaba duplicado en el original

    # Canales TermoKing sin cero (protocolo original)
    d1: Optional[str] = None
    d2: Optional[str] = None
    d3: Optional[str] = None
    d4: Optional[str] = None

    gps: Optional[str] = None
    val: Optional[str] = None
    rs: Optional[str] = None
    r: Optional[Any] = None      # Resultado de comandos ejecutados

    # Igual que el original: Optional con default=1
    estado: Optional[int] = 1

    # Fecha flexible: acepta {"$date":"..."}, string ISO o null
    fecha: Optional[datetime] = None

    model_config = {"populate_by_name": True, "extra": "allow"}

    @model_validator(mode="before")
    @classmethod
    def parse_fecha(cls, values: dict) -> dict:
        """
        Convierte el campo fecha a datetime antes de validar.
        Soporta: {"$date":"..."}, string ISO, datetime nativo, o null.
        Nunca rechaza la trama por fecha corrupta: la ignora.
        """
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
        """Normaliza a mayúsculas si es HEX válido. Si no, lo guarda tal cual."""
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        v_up = v.upper()
        return v_up if HEX_REGEX.match(v_up) else v

    @property
    def ip_address(self) -> Optional[str]:
        """Extrae solo la IP del campo ip (descarta metadatos tipo '10.0.0.1,17,0')."""
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
        Agrega received_at (timestamp servidor), secured y clock_drift.
        """
        if received_at is None:
            received_at = datetime.now(timezone.utc)

        doc = self.model_dump(mode="python")

        # Timestamp del servidor (siempre presente, incluso si fecha=None)
        doc["received_at"] = received_at

        # Drift del reloj dispositivo vs servidor
        if self.fecha is not None:
            device_ts = self.fecha
            if device_ts.tzinfo is None:
                device_ts = device_ts.replace(tzinfo=timezone.utc)
            recv = received_at if received_at.tzinfo else received_at.replace(tzinfo=timezone.utc)
            doc["clock_drift_seconds"] = round(abs((recv - device_ts).total_seconds()), 1)

        doc["secured"] = secured
        return doc

    model_config = {
        "populate_by_name": True,
        "extra": "allow",
        "json_schema_extra": {
            "example": {
                "i": "860389053784506",
                "ip": "10.81.213.33,17,0",
                "c": "",
                "d01": "UNIT111",
                "d02": "1B0204000082A7000401FE7F...",
                "d03": "1B0204000082A701...",
                "estado": 2,
                "fecha": {"$date": "2025-11-04T14:34:25.870Z"}
            }
        }
    }
