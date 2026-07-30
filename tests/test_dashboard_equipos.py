"""Tests funciones puras del catálogo de equipos del dashboard."""
from app.functions.dashboard_equipos import (
    _snapshot_equipo,
    equipo_para_api,
)


def test_snapshot_equipo_vacio():
    assert _snapshot_equipo(None) == {
        "imei": "",
        "numero_telemetria": "",
        "cliente": "",
        "notas": "",
    }


def test_snapshot_equipo_normaliza():
    doc = {
        "imei": "860389053784506",
        "numero_telemetria": " TK-01 ",
        "cliente": " Cerro Prieto ",
        "notas": "nota",
    }
    snap = _snapshot_equipo(doc)
    assert snap["numero_telemetria"] == "TK-01"
    assert snap["cliente"] == "Cerro Prieto"


def test_equipo_para_api_tipos():
    doc = {
        "imei": "860389053784506",
        "numero_telemetria": "TK-01",
        "cliente": "Cliente X",
        "notas": "",
        "tipos": {
            "TermoKing": {"activo": True},
            "Tunel": {"activo": False},
        },
    }
    out = equipo_para_api(doc)
    assert out["imei"] == "860389053784506"
    assert out["tipos"]["TermoKing"]["activo"] is True
    assert out["tipos"]["Tunel"]["activo"] is False
