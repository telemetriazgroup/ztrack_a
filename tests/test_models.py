"""
tests/test_models.py — Tests de validación de modelos Pydantic.

Cubre los casos reales del protocolo:
  - Payload del ejemplo real (con d02, d03 HEX largos)
  - Fecha en formato MongoDB {"$date":"..."}
  - Campos d1-d4 del TermoKingSchema original
  - IMEI de 15 dígitos y IDs cortos de prueba
  - Campo estado opcional con default=1
  - d08 no duplicado (bug del original corregido)
"""
import pytest
from datetime import datetime

from app.models.termoking import TermoKingSchema
from app.models.tunel import TunelSchema
from app.models.common import ComandoSchema, BusquedaSchema, BusquedaGeneral

# ── Payload real del ejemplo ─────────────────────────────────────────────────
REAL_PAYLOAD = {
    "i": "860389053784506",
    "ip": "10.81.213.33,17,0",
    "c": "",
    "d00": None,
    "d01": "UNIT111",
    "d02": "1B0204000082A7000401FE7F04010C0114012301FF7F0F01FE7FFE7FFE7FFE7F430000006702FE7FBE013C00BE00C000B800FE7FFE7F1E004B00EA028938000000000000230000001201FE7F04010401FE7F0000B9056700FE7FFF7F8CE71B",
    "d03": "1B0204000082A70100009CFF3000030100FE02FE7FFE7F500046000807060000FFFFFFFFB7731B",
    "d04": None, "d05": None, "d06": None, "d07": None, "d08": None,
    "gps": None, "val": None, "rs": "&&&", "r": None,
    "estado": 2,
    "fecha": {"$date": "2025-11-04T14:34:25.870Z"},
}


class TestTermoKingSchema:

    def test_real_payload_parses_correctly(self):
        """El payload exacto del ejemplo real debe parsearse sin errores."""
        p = TermoKingSchema(**REAL_PAYLOAD)
        assert p.i == "860389053784506"
        assert p.estado == 2
        assert p.d01 == "UNIT111"

    def test_fecha_mongodb_format_becomes_datetime(self):
        """{"$date": "..."} debe convertirse a datetime."""
        p = TermoKingSchema(**REAL_PAYLOAD)
        assert isinstance(p.fecha, datetime)
        assert p.fecha.year == 2025
        assert p.fecha.month == 11

    def test_fecha_iso_string(self):
        """String ISO directo también debe parsearse."""
        payload = dict(REAL_PAYLOAD, fecha="2025-11-04T14:34:25")
        p = TermoKingSchema(**payload)
        assert isinstance(p.fecha, datetime)

    def test_fecha_null_accepted(self):
        """Fecha null → se acepta (dispositivos legacy pueden no enviarla)."""
        payload = dict(REAL_PAYLOAD, fecha=None)
        p = TermoKingSchema(**payload)
        assert p.fecha is None

    def test_fecha_corrupta_no_rechaza_trama(self):
        """Fecha corrupta no rechaza la trama, se ignora."""
        payload = dict(REAL_PAYLOAD, fecha={"$date": "not-a-date"})
        p = TermoKingSchema(**payload)
        assert p.fecha is None

    def test_estado_optional_default_1(self):
        """Sin estado → default 1."""
        payload = {k: v for k, v in REAL_PAYLOAD.items() if k != "estado"}
        p = TermoKingSchema(**payload)
        assert p.estado == 1

    def test_estado_none_uses_default(self):
        """estado=None en JSON → default 1."""
        payload = dict(REAL_PAYLOAD, estado=None)
        p = TermoKingSchema(**payload)
        assert p.estado == 1

    def test_imei_15_digits(self):
        """IMEI estándar de 15 dígitos."""
        p = TermoKingSchema(**REAL_PAYLOAD)
        assert p.is_strict_imei  # type: ignore

    def test_imei_short_test_id(self):
        """IDs cortos de prueba como 'test01' deben aceptarse."""
        payload = dict(REAL_PAYLOAD, i="test01")
        p = TermoKingSchema(**payload)
        assert p.i == "test01"

    def test_imei_too_short_rejected(self):
        """ID de menos de 4 chars → ValidationError."""
        import pydantic
        payload = dict(REAL_PAYLOAD, i="AB")
        with pytest.raises(pydantic.ValidationError):
            TermoKingSchema(**payload)

    def test_hex_d02_normalized_to_uppercase(self):
        """HEX en minúsculas debe normalizarse a mayúsculas."""
        payload = dict(REAL_PAYLOAD, d02=REAL_PAYLOAD["d02"].lower())
        p = TermoKingSchema(**payload)
        assert p.d02 == p.d02.upper()

    def test_d1_d4_fields_original_protocol(self):
        """Canales d1-d4 del protocolo original TermoKing."""
        payload = dict(REAL_PAYLOAD, d1="1B0204", d2="FF00AA", d3=None, d4="DEADBEEF")
        p = TermoKingSchema(**payload)
        assert p.d1 == "1B0204"
        assert p.d4 == "DEADBEEF"
        assert p.d3 is None

    def test_d08_not_duplicated(self):
        """d08 debe existir como campo único (bug del original corregido)."""
        payload = dict(REAL_PAYLOAD, d08="AABBCC")
        p = TermoKingSchema(**payload)
        assert p.d08 == "AABBCC"

    def test_ip_address_property_extracts_only_ip(self):
        """ip_address extrae solo la IP descartando metadatos."""
        p = TermoKingSchema(**REAL_PAYLOAD)
        assert p.ip_address == "10.81.213.33"

    def test_r_field_accepts_command_response(self):
        """Campo r puede contener la respuesta del dispositivo a un comando."""
        payload = dict(REAL_PAYLOAD, r="OK:Trama_Readout(3)")
        p = TermoKingSchema(**payload)
        assert p.r == "OK:Trama_Readout(3)"

    def test_to_mongo_document_secured_false(self):
        """Documento MongoDB con secured=False para dispositivos legacy."""
        p = TermoKingSchema(**REAL_PAYLOAD)
        doc = p.to_mongo_document(secured=False)
        assert doc["secured"] is False
        assert "received_at" in doc
        assert doc["i"] == "860389053784506"

    def test_to_mongo_document_secured_true(self):
        """Documento MongoDB con secured=True para dispositivos actualizados."""
        p = TermoKingSchema(**REAL_PAYLOAD)
        doc = p.to_mongo_document(secured=True)
        assert doc["secured"] is True

    def test_to_mongo_document_has_clock_drift(self):
        """El documento debe incluir clock_drift_seconds cuando hay fecha."""
        p = TermoKingSchema(**REAL_PAYLOAD)
        doc = p.to_mongo_document()
        assert "clock_drift_seconds" in doc
        assert isinstance(doc["clock_drift_seconds"], float)

    def test_extra_fields_allowed(self):
        """Campos extra (protocolo futuro) deben aceptarse sin error."""
        payload = dict(REAL_PAYLOAD, campo_futuro="valor_futuro")
        p = TermoKingSchema(**payload)
        assert p is not None


class TestTunelSchema:

    def test_tunel_follows_same_pattern(self):
        """TunelSchema sigue el mismo patrón que TermoKingSchema."""
        payload = dict(REAL_PAYLOAD)
        p = TunelSchema(**payload)
        assert p.i == "860389053784506"
        assert isinstance(p.fecha, datetime)

    def test_tunel_estado_default(self):
        payload = {k: v for k, v in REAL_PAYLOAD.items() if k != "estado"}
        p = TunelSchema(**payload)
        assert p.estado == 1


class TestComandoSchema:

    def test_comando_schema_minimal(self):
        """ComandoSchema con campos mínimos requeridos."""
        c = ComandoSchema(imei="860389053784506", comando="Trama_Readout(3)")
        assert c.estado == 1
        assert c.status == 1
        assert c.tipo == 0

    def test_comando_schema_full(self):
        c = ComandoSchema(
            imei="test01",
            estado=1,
            comando="Trama_Readout(3)",
            dispositivo="ZGRU1234567",
            user="operador",
            receta="receta_1",
        )
        assert c.dispositivo == "ZGRU1234567"


class TestBusquedaSchemas:

    def test_busqueda_schema_default_values(self):
        b = BusquedaSchema(imei="860389053784506")
        assert b.fecha_inicio == "0"
        assert b.fecha_fin == "0"

    def test_busqueda_general_default_limit(self):
        b = BusquedaGeneral(imei="860389053784506")
        assert b.limit == 100
