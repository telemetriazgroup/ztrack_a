"""Tests parsing Cerro Prieto rs/d02."""
from datetime import datetime

from app.functions.cerro_prieto import (
    CERRO_PRIETO_ACCIONES,
    _serialize_datos_total,
    avanzar_canales,
    canales_iniciales,
    es_lectura_reinicio,
    evaluar_desviacion,
    objetivos_para_api,
    parse_d02,
    parse_inyector_rs,
    parse_rs,
    resolver_accion,
    starcool_bloques_desde_d02,
    tendencia_entre,
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
    assert len(d["flags"]) == 1
    assert d["flags"][0]["label"] == "Estado 10"
    assert d["por_zona"][0]["control"]["activo"] is False
    assert d["por_zona"][0]["control"]["valor"] == 0
    assert d["por_zona"][1]["control"]["activo"] is True
    assert d["por_zona"][2]["control"]["activo"] is False
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


def test_objetivos_para_api_incluye_defaults():
    o = objetivos_para_api({"1": 9, "2": 11, "3": 13}, {"1": 5, "2": 5, "3": 9})
    assert o["co2"]["1"] == 9
    assert o["defaults"]["co2"]["1"] == 8
    assert o["defaults"]["o2"]["3"] == 8


def test_reinicio_no_pisa_ultimo_valido():
    assert es_lectura_reinicio(0) is True
    assert es_lectura_reinicio(0.0) is True
    assert es_lectura_reinicio(25.5) is True
    assert es_lectura_reinicio(25.50) is True
    assert es_lectura_reinicio(6.1) is False
    assert es_lectura_reinicio(None) is False
    assert tendencia_entre(None, 6.1) is None
    assert tendencia_entre(6.0, 6.4) == "sube"
    assert tendencia_entre(6.4, 6.0) == "baja"
    assert tendencia_entre(6.0, 6.0) is None

    canales = canales_iniciales()
    t0 = datetime(2026, 10, 23, 10, 0, 0)
    gases = {
        "co2": {"1": 6.1, "2": 4.7, "3": 8.3},
        "o2": {"1": 4.0, "2": 10.4, "3": 11.9},
    }
    canales, vis = avanzar_canales(canales, gases, t0)
    assert vis["co2"]["1"]["valor"] == 6.1
    assert vis["co2"]["1"]["tendencia"] is None

    gases_sube = {
        "co2": {"1": 6.4, "2": 4.7, "3": 8.0},
        "o2": {"1": 3.5, "2": 10.4, "3": 11.9},
    }
    canales, vis = avanzar_canales(canales, gases_sube, datetime(2026, 10, 23, 10, 1, 0))
    assert vis["co2"]["1"]["tendencia"] == "sube"
    assert vis["co2"]["3"]["tendencia"] == "baja"
    assert vis["o2"]["1"]["tendencia"] == "baja"

    igual = {
        "co2": {"1": 6.4, "2": 4.7, "3": 8.0},
        "o2": {"1": 3.5, "2": 10.4, "3": 11.9},
    }
    canales, vis = avanzar_canales(canales, igual, datetime(2026, 10, 23, 10, 1, 30))
    assert vis["co2"]["1"]["tendencia"] == "sube"
    assert vis["o2"]["1"]["tendencia"] == "baja"
    assert canales["co2"]["1"]["tendencia"] == "sube"

    reinicio = {
        "co2": {"1": 0, "2": 25.5, "3": 8.0},
        "o2": {"1": 25.5, "2": 0, "3": 11.9},
    }
    canales, vis = avanzar_canales(canales, reinicio, datetime(2026, 10, 23, 10, 2, 0))
    assert vis["co2"]["1"]["reinicio"] is True
    assert vis["co2"]["1"]["valor"] == 6.4
    assert vis["co2"]["1"]["tendencia"] == "sube"
    assert vis["co2"]["1"]["valor_crudo"] == 0
    assert vis["co2"]["2"]["valor"] == 4.7
    assert vis["o2"]["1"]["valor"] == 3.5
    assert vis["o2"]["2"]["reinicio"] is True
    assert canales["co2"]["1"]["valor"] == 6.4
    assert canales["o2"]["1"]["valor"] == 3.5


def test_parse_d02_marca_control_en_zonas():
    d = parse_d02("1,2,3,4,5,6,70,80,90,1,1,0,1,0,1")
    assert d["por_zona"][0]["control"]["etiqueta"] == "Control activo"
    assert d["por_zona"][1]["control"]["activo"] is False
    assert d["por_zona"][2]["control"]["activo"] is True
    assert [f["label"] for f in d["flags"]] == ["Estado 10"]


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
