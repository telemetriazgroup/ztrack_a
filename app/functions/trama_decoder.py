"""
Decodificación de tramas TermoKing / Túnel para el panel web.

Las tramas almacenan canales d00–d08 y d1–d4 como hex, ASCII o CSV.
Este módulo ofrece interpretación estructurada sin reemplazar el pipeline
OFICIAL ({IMEI}_OFICIAL_{año}), que sigue siendo la fuente canónica si existe.
"""
from __future__ import annotations

import re
from typing import Any, Optional

CANAL_FIELDS = (
    "d00", "d01", "d02", "d03", "d04", "d05", "d06", "d07", "d08",
    "d1", "d2", "d3", "d4",
)

_HEX_ONLY = re.compile(r"^[0-9A-Fa-f]+$")
_CSV_NUMERIC = re.compile(r"^[\d\.,\-\s]+$")
_TK_PREFIX = re.compile(r"^F+1B02", re.IGNORECASE)
_INVALID_WORD = {0x7FFE, 0xFE7F, 0x7FFF, 0xFFFF}


def _clean_hex(value: str) -> str:
    return "".join(c for c in value.strip().upper() if c in "0123456789ABCDEF")


def _hex_to_bytes(value: str) -> Optional[bytes]:
    h = _clean_hex(value)
    if not h or len(h) % 2:
        return None
    try:
        return bytes.fromhex(h)
    except ValueError:
        return None


def _format_hex_dump(data: bytes, max_bytes: int = 256) -> list[str]:
    lines = []
    chunk = data[:max_bytes]
    for i in range(0, len(chunk), 16):
        part = chunk[i : i + 16]
        hex_part = " ".join(f"{b:02X}" for b in part)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in part)
        lines.append(f"{i:04X}  {hex_part:<48}  {ascii_part}")
    if len(data) > max_bytes:
        lines.append(f"... ({len(data) - max_bytes} bytes más)")
    return lines


def _extract_ascii_runs(data: bytes, min_len: int = 4) -> list[str]:
    runs: list[str] = []
    current: list[int] = []
    for b in data:
        if 32 <= b < 127:
            current.append(b)
        else:
            if len(current) >= min_len:
                runs.append(bytes(current).decode("ascii", errors="ignore"))
            current = []
    if len(current) >= min_len:
        runs.append(bytes(current).decode("ascii", errors="ignore"))
    return runs


def _classify_channel(value: Any) -> str:
    if value is None:
        return "vacio"
    s = str(value).strip()
    if not s:
        return "vacio"
    if _CSV_NUMERIC.match(s) and "," in s:
        return "csv"
    if _HEX_ONLY.match(s):
        if s.upper().startswith("1B02") or _TK_PREFIX.match(s):
            return "thermoking_1b02"
        return "hex"
    if s.isprintable() and not _HEX_ONLY.match(s):
        return "ascii"
    return "texto"


def _decode_csv(value: str) -> dict:
    parts = [p.strip() for p in value.split(",")]
    valores: list[Any] = []
    for p in parts:
        try:
            valores.append(float(p) if "." in p else int(p))
        except ValueError:
            valores.append(p)
    labels = ["canal_1", "canal_2", "canal_3", "canal_4", "canal_5"]
    named = {
        labels[i] if i < len(labels) else f"valor_{i + 1}": v
        for i, v in enumerate(valores)
    }
    return {
        "tipo": "csv",
        "descripcion": "Valores numéricos separados por coma (típico en d07)",
        "valores": valores,
        "campos": named,
    }


def _decode_ascii(value: str) -> dict:
    return {
        "tipo": "ascii",
        "descripcion": "Texto / identificador de unidad",
        "texto": value,
    }


def _interpret_word(word: int) -> dict:
    info: dict[str, Any] = {"hex": f"{word:04X}", "uint16": word}
    if word in _INVALID_WORD:
        info["interpretacion"] = "sin lectura / no disponible"
        return info
    signed = word if word < 32768 else word - 65536
    info["int16"] = signed
    if -2000 <= signed <= 2000:
        info["posible_temperatura_c"] = round(signed / 10.0, 1)
    return info


def _scan_tk_records(data: bytes, start: int = 4) -> list[dict]:
    """Busca patrones TAG + FE7F frecuentes en tramas TermoKing."""
    registros: list[dict] = []
    i = start
    while i < len(data) - 3:
        if data[i + 2 : i + 4] == b"\xFE\x7F":
            registros.append({
                "offset": i,
                "tag_hex": data[i : i + 2].hex().upper(),
                "estado": "sin_lectura (FE7F)",
            })
            i += 4
            continue
        i += 1
    return registros[:40]


def _decode_thermoking_1b02(value: str) -> dict:
    raw = value.strip().upper()
    prefix_ff = False
    if _TK_PREFIX.match(raw):
        prefix_ff = True
        idx = raw.find("1B02")
        raw = raw[idx:]

    data = _hex_to_bytes(raw)
    if not data or len(data) < 4:
        return {"tipo": "thermoking_1b02", "error": "Hex inválido o demasiado corto"}

    if data[0] != 0x1B or data[1] != 0x02:
        return {
            "tipo": "thermoking_1b02",
            "error": "Cabecera 1B02 no encontrada",
            "volcado_hex": _format_hex_dump(data),
        }

    length_field = int.from_bytes(data[2:4], "little") if len(data) >= 4 else None
    payload = data[4:]
    registros = _scan_tk_records(data)
    ascii_runs = _extract_ascii_runs(data)

    palabras: list[dict] = []
    for off in range(4, min(len(data) - 1, 120), 2):
        w = int.from_bytes(data[off : off + 2], "little")
        if w in _INVALID_WORD:
            continue
        entry = {"offset": off, **_interpret_word(w)}
        if entry.get("posible_temperatura_c") is not None:
            palabras.append(entry)

    return {
        "tipo": "thermoking_1b02",
        "descripcion": "Trama binaria TermoKing (cabecera 1B 02)",
        "prefijo_ff_ignorado": prefix_ff,
        "cabecera": {
            "stx": "1B",
            "version": "02",
            "campo_longitud_le": length_field,
        },
        "bytes_totales": len(data),
        "registros_sin_lectura": registros,
        "posibles_temperaturas": palabras[:20],
        "texto_embebido": ascii_runs,
        "volcado_hex": _format_hex_dump(data),
    }


def _decode_hex_generic(value: str) -> dict:
    data = _hex_to_bytes(value)
    if not data:
        return {"tipo": "hex", "error": "Hex inválido"}
    return {
        "tipo": "hex",
        "descripcion": "Datos hexadecimales (sin protocolo 1B02 reconocido)",
        "bytes_totales": len(data),
        "texto_embebido": _extract_ascii_runs(data),
        "volcado_hex": _format_hex_dump(data),
        "uint16_muestra": [
            {"offset": i, **_interpret_word(int.from_bytes(data[i : i + 2], "little"))}
            for i in range(0, min(len(data) - 1, 40), 2)
        ][:15],
    }


def decode_channel(name: str, value: Any) -> dict:
    """Decodifica un canal individual (d02, d07, etc.)."""
    tipo = _classify_channel(value)
    base = {
        "campo": name,
        "tipo": tipo,
        "valor_original": None if value is None else str(value)[:500],
    }
    if tipo == "vacio":
        base["descripcion"] = "Sin dato"
        return base
    s = str(value).strip()
    if tipo == "csv":
        base.update(_decode_csv(s))
    elif tipo == "ascii":
        base.update(_decode_ascii(s))
    elif tipo == "thermoking_1b02":
        base.update(_decode_thermoking_1b02(s))
    elif tipo == "hex":
        base.update(_decode_hex_generic(s))
    else:
        base["descripcion"] = "Texto mixto o no reconocido"
        base["texto"] = s
    return base


def decode_trama(trama: Optional[dict]) -> dict:
    """
    Decodifica todos los canales presentes en un documento de trama.
    """
    if not trama:
        return {"canales": [], "resumen": "Trama vacía"}

    canales = []
    for name in CANAL_FIELDS:
        if name not in trama or trama[name] in (None, ""):
            continue
        canales.append(decode_channel(name, trama[name]))

    otros = []
    skip = {"_id", *CANAL_FIELDS, "fecha", "received_at", "estado", "secured", "i", "ip", "c"}
    skip |= {k for k in trama if k.endswith("_display")}
    for k, v in trama.items():
        if k in skip or v in (None, ""):
            continue
        otros.append({"campo": k, "valor": str(v)[:300]})

    tipos = [c["tipo"] for c in canales]
    resumen_parts = []
    if "thermoking_1b02" in tipos:
        resumen_parts.append("trama(s) TermoKing 1B02")
    if "csv" in tipos:
        resumen_parts.append("valores CSV")
    if "ascii" in tipos:
        resumen_parts.append("identificador ASCII")
    if "hex" in tipos:
        resumen_parts.append("hex genérico")

    return {
        "imei": trama.get("i"),
        "resumen": ", ".join(resumen_parts) if resumen_parts else "sin canales de payload",
        "canales": canales,
        "otros_campos": otros,
        "nota": (
            "Interpretación heurística para visualización. "
            "Para datos oficiales procesados use la colección {IMEI}_OFICIAL_{año}."
        ),
    }
