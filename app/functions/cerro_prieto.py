"""
Panel Cerro Prieto — IMEI fijo TermoKing, parsing rs/d02 y cola de comandos PANTALLA.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from app.core.datetime_utils import format_for_display, server_now, timezone_label
from app.database.mongodb import get_control_collection
from app.functions.dashboard import _serialize_comando, _serialize_dt
from app.functions.live_helpers import _ultimo_live_un_imei
from app.functions.termoking import insertar_comando

CERRO_PRIETO_IMEI = "868428044554560"
CERRO_PRIETO_TIPO = "TermoKing"
CERRO_PRIETO_CLIENTE = "cerro_prieto"

# Comandos permitidos (whitelist)
CERRO_PRIETO_ACCIONES: list[dict[str, str]] = [
    {"id": "nitro1", "grupo": "Nitrógeno", "label": "Encender Nitrógeno zona 1", "comando": "PANTALLA:NITRO1*"},
    {"id": "nitro2", "grupo": "Nitrógeno", "label": "Encender Nitrógeno zona 2", "comando": "PANTALLA:NITRO2*"},
    {"id": "nitro3", "grupo": "Nitrógeno", "label": "Encender Nitrógeno zona 3", "comando": "PANTALLA:NITRO3*"},
    {"id": "nitro0", "grupo": "Nitrógeno", "label": "Apagar todos los nitrógenos", "comando": "PANTALLA:NITRO0*"},
    {"id": "co2_1", "grupo": "CO₂", "label": "Encender CO₂ zona 1", "comando": "PANTALLA:CO2_1*"},
    {"id": "co2_2", "grupo": "CO₂", "label": "Encender CO₂ zona 2", "comando": "PANTALLA:CO2_2*"},
    {"id": "co2_3", "grupo": "CO₂", "label": "Encender CO₂ zona 3", "comando": "PANTALLA:CO2_3*"},
    {"id": "co2_0", "grupo": "CO₂", "label": "Apagar todas las zonas de CO₂", "comando": "PANTALLA:CO2_0*"},
    {"id": "comp1_on", "grupo": "Compresores", "label": "Encender Compresor 1", "comando": "PANTALLA:COMP_1_ON*"},
    {"id": "comp1_off", "grupo": "Compresores", "label": "Apagar Compresor 1", "comando": "PANTALLA:COMP_1_OFF*"},
    {"id": "comp2_on", "grupo": "Compresores", "label": "Encender Compresor 2", "comando": "PANTALLA:COMP_2_ON*"},
    {"id": "comp2_off", "grupo": "Compresores", "label": "Apagar Compresor 2", "comando": "PANTALLA:COMP_2_OFF*"},
    {"id": "iny_o0", "grupo": "Inyector", "label": "Activar bypass (pase oxígeno)", "comando": "PANTALLA:INYECTOR:&O0*"},
    {"id": "iny_o1", "grupo": "Inyector", "label": "Desactivar bypass de oxígeno", "comando": "PANTALLA:INYECTOR:&O1*"},
    {"id": "mad_on", "grupo": "Madurador", "label": "Encender Madurador", "comando": "PANTALLA:MADURADOR_ENCENDER*"},
    {"id": "mad_off", "grupo": "Madurador", "label": "Apagar Madurador", "comando": "PANTALLA:MADURADOR_APAGAR*"},
]

_COMANDOS_PERMITIDOS = {a["comando"] for a in CERRO_PRIETO_ACCIONES}
_ACCIONES_POR_ID = {a["id"]: a for a in CERRO_PRIETO_ACCIONES}

# Objetivos predefinidos (%)
OBJETIVOS_CO2_DEFAULT: dict[int, float] = {1: 8.0, 2: 10.0, 3: 12.0}
OBJETIVOS_O2_DEFAULT: dict[int, float] = {1: 4.0, 2: 4.0, 3: 8.0}
TOLERANCIA_OK = 1.0   # ±1 → verde
TOLERANCIA_WARN = 2.0  # ±2 → naranja; fuera → rojo

# Canales STARCOOL por zona (datos leídos del campo d02)
STARCOOL_CANALES: list[tuple[int, str]] = [
    (1, "RIPENER"),
    (2, "REEFER_QUEST"),
    (3, "INYECTOR"),
]


def _compresor_ui(valor: Any) -> dict[str, Any]:
    """0 = apagado (rojo), 1 = encendido (verde)."""
    if valor == 1 or valor == 1.0:
        return {"encendido": True, "estado": "ok", "etiqueta": "Encendido"}
    if valor == 0 or valor == 0.0:
        return {"encendido": False, "estado": "danger", "etiqueta": "Apagado"}
    return {"encendido": None, "estado": "none", "etiqueta": "—"}


def _compresores_desde_flags(flags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Estado 14 → compresor 1, Estado 15 → compresor 2 (campo d02)."""
    by_label = {f.get("label"): f.get("valor") for f in flags}
    out: list[dict[str, Any]] = []
    for estado_n, numero in ((14, 1), (15, 2)):
        valor = by_label.get(f"Estado {estado_n}")
        ui = _compresor_ui(valor)
        out.append(
            {
                "numero": numero,
                "label": f"Compresor {numero}",
                "estado_d02": estado_n,
                "valor": valor,
                **ui,
            }
        )
    return out


def _serialize_datos_total(trama: Optional[dict]) -> Optional[dict[str, Any]]:
    """Última trama completa, lista para mostrar como JSON en el panel."""
    if not trama:
        return None
    out: dict[str, Any] = {}
    for key, value in trama.items():
        if key == "_id":
            continue
        if isinstance(value, datetime):
            out[key] = _serialize_dt(value)
        else:
            out[key] = value
    return out


# Bitmap INYECTOR en rs (16 bits A–P): 0 = encendido, 1 = apagado
_INYECTOR_VALVULAS: list[dict[str, Any]] = [
    {"idx": 4, "letra": "E", "grupo": "CO₂", "zona": 1, "label": "Válvula CO₂ Zona 1"},
    {"idx": 5, "letra": "F", "grupo": "CO₂", "zona": 2, "label": "Válvula CO₂ Zona 2"},
    {"idx": 6, "letra": "G", "grupo": "CO₂", "zona": 3, "label": "Válvula CO₂ Zona 3"},
    {"idx": 7, "letra": "H", "grupo": "Nitrógeno", "zona": 3, "label": "Válvula N₂ Zona 3"},
    {"idx": 8, "letra": "I", "grupo": "Nitrógeno", "zona": 2, "label": "Válvula N₂ Zona 2"},
    {"idx": 9, "letra": "J", "grupo": "Nitrógeno", "zona": 1, "label": "Válvula N₂ Zona 1"},
    {"idx": 14, "letra": "O", "grupo": "Bypass", "zona": None, "label": "Bypass de oxígeno"},
]


def _valvula_inyector_ui(bit: str) -> dict[str, Any]:
    if bit == "0":
        return {"encendido": True, "estado": "ok", "etiqueta": "Encendido"}
    if bit == "1":
        return {"encendido": False, "estado": "danger", "etiqueta": "Apagado"}
    return {"encendido": None, "estado": "none", "etiqueta": "—"}


def parse_inyector_rs(rs: Optional[str]) -> dict[str, Any]:
    """
    Decodifica INYECTOR:0000111111100000,1& — solo el bitmap de 16 bits antes de la coma.
    Posiciones A–D y K–N/P sin uso; E–J válvulas; O bypass oxígeno.
    """
    vacio: dict[str, Any] = {
        "sin_dato": True,
        "bitmap": None,
        "raw_bloque": None,
        "valvulas": [],
        "grupos": {},
        "leyenda": {"0": "Encendido", "1": "Apagado"},
    }
    if not rs or not str(rs).strip():
        return vacio

    bloque = next(
        (b for b in parse_rs(rs) if (b.get("nombre") or "").upper() == "INYECTOR"),
        None,
    )
    if not bloque:
        return vacio

    datos = (bloque.get("datos") or "").strip()
    bitmap = datos.split(",")[0].strip() if datos else ""
    if not bitmap or not all(c in "01" for c in bitmap):
        return {
            **vacio,
            "raw_bloque": bloque.get("raw"),
            "bitmap": bitmap or None,
            "error": "Bitmap INYECTOR inválido (se esperan 16 bits 0/1)",
        }

    bitmap = bitmap.ljust(16, "0")[:16]
    valvulas: list[dict[str, Any]] = []
    grupos: dict[str, list[dict[str, Any]]] = {}
    letras = "ABCDEFGHIJKLMNOP"

    for spec in _INYECTOR_VALVULAS:
        idx = spec["idx"]
        bit = bitmap[idx]
        entry = {**spec, "bit": bit, "posicion": idx + 1, **_valvula_inyector_ui(bit)}
        valvulas.append(entry)
        grupos.setdefault(spec["grupo"], []).append(entry)

    mapa_bits = [
        {"letra": letras[i], "bit": bitmap[i], "usado": i in {s["idx"] for s in _INYECTOR_VALVULAS}}
        for i in range(16)
    ]

    return {
        "sin_dato": False,
        "bitmap": bitmap,
        "raw_bloque": bloque.get("raw"),
        "valvulas": valvulas,
        "grupos": grupos,
        "mapa_bits": mapa_bits,
        "leyenda": {"0": "Encendido", "1": "Apagado"},
    }


def parse_rs(rs: Optional[str]) -> list[dict[str, str]]:
    """Separa bloques RIPENER / REEFER_QUEST / INYECTOR del campo rs."""
    if not rs or not str(rs).strip():
        return []
    out: list[dict[str, str]] = []
    for block in str(rs).split("&"):
        block = block.strip()
        if not block:
            continue
        if ":" in block:
            nombre, _, datos = block.partition(":")
            nombre = nombre.strip()
            datos = datos.strip()
            raw = f"{nombre}:{datos}&"
        else:
            nombre, datos, raw = "?", block, f"{block}&"
        out.append({"nombre": nombre, "datos": datos, "raw": raw})
    return out


def _normalizar_objetivos_por_zona(
    src: Optional[dict],
    default: dict[int, float],
) -> dict[int, float]:
    out = dict(default)
    if not src:
        return out
    for z in (1, 2, 3):
        v = src.get(z) if z in src else src.get(str(z))
        if v is not None:
            try:
                out[z] = float(v)
            except (TypeError, ValueError):
                pass
    return out


def evaluar_desviacion(
    valor: Any,
    objetivo: float,
    tol_ok: float = TOLERANCIA_OK,
    tol_warn: float = TOLERANCIA_WARN,
) -> dict[str, Any]:
    """Verde ±tol_ok, naranja ±tol_warn, rojo fuera de tol_warn."""
    if not isinstance(valor, (int, float)):
        return {
            "estado": "none",
            "desviacion": None,
            "objetivo": objetivo,
        }
    diff = abs(float(valor) - float(objetivo))
    if diff <= tol_ok:
        estado = "ok"
    elif diff <= tol_warn:
        estado = "warn"
    else:
        estado = "danger"
    return {
        "estado": estado,
        "desviacion": round(diff, 2),
        "objetivo": objetivo,
    }


def objetivos_para_api(
    co2: Optional[dict] = None,
    o2: Optional[dict] = None,
) -> dict[str, Any]:
    co2_map = _normalizar_objetivos_por_zona(co2, OBJETIVOS_CO2_DEFAULT)
    o2_map = _normalizar_objetivos_por_zona(o2, OBJETIVOS_O2_DEFAULT)
    return {
        "co2": {str(z): co2_map[z] for z in (1, 2, 3)},
        "o2": {str(z): o2_map[z] for z in (1, 2, 3)},
        "tolerancias": {"ok": TOLERANCIA_OK, "warn": TOLERANCIA_WARN},
        "leyenda": {
            "ok": f"±{TOLERANCIA_OK} % del objetivo (verde)",
            "warn": f"±{TOLERANCIA_WARN} % (naranja)",
            "danger": f"Fuera de ±{TOLERANCIA_WARN} % (rojo)",
        },
    }


def comando_objetivo_co2(zona: int, valor: float) -> str:
    return f"PANTALLA:OBJ_CO2_Z{zona}:{valor:g}*"


def comando_objetivo_o2(zona: int, valor: float) -> str:
    return f"PANTALLA:OBJ_O2_Z{zona}:{valor:g}*"


def parse_d02(
    d02: Optional[str],
    objetivos_co2: Optional[dict] = None,
    objetivos_o2: Optional[dict] = None,
) -> dict[str, Any]:
    """Interpreta CSV d02: CO2, O2 y humedad por zona (primeros 9 valores)."""
    raw = (d02 or "").strip()
    empty: dict[str, Any] = {
        "raw": raw,
        "zonas": [],
        "flags": [],
        "compresores": [],
        "por_zona": [],
    }
    co2_obj = _normalizar_objetivos_por_zona(objetivos_co2, OBJETIVOS_CO2_DEFAULT)
    o2_obj = _normalizar_objetivos_por_zona(objetivos_o2, OBJETIVOS_O2_DEFAULT)

    if not raw:
        return empty

    partes = [p.strip() for p in raw.split(",")]
    valores: list[Any] = []
    for p in partes:
        try:
            valores.append(float(p))
        except ValueError:
            valores.append(p)

    meta = [
        ("co2", 1, "Zona 1 CO₂"),
        ("co2", 2, "Zona 2 CO₂"),
        ("co2", 3, "Zona 3 CO₂"),
        ("o2", 1, "Zona 1 O₂"),
        ("o2", 2, "Zona 2 O₂"),
        ("o2", 3, "Zona 3 O₂"),
        ("humedad", 1, "Zona 1 humedad"),
        ("humedad", 2, "Zona 2 humedad"),
        ("humedad", 3, "Zona 3 humedad"),
    ]

    zonas: list[dict[str, Any]] = []
    for i, (tipo, zona, label) in enumerate(meta):
        if i >= len(valores):
            break
        valor = valores[i]
        entry: dict[str, Any] = {
            "label": label,
            "valor": valor,
            "tipo": tipo,
            "zona": zona,
        }
        if tipo == "co2":
            obj = co2_obj[zona]
            entry.update(evaluar_desviacion(valor, obj))
        elif tipo == "o2":
            obj = o2_obj[zona]
            entry.update(evaluar_desviacion(valor, obj))
        else:
            entry["estado"] = "none"
            entry["objetivo"] = None
            entry["desviacion"] = None
        zonas.append(entry)

    por_zona = []
    for z in (1, 2, 3):
        co2 = next((x for x in zonas if x["tipo"] == "co2" and x["zona"] == z), None)
        o2 = next((x for x in zonas if x["tipo"] == "o2" and x["zona"] == z), None)
        por_zona.append({"zona": z, "co2": co2, "o2": o2})

    flags = [
        {"label": f"Estado {i + 1}", "valor": valores[i]}
        for i in range(9, len(valores))
    ]
    compresores = _compresores_desde_flags(flags)
    flags_otros = [f for f in flags if f["label"] not in ("Estado 14", "Estado 15")]
    parsed = {
        "raw": raw,
        "zonas": zonas,
        "flags": flags_otros,
        "compresores": compresores,
        "por_zona": por_zona,
    }
    parsed["starcool_bloques"] = starcool_bloques_desde_d02(parsed)
    return parsed


def starcool_bloques_desde_d02(d02_data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Arma bloques tipo canal rs (RIPENER, REEFER_QUEST, INYECTOR) desde CSV d02.
    Zona 1 → RIPENER, zona 2 → REEFER_QUEST, zona 3 → INYECTOR.
    """
    bloques: list[dict[str, Any]] = []
    por_zona = d02_data.get("por_zona") or []
    zonas = d02_data.get("zonas") or []

    for z, nombre in STARCOOL_CANALES:
        row = next((r for r in por_zona if r.get("zona") == z), None)
        hum = next(
            (x for x in zonas if x.get("tipo") == "humedad" and x.get("zona") == z),
            None,
        )
        co2 = (row or {}).get("co2") or {}
        o2 = (row or {}).get("o2") or {}

        def _num(entry: dict) -> str:
            v = entry.get("valor") if entry else None
            if isinstance(v, (int, float)):
                return f"{v:g}"
            return ""

        c, o, h = _num(co2), _num(o2), _num(hum)
        if not c and not o and not h:
            continue
        datos = ",".join(p for p in (c, o, h) if p != "")
        bloques.append(
            {
                "nombre": nombre,
                "datos": datos,
                "raw": f"{nombre}:{datos}&",
                "zona": z,
                "co2": co2,
                "o2": o2,
                "humedad": hum,
            }
        )
    return bloques


def _comando_ui(doc: Optional[dict]) -> dict[str, Any]:
    """estado UI: 1 pendiente, 0 ejecutado (según lógica del cliente)."""
    if not doc:
        return {
            "hay_comando": False,
            "comando": None,
            "estado": None,
            "estado_etiqueta": "Sin comandos recientes",
            "pendiente": False,
        }
    estado_int = int(doc.get("estado") or 0)
    status = int(doc.get("status") or 1)
    pendiente = estado_int > 0 and status != 2
    return {
        "hay_comando": True,
        "comando": doc.get("comando"),
        "estado": 1 if pendiente else 0,
        "estado_etiqueta": "Pendiente" if pendiente else "Ejecutado",
        "pendiente": pendiente,
        "status": status,
        "estado_intentos": estado_int,
        "fecha_creacion": _serialize_dt(doc.get("fecha_creacion")),
        "fecha_creacion_display": format_for_display(
            doc.get("fecha_creacion"), with_timezone=False
        ),
        "fecha_ejecucion": _serialize_dt(doc.get("fecha_ejecucion")),
        "fecha_ejecucion_display": format_for_display(
            doc.get("fecha_ejecucion"), with_timezone=False
        ),
        "user": doc.get("user"),
    }


async def _buscar_comandos_recientes(dias: int = 30, limite: int = 20) -> list[dict]:
    now = server_now()
    now_naive = now.replace(tzinfo=None) if now.tzinfo else now
    inicio = now_naive - timedelta(days=max(dias, 1))
    imei = CERRO_PRIETO_IMEI
    encontrados: list[dict] = []

    y, m = now_naive.year, now_naive.month
    meses = 3
    for _ in range(meses):
        col = get_control_collection(CERRO_PRIETO_TIPO, datetime(y, m, 1))
        cursor = col.find(
            {"imei": imei, "fecha_creacion": {"$gte": inicio}},
            {"_id": 0},
        ).sort("fecha_creacion", -1).limit(limite)
        encontrados.extend(await cursor.to_list(length=limite))
        if m == 1:
            m, y = 12, y - 1
        else:
            m -= 1

    def _key(d: dict) -> datetime:
        f = d.get("fecha_creacion")
        return f if isinstance(f, datetime) else datetime.min

    encontrados.sort(key=_key, reverse=True)
    return encontrados[:limite]


async def _ultimo_comando_cola() -> Optional[dict]:
    """Último comando pendiente en cola (estado > 0)."""
    now = server_now()
    now_naive = now.replace(tzinfo=None) if now.tzinfo else now
    y, m = now_naive.year, now_naive.month
    for _ in range(3):
        col = get_control_collection(CERRO_PRIETO_TIPO, datetime(y, m, 1))
        doc = await col.find_one(
            {"imei": CERRO_PRIETO_IMEI, "estado": {"$gt": 0}},
            {"_id": 0},
            sort=[("fecha_creacion", -1)],
        )
        if doc:
            return doc
        if m == 1:
            m, y = 12, y - 1
        else:
            m -= 1
    return None


async def obtener_panel_estado() -> dict[str, Any]:
    trama = await _ultimo_live_un_imei(CERRO_PRIETO_IMEI, CERRO_PRIETO_TIPO)
    comandos = await _buscar_comandos_recientes()
    ultimo_cualquiera = comandos[0] if comandos else None
    pendiente_doc = await _ultimo_comando_cola()

    fecha_trama = None
    fecha_display = None
    if trama:
        fecha_trama = _serialize_dt(trama.get("fecha") or trama.get("received_at"))
        fecha_display = format_for_display(
            trama.get("fecha") or trama.get("received_at"),
            with_timezone=False,
        )

    rs = trama.get("rs") if trama else None
    d02 = trama.get("d02") if trama else None
    objetivos = objetivos_para_api()
    d02_parsed = parse_d02(
        d02,
        objetivos_co2=objetivos["co2"],
        objetivos_o2=objetivos["o2"],
    )

    return {
        "cliente": CERRO_PRIETO_CLIENTE,
        "imei": CERRO_PRIETO_IMEI,
        "tipo": CERRO_PRIETO_TIPO,
        "zona_horaria": timezone_label(),
        "ultima_actualizacion": fecha_trama,
        "ultima_actualizacion_display": fecha_display,
        "sin_datos": trama is None,
        "objetivos": objetivos,
        "rs": parse_rs(rs),
        "rs_raw": rs,
        "inyector": parse_inyector_rs(rs),
        "datos_total": _serialize_datos_total(trama),
        "starcool": {
            "fuente": "d02",
            "bloques": d02_parsed.get("starcool_bloques") or [],
        },
        "d02": d02_parsed,
        "d02_raw": d02,
        "ultimo_comando": _comando_ui(ultimo_cualquiera),
        "comando_pendiente": _comando_ui(pendiente_doc),
        "comandos_recientes": [_serialize_comando(c) for c in comandos[:10]],
        "acciones": CERRO_PRIETO_ACCIONES,
    }


def resolver_accion(accion_id: Optional[str], comando: Optional[str]) -> Optional[dict]:
    if accion_id and accion_id in _ACCIONES_POR_ID:
        return _ACCIONES_POR_ID[accion_id]
    if comando and comando in _COMANDOS_PERMITIDOS:
        for a in CERRO_PRIETO_ACCIONES:
            if a["comando"] == comando:
                return a
    return None


async def enviar_comando_panel(
    accion_id: Optional[str] = None,
    comando: Optional[str] = None,
    user: str = "cerro_prieto_panel",
) -> dict[str, Any]:
    accion = resolver_accion(accion_id, comando)
    if not accion:
        return {"ok": False, "error": "Acción o comando no permitido"}

    cmd = accion["comando"]
    doc = {
        "imei": CERRO_PRIETO_IMEI,
        "comando": cmd,
        "estado": 1,
        "status": 1,
        "user": user or "cerro_prieto_panel",
        "dispositivo": CERRO_PRIETO_CLIENTE,
        "evento": accion["label"],
    }
    insertado = await insertar_comando(doc)
    return {
        "ok": True,
        "mensaje": "Comando encolado; se enviará en el próximo POST del dispositivo",
        "accion": accion,
        "comando_insertado": _serialize_comando(insertado) if insertado else doc,
    }


async def aplicar_objetivos_panel(
    co2: Optional[dict] = None,
    o2: Optional[dict] = None,
    user: str = "cerro_prieto_panel",
) -> dict[str, Any]:
    """Encola comandos PANTALLA:OBJ_CO2_Z* y PANTALLA:OBJ_O2_Z* por zona."""
    co2_map = _normalizar_objetivos_por_zona(co2, OBJETIVOS_CO2_DEFAULT)
    o2_map = _normalizar_objetivos_por_zona(o2, OBJETIVOS_O2_DEFAULT)
    insertados: list[dict] = []

    for z in (1, 2, 3):
        cmd = comando_objetivo_co2(z, co2_map[z])
        doc = {
            "imei": CERRO_PRIETO_IMEI,
            "comando": cmd,
            "estado": 1,
            "status": 1,
            "user": user,
            "dispositivo": CERRO_PRIETO_CLIENTE,
            "evento": f"Objetivo CO₂ zona {z}: {co2_map[z]:g}%",
        }
        row = await insertar_comando(doc)
        insertados.append(_serialize_comando(row) if row else doc)

    for z in (1, 2, 3):
        cmd = comando_objetivo_o2(z, o2_map[z])
        doc = {
            "imei": CERRO_PRIETO_IMEI,
            "comando": cmd,
            "estado": 1,
            "status": 1,
            "user": user,
            "dispositivo": CERRO_PRIETO_CLIENTE,
            "evento": f"Objetivo O₂ zona {z}: {o2_map[z]:g}%",
        }
        row = await insertar_comando(doc)
        insertados.append(_serialize_comando(row) if row else doc)

    return {
        "ok": True,
        "mensaje": "6 comandos de objetivos encolados",
        "objetivos": objetivos_para_api(co2_map, o2_map),
        "comandos_insertados": insertados,
    }
