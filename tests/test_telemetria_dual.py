"""Tests lista dual y resumen de documento."""
from app.functions.telemetria_dual import (
    IMEIS_DOBLE_PERSISTENCIA,
    _resumen_doc,
    imei_en_lista_dual,
)


def test_imei_en_lista_dual():
    assert imei_en_lista_dual("868428040551750")
    assert not imei_en_lista_dual("999")
    assert not imei_en_lista_dual("")


def test_resumen_doc_no_incluye_tramas_completas():
    doc = {"i": "868428040551750", "rs": "x" * 100, "d02": "1,2,3"}
    r = _resumen_doc(doc)
    assert r["i"] == "868428040551750"
    assert r["rs_len"] == 100
    assert len(IMEIS_DOBLE_PERSISTENCIA) == 6
