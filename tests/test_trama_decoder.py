"""Tests del decodificador de tramas."""
import pytest

from app.functions.trama_decoder import convertir_valor, decode_channel, decode_trama

REAL_D02 = (
    "1B0204000082A7000401FE7F04010C0114012301FF7F0F01FE7FFE7FFE7FFE7F"
    "430000006702FE7FBE013C00BE00C000B800FE7FFE7F1E004B00EA028938000000000000"
    "230000001201FE7F04010401FE7F0000B9056700FE7FFF7F8CE71B"
)


class TestTramaDecoder:

    def test_decode_ascii_d01(self):
        r = decode_channel("d01", "UNIT111")
        assert r["tipo"] == "ascii"
        assert r["texto"] == "UNIT111"

    def test_decode_csv_d07(self):
        r = decode_channel("d07", "0,0,0,0,-1.0")
        assert r["tipo"] == "csv"
        assert r["valores"][-1] == -1.0

    def test_decode_csv_espacios(self):
        raw = "1 32516 1051 0 0 0 0.0"
        r = decode_channel("d07", raw)
        assert r["tipo"] == "csv"
        assert r["valores"] == [1, 32516, 1051, 0, 0, 0, 0.0]

    def test_convertir_valor_escalar_y_lista(self):
        assert convertir_valor("8.6") == 8.6
        assert convertir_valor("1 32516 1051 0 0 0 0.0") == [
            1,
            32516,
            1051,
            0,
            0,
            0,
            0.0,
        ]
        assert convertir_valor("1,2,3") == [1, 2, 3]

    def test_decode_thermoking_1b02(self):
        r = decode_channel("d02", REAL_D02)
        assert r["tipo"] == "thermoking_1b02"
        assert r["cabecera"]["stx"] == "1B"
        assert r["bytes_totales"] > 20
        assert len(r["registros_sin_lectura"]) > 0

    def test_decode_trama_completa(self):
        trama = {"i": "860389053784506", "d01": "UNIT111", "d02": REAL_D02, "d07": "1,2,3"}
        out = decode_trama(trama)
        assert out["imei"] == "860389053784506"
        assert len(out["canales"]) == 3
        assert "1B02" in out["resumen"] or "TermoKing" in out["resumen"]

    def test_prefijo_ff(self):
        r = decode_channel("d00", "FFFFFFFF" + REAL_D02[:40])
        assert r["tipo"] == "thermoking_1b02"
        assert r.get("prefijo_ff_ignorado") is True
