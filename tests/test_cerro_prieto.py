"""Tests parsing Cerro Prieto rs/d02."""
from datetime import datetime

from app.functions.cerro_prieto import (
    CERRO_PRIETO_ACCIONES,
    _serialize_datos_total,
    evaluar_desviacion,
    parse_d02,
    parse_inyector_rs,
    parse_rs,
    resolver_accion,
    starcool_bloques_desde_d02,
)

RS_EJEMPLO = (
    "RIPENER:0,20.0,26.8,27.3,27.1,29.2,0.0,0.0,0.0,0.0,90,0,0.0,0.0,95.0,2.0,0,0.0&"
    "REEFER_QUEST:1,5.0,5.1,6.5,2.2,36.3,0.0,0.0,0.0,0.0,82,10,1.2,19.2,254.0,1.0&"
    "INYECTOR:0000111101100010,1&"
)

D02_EJEMPLO = "8.6,9.1,10.0,3.1,8.4,2.9,87.8,88.6,100.0,1,0,1,0,1,1"


def test_parse_inyector_bitmap():
    inj = parse_inyector_rs(RS_EJEMPLO)
    assert inj["sin_dato"] is False
    assert inj["bitmap"] == "0000111101100010"
    assert len(inj["valvulas"]) == 7
    e = next(v for v in inj["valvulas"] if v["letra"] == "E")
    assert e["bit"] == "0" and e["etiqueta"] == "Encendido"
    f = next(v for v in inj["valvulas"] if v["letra"] == "F")
    assert f["bit"] == "1" and f["etiqueta"] == "Apagado"
    o = next(v for v in inj["valvulas"] if v["letra"] == "O")
    assert o["bit"] == "1" and o["etiqueta"] == "Apagado"


def test_parse_inyector_ejemplo_md():
    rs = (
        "RIPENER:0,20.0&REEFER_QUEST:1,5.0&INYECTOR:0000111111100000,1&"
    )
    inj = parse_inyector_rs(rs)
    assert inj["bitmap"] == "0000111111100000"
    assert next(v for v in inj["valvulas"] if v["letra"] == "E")["bit"] == "0"
    assert next(v for v in inj["valvulas"] if v["letra"] == "O")["bit"] == "0"


def test_parse_rs_tres_bloques():
    bloques = parse_rs(RS_EJEMPLO)
    assert len(bloques) == 3
    assert bloques[0]["nombre"] == "RIPENER"
    assert bloques[1]["nombre"] == "REEFER_QUEST"
    assert bloques[2]["nombre"] == "INYECTOR"
    assert bloques[0]["raw"].endswith("&")


def test_parse_d02_zonas():
    d = parse_d02(D02_EJEMPLO)
    assert len(d["zonas"]) == 9
    assert d["zonas"][0]["valor"] == 8.6
    assert d["zonas"][0]["tipo"] == "co2"
    assert d["zonas"][0]["estado"] == "ok"
    assert d["zonas"][3]["valor"] == 3.1
    assert d["zonas"][3]["tipo"] == "o2"
    assert d["zonas"][3]["estado"] == "ok"
    assert len(d["por_zona"]) == 3
    assert len(d["flags"]) == 4
    assert len(d["compresores"]) == 2
    assert d["compresores"][0]["numero"] == 1
    assert d["compresores"][0]["valor"] == 1
    assert d["compresores"][0]["estado"] == "ok"
    assert d["compresores"][0]["etiqueta"] == "Encendido"
    assert d["compresores"][1]["numero"] == 2
    assert d["compresores"][1]["valor"] == 1
    assert d["compresores"][1]["estado"] == "ok"


def test_starcool_bloques_desde_d02():
    d = parse_d02(D02_EJEMPLO)
    bloques = starcool_bloques_desde_d02(d)
    assert len(bloques) == 3
    assert bloques[0]["nombre"] == "RIPENER"
    assert bloques[1]["nombre"] == "REEFER_QUEST"
    assert bloques[2]["nombre"] == "INYECTOR"
    assert bloques[0]["co2"]["valor"] == 8.6
    assert "RIPENER:8.6" in bloques[0]["raw"]


def test_serialize_datos_total():
    trama = {
        "_id": "omit",
        "i": "868428044554560",
        "rs": RS_EJEMPLO,
        "d02": D02_EJEMPLO,
        "fecha": datetime(2026, 3, 19, 14, 30, 0),
    }
    out = _serialize_datos_total(trama)
    assert out is not None
    assert "_id" not in out
    assert out["i"] == "868428044554560"
    assert out["d02"] == D02_EJEMPLO
    assert isinstance(out["fecha"], str)


def test_evaluar_desviacion_colores():
    assert evaluar_desviacion(8.5, 8.0)["estado"] == "ok"
    assert evaluar_desviacion(9.5, 8.0)["estado"] == "warn"
    assert evaluar_desviacion(11.0, 8.0)["estado"] == "danger"


def test_resolver_accion_whitelist():
    a = resolver_accion("nitro1", None)
    assert a is not None
    assert a["comando"] == "PANTALLA:NITRO1*"
    assert resolver_accion(None, "PANTALLA:INVALID*") is None
    assert len(CERRO_PRIETO_ACCIONES) == 16
