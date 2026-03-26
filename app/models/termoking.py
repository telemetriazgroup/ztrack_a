"""
app/models/termoking.py

Portado del original server/models/termoking.py → TermoKingSchema.

CAMBIOS:
  - IMEI acepta formato compuesto: UNIT222,ZGRU9999994
  - Canales d00-d08: aceptan hex o no (ej: d07='0,0,0,0,-1.0') — no se rechaza
  - fecha: se asigna en to_mongo_document (servidor), no se exige en payload
  - Política: guardar todas las tramas; validación/corrección en subproceso posterior
"""
import re
from datetime import datetime

from app.core.datetime_utils import server_now
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# IMEI: 15 dígitos, o formato UNIT222,ZGRU9999994, o alfanumérico flexible
IMEI_STRICT = re.compile(r"^\d{15}$")
IMEI_COMPOSITE = re.compile(r"^[a-zA-Z0-9_,\.\-]{4,80}$")  # UNIT222,ZGRU9999994


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

    estado: Optional[int] = 1

    # fecha no se exige: se asigna en to_mongo_document (servidor)
    fecha: Optional[Any] = None

    @field_validator("i")
    @classmethod
    def validate_imei(cls, v: str) -> str:
        """Acepta IMEI numérico, UNIT222,ZGRU9999994, o alfanumérico flexible."""
        v = str(v).strip()
        if not v:
            raise ValueError("Campo 'i' vacío")
        if IMEI_STRICT.match(v) or IMEI_COMPOSITE.match(v):
            return v
        # Último recurso: cualquier string no vacío (4-80 chars)
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
        """
        Acepta hex, CSV (ej: 0,0,0,0,-1.0) o cualquier string. No rechaza por formato.
        Hex puro se normaliza a mayúsculas; el resto se guarda tal cual.
        """
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        # Si es hex puro (solo 0-9A-Fa-f), normalizar a mayúsculas
        clean = "".join(c for c in s if c in "0123456789ABCDEFabcdef")
        if len(clean) == len(s):
            return s.upper()
        return s

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

    model_config = {
        "populate_by_name": True,
        "extra": "allow",
        "json_schema_extra": {
            "examples": [
                {"i": "860389053784506", "d01": "UNIT111", "d02": "1B0204000082A7..."},
                {"i": "UNIT222,ZGRU9999994", "d00": "FFFFFFFF1B02...", "d07": "0,0,0,0,-1.0"},
            ]
        }
    }


class TermoKingDispositivosPeriodoSchema(BaseModel):
    mes: Optional[int] = Field(None, ge=1, le=12)
    anio: Optional[int] = Field(None, ge=2000, le=2100)

    model_config = {"json_schema_extra": {"example": {"mes": 3, "anio": 2026}}}


def _cantidad_meses_inclusivo_tk(
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


class TermoKingDispositivosRangoSchema(BaseModel):
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
    def validar_rango(self) -> "TermoKingDispositivosRangoSchema":
        if (self.anio_desde, self.mes_desde) > (self.anio_hasta, self.mes_hasta):
            raise ValueError(
                "Periodo inválido: mes_desde/anio_desde debe ser anterior o igual a mes_hasta/anio_hasta"
            )
        n = _cantidad_meses_inclusivo_tk(
            self.anio_desde, self.mes_desde, self.anio_hasta, self.mes_hasta
        )
        if n > 36:
            raise ValueError("El rango no puede superar 36 meses")
        return self


class TermoKingBuscarComandosSchema(BaseModel):
    imei: Optional[str] = None
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None

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
    def fechas_en_par(self) -> "TermoKingBuscarComandosSchema":
        def _non_empty(v: Optional[str]) -> bool:
            return bool(v and str(v).strip())

        if _non_empty(self.fecha_inicio) != _non_empty(self.fecha_fin):
            raise ValueError(
                "Envíe fecha_inicio y fecha_fin juntas, u omita ambas para usar las últimas 12 horas"
            )
        return self


class TermoKingBuscarImeiSchema(BaseModel):
    imei: str = Field(...)
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None

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
    def fechas_en_par(self) -> "TermoKingBuscarImeiSchema":
        def _non_empty(v: Optional[str]) -> bool:
            return bool(v and str(v).strip())

        if _non_empty(self.fecha_inicio) != _non_empty(self.fecha_fin):
            raise ValueError(
                "Envíe fecha_inicio y fecha_fin juntas, u omita ambas para usar las últimas 12 horas"
            )
        return self
