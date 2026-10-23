"""
Panel Cerro Prieto — IMEI fijo TermoKing, parsing rs/d02 y cola de comandos PANTALLA.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Optional

from app.core.datetime_utils import format_for_display, parse_stored_datetime, server_now, timezone_label
from app.core.logging import get_logger
from app.database.mongodb import bd_gene, collection, get_control_collection
from app.functions.dashboard import _serialize_comando, _serialize_dt
from app.functions.guardar_datos import COMANDO_ESTADO_CANCELADO, COMANDO_ESTADO_PENDIENTE
from app.functions.live_helpers import _ultimo_live_un_imei
from app.functions.termoking import insertar_comando

logger = get_logger(__name__)

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

# 0 y 25.5 en CO₂/O₂: el sensor reinició la lectura (no es un valor real).
LECTURA_REINICIO = (0.0, 25.5)
# Estado 11/12/13 del d02 → control activo (1) en zona 1/2/3.
CONTROL_ESTADO_POR_ZONA = {1: 11, 2: 12, 3: 13}
_ESTADOS_EN_ZONA = {11, 12, 13, 14, 15}
LECTURAS_LIMITE = 1000
_LECTURAS_SNAPSHOT_ID = f"lecturas_ultimo_{CERRO_PRIETO_IMEI}"
_SEMILLA_LECTURAS = 2
_INDICE_LECTURAS_LISTO = False

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

    bloques = parse_rs(rs)
    bloque = next(
        (b for b in bloques if (b.get("nombre") or "").upper() == "INYECTOR"),
        None,
    )
    if not bloque:
        m = re.search(r"INYECTOR:([^&]+)", str(rs), re.IGNORECASE)
        if m:
            datos_fb = m.group(1).strip()
            bloque = {"nombre": "INYECTOR", "datos": datos_fb, "raw": m.group(0) + "&"}
        else:
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


def es_lectura_reinicio(valor: Any) -> bool:
    """0 o 25.5 en CO₂/O₂: el equipo reinició la lectura."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return False
    v = float(valor)
    return abs(v) < 1e-9 or abs(v - 25.5) < 1e-6


def tendencia_entre(anterior: Optional[float], nuevo: float) -> Optional[str]:
    """sube / baja. Sin flecha si no hay valor previo o si no cambió."""
    if anterior is None:
        return None
    if float(nuevo) > float(anterior) + 1e-9:
        return "sube"
    if float(nuevo) < float(anterior) - 1e-9:
        return "baja"
    return None


def canales_iniciales() -> dict[str, dict[str, dict[str, Any]]]:
    vacio = {"valor": None, "anterior": None, "tendencia": None, "fecha": None}
    return {
        gas: {str(z): dict(vacio) for z in (1, 2, 3)}
        for gas in ("co2", "o2")
    }


def _copiar_canales(canales: dict) -> dict[str, dict[str, dict[str, Any]]]:
    out = canales_iniciales()
    for gas in ("co2", "o2"):
        src = (canales or {}).get(gas) or {}
        for z in ("1", "2", "3"):
            c = src.get(z) or {}
            fecha = c.get("fecha")
            if not isinstance(fecha, datetime):
                fecha = parse_stored_datetime(fecha)
            out[gas][z] = {
                "valor": _float_o_none(c.get("valor")),
                "anterior": _float_o_none(c.get("anterior")),
                "tendencia": c.get("tendencia") if c.get("tendencia") in ("sube", "baja") else None,
                "fecha": fecha,
            }
    return out


def _float_o_none(valor: Any) -> Optional[float]:
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def punto_gases(parsed: dict) -> dict[str, dict[str, Any]]:
    """Valores crudos de CO₂/O₂ y control por zona, antes de sustituir reinicios."""
    out: dict[str, dict[str, Any]] = {"co2": {}, "o2": {}, "control": {}}
    for row in parsed.get("por_zona") or []:
        z = str(row.get("zona"))
        for gas in ("co2", "o2"):
            entry = row.get(gas) or {}
            out[gas][z] = _float_o_none(entry.get("valor_crudo", entry.get("valor")))
        ctrl = row.get("control") or {}
        out["control"][z] = ctrl.get("valor")
    return out


def avanzar_canales(
    canales: dict,
    gases: dict,
    fecha: Optional[datetime],
) -> tuple[dict, dict[str, dict[str, dict[str, Any]]]]:
    """
    Avanza el último valor válido. 0 y 25.5 no reemplazan la lectura:
    la pantalla sigue mostrando el último valor real y su tendencia.
    """
    nuevos = _copiar_canales(canales)
    visibles: dict[str, dict[str, dict[str, Any]]] = {"co2": {}, "o2": {}}
    for gas in ("co2", "o2"):
        crudos = (gases or {}).get(gas) or {}
        for z in ("1", "2", "3"):
            crudo = _float_o_none(crudos.get(z))
            estado = nuevos[gas][z]
            reinicio = crudo is not None and es_lectura_reinicio(crudo)
            if reinicio or crudo is None:
                visibles[gas][z] = {
                    "valor_crudo": crudo,
                    "valor": estado["valor"],
                    "reinicio": reinicio,
                    "tendencia": estado["tendencia"] if estado["valor"] is not None else None,
                    "anterior": estado["anterior"],
                    "fecha_valida": estado["fecha"],
                }
                continue
            anterior = estado["valor"]
            if anterior is not None and abs(float(crudo) - float(anterior)) <= 1e-9:
                # Misma lectura: se conserva la última subida o bajada.
                tendencia = estado["tendencia"]
                anterior_ref = estado["anterior"]
            else:
                tendencia = tendencia_entre(anterior, crudo)
                anterior_ref = anterior
            nuevos[gas][z] = {
                "valor": float(crudo),
                "anterior": anterior_ref,
                "tendencia": tendencia,
                "fecha": fecha,
            }
            visibles[gas][z] = {
                "valor_crudo": float(crudo),
                "valor": float(crudo),
                "reinicio": False,
                "tendencia": tendencia,
                "anterior": anterior_ref,
                "fecha_valida": fecha,
            }
    return nuevos, visibles


def visibles_para_muestra(canales: dict, gases: dict) -> dict[str, dict[str, dict[str, Any]]]:
    """
    Arma lo que debe verse ahora.
    Si el snapshot ya incorporó esta muestra válida, usa su tendencia.
    Si la muestra es reinicio, conserva el último válido del snapshot.
    """
    base = _copiar_canales(canales)
    visibles: dict[str, dict[str, dict[str, Any]]] = {"co2": {}, "o2": {}}
    for gas in ("co2", "o2"):
        crudos = (gases or {}).get(gas) or {}
        for z in ("1", "2", "3"):
            crudo = _float_o_none(crudos.get(z))
            estado = base[gas][z]
            reinicio = crudo is not None and es_lectura_reinicio(crudo)
            if reinicio or crudo is None:
                visibles[gas][z] = {
                    "valor_crudo": crudo,
                    "valor": estado["valor"],
                    "reinicio": reinicio,
                    "tendencia": estado["tendencia"] if estado["valor"] is not None else None,
                    "anterior": estado["anterior"],
                    "fecha_valida": estado["fecha"],
                }
                continue
            if estado["valor"] is not None and abs(estado["valor"] - float(crudo)) <= 1e-9:
                valor = estado["valor"]
                tendencia = estado["tendencia"]
                anterior = estado["anterior"]
                fecha_valida = estado["fecha"]
            else:
                valor = float(crudo)
                anterior = estado["valor"]
                tendencia = tendencia_entre(anterior, valor)
                fecha_valida = None
            visibles[gas][z] = {
                "valor_crudo": float(crudo),
                "valor": valor,
                "reinicio": False,
                "tendencia": tendencia,
                "anterior": anterior,
                "fecha_valida": fecha_valida,
            }
    return visibles


def _aplicar_visibles(parsed: dict, visibles: dict) -> None:
    """Sustituye 0/25.5 por el último válido y recalcula color contra el objetivo."""
    for row in parsed.get("por_zona") or []:
        z = str(row.get("zona"))
        for gas in ("co2", "o2"):
            entry = row.get(gas)
            if not entry:
                continue
            info = (visibles.get(gas) or {}).get(z) or {}
            entry["valor_crudo"] = info.get("valor_crudo", entry.get("valor"))
            entry["reinicio"] = bool(info.get("reinicio"))
            entry["tendencia"] = info.get("tendencia")
            entry["valor_anterior"] = info.get("anterior")
            entry["valor"] = info.get("valor")
            fecha_valida = info.get("fecha_valida")
            entry["fecha_valida_display"] = (
                format_for_display(fecha_valida, with_timezone=False) if fecha_valida else None
            )
            obj = entry.get("objetivo")
            if obj is not None:
                entry.update(evaluar_desviacion(entry.get("valor"), obj))
                entry["objetivo"] = obj
    parsed["starcool_bloques"] = starcool_bloques_desde_d02(parsed)


def _valor_estado(valores: list[Any], estado_n: int) -> Any:
    idx = estado_n - 1
    if idx < 0 or idx >= len(valores):
        return None
    return valores[idx]


def _control_desde_valor(valor: Any) -> dict[str, Any]:
    """Estado 11/12/13: 1 = control activo en la zona."""
    if valor == 1 or valor == 1.0:
        return {"valor": valor, "activo": True, "etiqueta": "Control activo"}
    if valor == 0 or valor == 0.0:
        return {"valor": valor, "activo": False, "etiqueta": "Control inactivo"}
    return {"valor": valor, "activo": None, "etiqueta": "Sin dato de control"}


OBJETIVOS_PANEL_COL = "cerro_prieto_panel"
_OBJETIVOS_DOC_ID = f"objetivos_{CERRO_PRIETO_IMEI}"


def _objetivos_maps_para_api(
    co2_map: dict[int, float],
    o2_map: dict[int, float],
) -> dict[str, dict[str, float]]:
    return {
        "co2": {str(z): co2_map[z] for z in (1, 2, 3)},
        "o2": {str(z): o2_map[z] for z in (1, 2, 3)},
    }


def objetivos_para_api(
    co2: Optional[dict] = None,
    o2: Optional[dict] = None,
    *,
    actualizado: Optional[datetime] = None,
    actualizado_display: Optional[str] = None,
    user: Optional[str] = None,
) -> dict[str, Any]:
    co2_map = _normalizar_objetivos_por_zona(co2, OBJETIVOS_CO2_DEFAULT)
    o2_map = _normalizar_objetivos_por_zona(o2, OBJETIVOS_O2_DEFAULT)
    out: dict[str, Any] = {
        **_objetivos_maps_para_api(co2_map, o2_map),
        "defaults": _objetivos_maps_para_api(OBJETIVOS_CO2_DEFAULT, OBJETIVOS_O2_DEFAULT),
        "tolerancias": {"ok": TOLERANCIA_OK, "warn": TOLERANCIA_WARN},
        "leyenda": {
            "ok": f"±{TOLERANCIA_OK} % del objetivo (verde)",
            "warn": f"±{TOLERANCIA_WARN} % (naranja)",
            "danger": f"Fuera de ±{TOLERANCIA_WARN} % (rojo)",
        },
    }
    if actualizado is not None:
        out["actualizado"] = _serialize_dt(actualizado)
    if actualizado_display is not None:
        out["actualizado_display"] = actualizado_display
    if user:
        out["user"] = user
    return out


def _serialize_historial_objetivos(doc: dict) -> dict[str, Any]:
    return {
        "fecha": _serialize_dt(doc.get("fecha")),
        "fecha_display": format_for_display(doc.get("fecha"), with_timezone=False),
        "user": doc.get("user"),
        "motivo": doc.get("motivo"),
        "anterior": doc.get("anterior"),
        "nuevo": doc.get("nuevo"),
    }


async def _objetivos_panel_col():
    return collection(OBJETIVOS_PANEL_COL)


async def obtener_objetivos_guardados() -> dict[str, Any]:
    """Objetivos persistidos o valores predeterminados si no hay registro."""
    col = await _objetivos_panel_col()
    doc = await col.find_one({"_id": _OBJETIVOS_DOC_ID}, {"_id": 0})
    if not doc:
        return objetivos_para_api()
    return objetivos_para_api(
        doc.get("co2"),
        doc.get("o2"),
        actualizado=doc.get("actualizado"),
        actualizado_display=format_for_display(doc.get("actualizado"), with_timezone=False),
        user=doc.get("user"),
    )


async def listar_historial_objetivos(limite: int = 15) -> list[dict[str, Any]]:
    col = await _objetivos_panel_col()
    cursor = col.find(
        {"tipo": "objetivos_historial", "imei": CERRO_PRIETO_IMEI},
        {"_id": 0},
    ).sort("fecha", -1).limit(limite)
    docs = await cursor.to_list(length=limite)
    return [_serialize_historial_objetivos(d) for d in docs]


async def guardar_objetivos_con_historial(
    co2_map: dict[int, float],
    o2_map: dict[int, float],
    *,
    user: str,
    motivo: str = "aplicar",
) -> dict[str, Any]:
    """Persiste objetivos y registra valores anteriores en historial."""
    col = await _objetivos_panel_col()
    now = server_now()
    anterior_doc = await col.find_one({"_id": _OBJETIVOS_DOC_ID}, {"_id": 0})
    anterior_co2 = _normalizar_objetivos_por_zona(
        (anterior_doc or {}).get("co2"), OBJETIVOS_CO2_DEFAULT
    )
    anterior_o2 = _normalizar_objetivos_por_zona(
        (anterior_doc or {}).get("o2"), OBJETIVOS_O2_DEFAULT
    )
    anterior = _objetivos_maps_para_api(anterior_co2, anterior_o2)
    nuevo = _objetivos_maps_para_api(co2_map, o2_map)

    cambio = anterior != nuevo or not anterior_doc
    if cambio:
        await col.insert_one(
            {
                "tipo": "objetivos_historial",
                "imei": CERRO_PRIETO_IMEI,
                "fecha": now,
                "user": user,
                "motivo": motivo,
                "anterior": anterior,
                "nuevo": nuevo,
            }
        )

    await col.update_one(
        {"_id": _OBJETIVOS_DOC_ID},
        {
            "$set": {
                "imei": CERRO_PRIETO_IMEI,
                "co2": nuevo["co2"],
                "o2": nuevo["o2"],
                "actualizado": now,
                "user": user,
            }
        },
        upsert=True,
    )

    return objetivos_para_api(
        co2_map,
        o2_map,
        actualizado=now,
        actualizado_display=format_for_display(now, with_timezone=False),
        user=user,
    )


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
        control = _control_desde_valor(_valor_estado(valores, CONTROL_ESTADO_POR_ZONA[z]))
        por_zona.append({"zona": z, "co2": co2, "o2": o2, "control": control})

    flags = [
        {"label": f"Estado {i + 1}", "valor": valores[i]}
        for i in range(9, len(valores))
    ]
    compresores = _compresores_desde_flags(flags)
    flags_otros = [
        f for f in flags if f["label"] not in {f"Estado {n}" for n in _ESTADOS_EN_ZONA}
    ]
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
    """estado UI: 1 pendiente, 0 ejecutado, 3 cancelado."""
    if not doc:
        return {
            "hay_comando": False,
            "comando": None,
            "estado": None,
            "estado_etiqueta": "Sin comandos recientes",
            "pendiente": False,
            "cancelado": False,
        }
    estado_int = int(doc.get("estado") if doc.get("estado") is not None else -1)
    status = int(doc.get("status") or 1)
    cancelado = estado_int == COMANDO_ESTADO_CANCELADO
    pendiente = estado_int == COMANDO_ESTADO_PENDIENTE and status != 2
    if cancelado:
        etiqueta = "Cancelado"
        estado_ui = COMANDO_ESTADO_CANCELADO
    elif pendiente:
        etiqueta = "Pendiente"
        estado_ui = 1
    else:
        etiqueta = "Ejecutado"
        estado_ui = 0
    return {
        "hay_comando": True,
        "comando": doc.get("comando"),
        "estado": estado_ui,
        "estado_etiqueta": etiqueta,
        "pendiente": pendiente,
        "cancelado": cancelado,
        "status": status,
        "estado_raw": estado_int,
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
    """Último comando pendiente en cola (estado = 1)."""
    now = server_now()
    now_naive = now.replace(tzinfo=None) if now.tzinfo else now
    y, m = now_naive.year, now_naive.month
    for _ in range(3):
        col = get_control_collection(CERRO_PRIETO_TIPO, datetime(y, m, 1))
        doc = await col.find_one(
            {"imei": CERRO_PRIETO_IMEI, "estado": COMANDO_ESTADO_PENDIENTE},
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


def _fecha_naive(fecha: Any) -> Optional[datetime]:
    if fecha is None:
        return None
    if not isinstance(fecha, datetime):
        fecha = parse_stored_datetime(fecha)
    if not isinstance(fecha, datetime):
        return None
    if fecha.tzinfo is not None:
        return fecha.replace(tzinfo=None)
    return fecha


def _fecha_de_trama(trama: Optional[dict]) -> Optional[datetime]:
    if not trama:
        return None
    fecha = trama.get("fecha") or trama.get("received_at")
    if not isinstance(fecha, datetime):
        fecha = parse_stored_datetime(fecha)
    return _fecha_naive(fecha)


def _iter_meses(desde: datetime, hasta: datetime):
    y, m = desde.year, desde.month
    fin = (hasta.year, hasta.month)
    while (y, m) <= fin:
        yield datetime(y, m, 1)
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1


def _rango_dias(desde: str, hasta: str) -> tuple[datetime, datetime]:
    try:
        d0 = datetime.strptime(desde, "%Y-%m-%d")
        d1 = datetime.strptime(hasta, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ValueError("Use fechas AAAA-MM-DD") from exc
    if d1 < d0:
        raise ValueError("La fecha hasta no puede ser anterior a desde")
    if (d1 - d0).days > 62:
        raise ValueError("El rango máximo es de 62 días")
    inicio = datetime(d0.year, d0.month, d0.day, 0, 0, 0)
    fin = datetime(d1.year, d1.month, d1.day, 23, 59, 59, 999999)
    return inicio, fin


async def _asegurar_indice_lecturas() -> None:
    global _INDICE_LECTURAS_LISTO
    if _INDICE_LECTURAS_LISTO:
        return
    col = await _objetivos_panel_col()
    try:
        await col.create_index(
            [("tipo", 1), ("imei", 1), ("fecha", 1)],
            unique=True,
            partialFilterExpression={"tipo": "lectura_gas"},
            name="lectura_gas_unica",
        )
    except Exception as exc:
        logger.warning("indice lecturas cerro prieto", error=str(exc))
    _INDICE_LECTURAS_LISTO = True


async def _tramas_d02_entre(
    desde: datetime,
    hasta: datetime,
    limite: int = LECTURAS_LIMITE,
) -> list[dict]:
    """Tramas del equipo en el rango, de la más antigua a la más reciente."""
    if limite <= 0:
        return []
    chunks: list[dict] = []
    restantes = limite
    meses = list(_iter_meses(desde, hasta))
    for dt in reversed(meses):
        if restantes <= 0:
            break
        col = collection(bd_gene(CERRO_PRIETO_IMEI, CERRO_PRIETO_TIPO, dt))
        try:
            cursor = col.find(
                {
                    "fecha": {"$gte": desde, "$lte": hasta},
                    "d02": {"$nin": [None, ""]},
                },
                {"_id": 0, "fecha": 1, "d02": 1},
            ).sort("fecha", -1).limit(restantes)
            docs = await cursor.to_list(length=restantes)
        except Exception as exc:
            logger.warning(
                "lectura telemetria cerro prieto",
                mes=dt.strftime("%m-%Y"),
                error=str(exc),
            )
            continue
        chunks.extend(docs)
        restantes -= len(docs)
    chunks.sort(key=lambda d: d.get("fecha") or datetime.min)
    return chunks


def _punto_desde_doc(doc: dict) -> Optional[dict[str, Any]]:
    fecha = doc.get("fecha")
    if not isinstance(fecha, datetime):
        fecha = parse_stored_datetime(fecha)
    fecha = _fecha_naive(fecha)
    if fecha is None:
        return None
    parsed = parse_d02(doc.get("d02"))
    gases = punto_gases(parsed)
    return {"fecha": fecha, "parsed": parsed, **gases}


async def _guardar_puntos(puntos: list[dict]) -> None:
    if not puntos:
        return
    from pymongo import UpdateOne

    await _asegurar_indice_lecturas()
    col = await _objetivos_panel_col()
    ops = [
        UpdateOne(
            {
                "tipo": "lectura_gas",
                "imei": CERRO_PRIETO_IMEI,
                "fecha": p["fecha"],
            },
            {
                "$setOnInsert": {
                    "tipo": "lectura_gas",
                    "imei": CERRO_PRIETO_IMEI,
                    "fecha": p["fecha"],
                    "co2": p.get("co2") or {},
                    "o2": p.get("o2") or {},
                    "control": p.get("control") or {},
                }
            },
            upsert=True,
        )
        for p in puntos
        if p.get("fecha") is not None
    ]
    if not ops:
        return
    try:
        await col.bulk_write(ops, ordered=False)
    except Exception as exc:
        logger.warning("guardar lecturas cerro prieto", error=str(exc), n=len(ops))


def _gas_publico(info: Optional[dict]) -> Optional[dict]:
    if not info:
        return info
    out = dict(info)
    fecha = out.pop("fecha_valida", None)
    out["fecha_valida_display"] = (
        format_for_display(fecha, with_timezone=False) if fecha else None
    )
    return out


def _fila_lectura(fecha: datetime, parsed: dict, visibles: dict) -> dict[str, Any]:
    zonas = []
    for row in parsed.get("por_zona") or []:
        z = row.get("zona")
        key = str(z)
        zonas.append(
            {
                "zona": z,
                "co2": _gas_publico(visibles.get("co2", {}).get(key)),
                "o2": _gas_publico(visibles.get("o2", {}).get(key)),
                "control": row.get("control"),
            }
        )
    return {
        "fecha": _serialize_dt(fecha),
        "fecha_display": format_for_display(fecha, with_timezone=False),
        "zonas": zonas,
    }


def _serie_visible(puntos: list[dict], canales: Optional[dict] = None) -> tuple[dict, list[dict]]:
    estado = _copiar_canales(canales or canales_iniciales())
    filas: list[dict] = []
    ultima: Optional[datetime] = None
    for p in puntos:
        fecha = _fecha_naive(p.get("fecha"))
        if fecha is None or (ultima is not None and fecha <= ultima):
            continue
        estado, visibles = avanzar_canales(estado, p, fecha)
        filas.append(_fila_lectura(fecha, p.get("parsed") or {"por_zona": []}, visibles))
        ultima = fecha
    return estado, filas


async def actualizar_snapshot_lecturas(
    parsed_actual: Optional[dict],
    fecha_actual: Optional[datetime],
) -> dict:
    """
    Guarda lecturas nuevas de CO₂/O₂ y mantiene el último valor válido por zona.
    La primera vez recorre las tramas recientes para no mostrar 0 ni 25.5.
    """
    col = await _objetivos_panel_col()
    snap = await col.find_one({"_id": _LECTURAS_SNAPSHOT_ID})
    sembrado = bool(snap and snap.get("sembrado") and snap.get("semilla") == _SEMILLA_LECTURAS)
    canales = _copiar_canales((snap or {}).get("canales"))
    ultima = _fecha_naive(snap.get("fecha_trama") if snap else None)
    fecha_actual = _fecha_naive(fecha_actual)

    puntos: list[dict] = []
    if not sembrado:
        hasta = fecha_actual or _fecha_naive(server_now())
        desde = hasta - timedelta(days=14)
        docs = await _tramas_d02_entre(desde, hasta, limite=800)
        puntos = [p for d in docs if (p := _punto_desde_doc(d))]
        canales = canales_iniciales()
        ultima = None
    else:
        hasta = fecha_actual or _fecha_naive(server_now())
        desde = ultima if ultima is not None else hasta - timedelta(days=1)
        if ultima is None or hasta > ultima:
            docs = await _tramas_d02_entre(desde, hasta, limite=300)
            puntos = [
                p
                for d in docs
                if (p := _punto_desde_doc(d)) and (ultima is None or p["fecha"] > ultima)
            ]

    if fecha_actual and parsed_actual:
        gases = punto_gases(parsed_actual)
        if not any(p["fecha"] == fecha_actual for p in puntos):
            if ultima is None or fecha_actual > ultima:
                puntos.append({"fecha": fecha_actual, "parsed": parsed_actual, **gases})

    puntos.sort(key=lambda p: p["fecha"])
    if puntos:
        canales, _filas = _serie_visible(puntos, canales)
        ultima = puntos[-1]["fecha"]
        await _guardar_puntos(puntos)

    await col.update_one(
        {"_id": _LECTURAS_SNAPSHOT_ID},
        {
            "$set": {
                "tipo": "lecturas_ultimo",
                "imei": CERRO_PRIETO_IMEI,
                "sembrado": True,
                "semilla": _SEMILLA_LECTURAS,
                "fecha_trama": ultima,
                "actualizado": server_now(),
                "canales": canales,
            }
        },
        upsert=True,
    )
    return canales


async def listar_lecturas_gas(desde: str, hasta: str) -> dict[str, Any]:
    """Histórico de CO₂/O₂ por fechas. 0 y 25.5 se devuelven como reinicio."""
    inicio, fin = _rango_dias(desde, hasta)
    docs = await _tramas_d02_entre(inicio, fin, limite=LECTURAS_LIMITE + 1)
    truncado = len(docs) > LECTURAS_LIMITE
    if truncado:
        docs = docs[-LECTURAS_LIMITE:]

    puntos = [p for d in docs if (p := _punto_desde_doc(d))]
    previos: list[dict] = []
    if puntos:
        lookback_hasta = puntos[0]["fecha"] - timedelta(microseconds=1)
        lookback_desde = lookback_hasta - timedelta(days=2)
        prev_docs = await _tramas_d02_entre(lookback_desde, lookback_hasta, limite=400)
        previos = [p for d in prev_docs if (p := _punto_desde_doc(d))]

    canales = canales_iniciales()
    if previos:
        canales, _ = _serie_visible(previos, canales)
    _estado, filas = _serie_visible(puntos, canales)
    await _guardar_puntos(previos + puntos)

    return {
        "ok": True,
        "desde": desde,
        "hasta": hasta,
        "total": len(filas),
        "limite": LECTURAS_LIMITE,
        "truncado": truncado,
        "lecturas": filas,
    }


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
    objetivos = await obtener_objetivos_guardados()
    historial_objetivos = await listar_historial_objetivos()
    d02_parsed = parse_d02(
        d02,
        objetivos_co2=objetivos["co2"],
        objetivos_o2=objetivos["o2"],
    )
    fecha_dt = _fecha_de_trama(trama)
    try:
        canales = await actualizar_snapshot_lecturas(d02_parsed, fecha_dt)
    except Exception as exc:
        logger.warning("snapshot lecturas cerro prieto", error=str(exc))
        canales = canales_iniciales()
    if d02_parsed.get("por_zona"):
        _aplicar_visibles(d02_parsed, visibles_para_muestra(canales, punto_gases(d02_parsed)))

    return {
        "cliente": CERRO_PRIETO_CLIENTE,
        "imei": CERRO_PRIETO_IMEI,
        "tipo": CERRO_PRIETO_TIPO,
        "zona_horaria": timezone_label(),
        "ultima_actualizacion": fecha_trama,
        "ultima_actualizacion_display": fecha_display,
        "sin_datos": trama is None,
        "objetivos": objetivos,
        "objetivos_historial": historial_objetivos,
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


def _mapas_objetivos_validos(
    co2: Optional[dict],
    o2: Optional[dict],
) -> tuple[dict[int, float], dict[int, float]]:
    co2_map = _normalizar_objetivos_por_zona(co2, OBJETIVOS_CO2_DEFAULT)
    o2_map = _normalizar_objetivos_por_zona(o2, OBJETIVOS_O2_DEFAULT)
    for valor in (*co2_map.values(), *o2_map.values()):
        if valor != valor or valor < 0 or valor > 100:
            raise ValueError("Los objetivos deben estar entre 0 y 100")
    return co2_map, o2_map


async def guardar_objetivos_panel(
    co2: Optional[dict] = None,
    o2: Optional[dict] = None,
    user: str = "cerro_prieto_panel",
) -> dict[str, Any]:
    """Persiste setpoints del panel. No encola comandos al equipo."""
    co2_map, o2_map = _mapas_objetivos_validos(co2, o2)
    objetivos_guardados = await guardar_objetivos_con_historial(
        co2_map, o2_map, user=user, motivo="guardar"
    )
    historial = await listar_historial_objetivos()
    return {
        "ok": True,
        "mensaje": "Objetivos guardados. No se envió ningún comando al equipo.",
        "comandos_enviados": 0,
        "objetivos": objetivos_guardados,
        "objetivos_historial": historial,
    }


async def aplicar_objetivos_panel(
    co2: Optional[dict] = None,
    o2: Optional[dict] = None,
    user: str = "cerro_prieto_panel",
) -> dict[str, Any]:
    """Encola comandos PANTALLA:OBJ_CO2_Z* y PANTALLA:OBJ_O2_Z* por zona."""
    co2_map, o2_map = _mapas_objetivos_validos(co2, o2)
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

    objetivos_guardados = await guardar_objetivos_con_historial(
        co2_map, o2_map, user=user, motivo="aplicar"
    )
    historial = await listar_historial_objetivos()

    return {
        "ok": True,
        "mensaje": "Objetivos guardados y 6 comandos encolados al equipo",
        "objetivos": objetivos_guardados,
        "objetivos_historial": historial,
        "comandos_insertados": insertados,
    }
