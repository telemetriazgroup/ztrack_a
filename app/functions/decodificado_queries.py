"""
Consultas sobre colecciones de datos decodificados / procesados.

- TermoKing: {IMEI}_OFICIAL_{AÑO}
- Tunel:     {IMEI}_TUNEL_OFICIAL_{AÑO}

- live: último documento por fecha entre el año actual y el anterior.
- imei: rango de fechas (por defecto últimas 12 h); cruza varios años consultando
  una colección por año civil e integra resultados.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.core.datetime_utils import server_now
from app.core.logging import get_logger
from app.database.mongodb import bd_gene_oficial, bd_gene_oficial_tunel, collection
from app.functions.device_queries import _rango_desde_datos
from app.functions.live_helpers import _imeis_fallback_mongo, imeis_fallback_mongo_union
from app.services import redis_service

logger = get_logger(__name__)

_MAX_REGISTROS = 5000
_MAX_CANDIDATOS_LIVE = 40
_ANIOS_LIVE = 3  # año actual y anteriores a revisar para el último dato


def _key_fecha(d: dict) -> datetime:
    f = d.get("fecha")
    return f if isinstance(f, datetime) else datetime.min


def _bd_oficial(imei: str, anio: int, tipo: str) -> str:
    """Nombre de colección OFICIAL según módulo (TermoKing vs Tunel)."""
    if tipo == "Tunel":
        return bd_gene_oficial_tunel(imei, anio)
    return bd_gene_oficial(imei, anio)


async def _ultimo_oficial_for_imei(imei: str, tipo: str = "TermoKing") -> dict:
    """Último registro en colección OFICIAL del módulo, revisando los últimos años."""
    imei = (imei or "").strip()
    if not imei:
        return {
            "ultimo": None,
            "coleccion": None,
            "anio": None,
            "mensaje": "imei requerido",
            "referencia_servidor": server_now().isoformat(),
        }
    y0 = server_now().replace(tzinfo=None).year
    best: Optional[dict] = None
    best_fecha: Optional[datetime] = None
    best_meta: tuple[Optional[str], Optional[int]] = (None, None)

    for k in range(_ANIOS_LIVE):
        y = y0 - k
        name = _bd_oficial(imei, y, tipo)
        col = collection(name)
        try:
            doc = await col.find_one({}, {"_id": 0}, sort=[("fecha", -1)])
        except Exception as e:
            logger.warning("decodificado live: error leyendo colección", coleccion=name, error=str(e))
            doc = None
        if not doc:
            continue
        f = doc.get("fecha")
        if isinstance(f, datetime):
            if best_fecha is None or f > best_fecha:
                best_fecha = f
                best = doc
                best_meta = (name, y)

    if best is None:
        return {
            "ultimo": None,
            "coleccion": _bd_oficial(imei, y0, tipo),
            "anio": y0,
            "mensaje": "sin datos en colecciones OFICIAL recientes",
            "referencia_servidor": server_now().isoformat(),
        }

    return {
        "ultimo": best,
        "coleccion": best_meta[0],
        "anio": best_meta[1],
        "mensaje": "ok",
        "referencia_servidor": server_now().isoformat(),
    }


async def buscar_live_oficial(imei: str, tipo: str = "TermoKing") -> dict:
    """Compatibilidad: un solo IMEI completo."""
    return await _ultimo_oficial_for_imei(imei, tipo)


async def _resolver_imeis_fragmento_oficial(q: str, tipo: str) -> list[str]:
    """
    Fragmento ≥5: TermoKing usa unión Redis/Mongo TK+Tunel; Tunel solo índice Tunel
    (colecciones {IMEI}_TUNEL_OFICIAL_*).
    """
    if len(q) < redis_service.MIN_PARCIAL_LEN_IMEI:
        return [q]
    if tipo == "Tunel":
        cands = await redis_service.buscar_imeis_parciales("Tunel", q, limit=_MAX_CANDIDATOS_LIVE)
        if not cands:
            cands = await _imeis_fallback_mongo("Tunel", q, _MAX_CANDIDATOS_LIVE)
    else:
        cands = await redis_service.buscar_imeis_parciales_union(q, limit=_MAX_CANDIDATOS_LIVE)
        if not cands:
            cands = await imeis_fallback_mongo_union(q, _MAX_CANDIDATOS_LIVE)
    if not cands:
        return [q]
    return cands


async def buscar_live_oficial_parcial(datos: dict, tipo: str) -> dict:
    """
    Misma lógica que telemetría live: ≥5 caracteres busca subcadena en Redis
    y dispositivos; TermoKing une TK+Tunel; Tunel solo dispositivos túnel.
    """
    q = (datos.get("imei") or "").strip()
    ref = server_now().isoformat()
    if not q:
        return await _ultimo_oficial_for_imei("", tipo)

    if len(q) < redis_service.MIN_PARCIAL_LEN_IMEI:
        return await _ultimo_oficial_for_imei(q, tipo)

    candidates = await _resolver_imeis_fragmento_oficial(q, tipo)
    if not candidates:
        return await _ultimo_oficial_for_imei(q, tipo)

    detalle: list[dict] = []
    for im in candidates:
        r = await _ultimo_oficial_for_imei(im, tipo)
        if r.get("ultimo") is not None:
            detalle.append(
                {
                    "imei": im,
                    "ultimo": r["ultimo"],
                    "coleccion": r.get("coleccion"),
                    "anio": r.get("anio"),
                    "mensaje": r.get("mensaje"),
                }
            )

    detalle.sort(key=lambda x: _key_fecha(x.get("ultimo") or {}), reverse=True)

    if len(detalle) == 1:
        d0 = detalle[0]
        return {
            "ultimo": d0["ultimo"],
            "coleccion": d0.get("coleccion"),
            "anio": d0.get("anio"),
            "mensaje": d0.get("mensaje") or "ok",
            "referencia_servidor": ref,
        }

    if not detalle:
        return {
            "busqueda": q,
            "mensaje": "sin datos oficiales para las coincidencias",
            "coincidencias_imei": candidates,
            "detalle": [],
            "ultimo": None,
            "parcial": True,
            "referencia_servidor": ref,
        }

    d0 = detalle[0]
    return {
        "busqueda": q,
        "coincidencias_imei": [x["imei"] for x in detalle],
        "detalle": detalle,
        "ultimo": d0["ultimo"],
        "coleccion": d0.get("coleccion"),
        "anio": d0.get("anio"),
        "total_coincidencias": len(detalle),
        "parcial": True,
        "referencia_servidor": ref,
    }


async def buscar_decodificado_imei_rango(datos: dict, tipo: str = "TermoKing") -> dict:
    """
    Por IMEI y rango de fechas (DD-MM-YYYY_HH-MM-SS). Sin fechas: últimas 12 h.
    Consulta la colección OFICIAL del módulo por cada año civil que cruce el rango.
    """
    imei = (datos.get("imei") or "").strip()
    if not imei:
        return {
            "mensaje": "imei requerido",
            "registros": [],
            "total": 0,
            "colecciones_consultadas": [],
            "rango": None,
            "referencia_servidor": server_now().isoformat(),
        }

    inicio, fin, err = _rango_desde_datos(datos)
    if err:
        return {
            "mensaje": err,
            "registros": [],
            "total": 0,
            "colecciones_consultadas": [],
            "rango": None,
            "referencia_servidor": server_now().isoformat(),
        }
    if not inicio or not fin:
        return {
            "mensaje": "Rango inválido",
            "registros": [],
            "total": 0,
            "colecciones_consultadas": [],
            "rango": None,
            "referencia_servidor": server_now().isoformat(),
        }

    imeis = await _resolver_imeis_fragmento_oficial(imei, tipo)
    years = list(range(inicio.year, fin.year + 1))
    out: list[dict] = []
    cols_hit: list[str] = []

    for im in imeis:
        for y in years:
            start_y = datetime(y, 1, 1, 0, 0, 0)
            end_y = datetime(y, 12, 31, 23, 59, 59)
            seg_a = max(inicio, start_y)
            seg_b = min(fin, end_y)
            if seg_a > seg_b:
                continue
            name = _bd_oficial(im, y, tipo)
            if name not in cols_hit:
                cols_hit.append(name)
            col = collection(name)
            try:
                cur = col.find(
                    {"fecha": {"$gte": seg_a, "$lte": seg_b}},
                    {"_id": 0},
                ).sort("fecha", -1).limit(_MAX_REGISTROS)
                chunk = await cur.to_list(length=_MAX_REGISTROS)
            except Exception as e:
                logger.warning("decodificado imei: error en colección", coleccion=name, error=str(e))
                chunk = []
            out.extend(chunk)
            if len(out) >= _MAX_REGISTROS:
                break
        if len(out) >= _MAX_REGISTROS:
            break

    out.sort(key=_key_fecha, reverse=True)
    out = out[:_MAX_REGISTROS]

    ref = server_now().isoformat()
    base: dict = {
        "mensaje": "ok",
        "registros": out,
        "total": len(out),
        "colecciones_consultadas": cols_hit,
        "rango": {
            "inicio": inicio.isoformat(),
            "fin": fin.isoformat(),
        },
        "referencia_servidor": ref,
    }
    if len(imeis) > 1:
        base["coincidencias_imei"] = imeis
        base["parcial"] = True
    return base
