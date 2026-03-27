"""
Live (última trama) con búsqueda parcial de IMEI vía índice en Redis (SET por tipo).

Mínimo 5 caracteres para activar coincidencia por subcadena; si hay una sola
coincidencia se devuelve el documento plano (compatibilidad); si hay varias,
un objeto con detalle por IMEI.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from app.core.datetime_utils import server_now
from app.core.logging import get_logger
from app.database.mongodb import bd_gene, collection, get_dispositivos_collection
from app.services import redis_service

logger = get_logger(__name__)

_MESES_FALLBACK = 6
_MAX_CANDIDATOS = 40


def _fecha_doc(doc: Optional[dict]) -> datetime:
    if not doc:
        return datetime.min
    f = doc.get("fecha")
    return f if isinstance(f, datetime) else datetime.min


async def _ultimo_live_un_imei(imei: str, tipo: str) -> Optional[dict]:
    col = collection(bd_gene(imei, tipo))
    try:
        return await col.find_one({}, {"_id": 0}, sort=[("fecha", -1)])
    except Exception as e:
        logger.warning("live: error leyendo colección", imei=imei, tipo=tipo, error=str(e))
        return None


async def _imeis_fallback_mongo(tipo: str, fragmento: str, limit: int) -> list[str]:
    """Si Redis no tiene índice, busca IMEI por subcadena en *_dispositivos_* (últimos meses)."""
    frag = fragmento.strip()
    if len(frag) < redis_service.MIN_PARCIAL_LEN_IMEI:
        return []
    seen: set[str] = set()
    out: list[str] = []
    now = datetime.now()
    y, m = now.year, now.month
    for _ in range(_MESES_FALLBACK):
        try:
            dcol = get_dispositivos_collection(tipo, datetime(y, m, 1))
            cur = dcol.find(
                {"imei": {"$regex": re.escape(frag), "$options": "i"}},
                {"imei": 1, "_id": 0},
            ).limit(limit)
            docs = await cur.to_list(length=limit)
            for d in docs:
                im = (d.get("imei") or "").strip()
                if im and im not in seen:
                    seen.add(im)
                    out.append(im)
                    if len(out) >= limit:
                        return out
        except Exception as e:
            logger.warning("live fallback mongo", tipo=tipo, error=str(e))
        if m == 1:
            m = 12
            y -= 1
        else:
            m -= 1
    return out[:limit]


async def imeis_fallback_mongo_union(fragmento: str, limit: int) -> list[str]:
    """Unión de coincidencias en TK_* y TUNEL_* dispositivos (mismo IMEI puede estar en un solo tipo)."""
    a = await _imeis_fallback_mongo("TermoKing", fragmento, limit)
    b = await _imeis_fallback_mongo("Tunel", fragmento, limit)
    seen: set[str] = set()
    out: list[str] = []
    for im in a + b:
        if im not in seen:
            seen.add(im)
            out.append(im)
        if len(out) >= limit:
            break
    return out


async def buscar_live_telemetria_parcial(datos: dict, tipo: str) -> Any:
    """
    TK_* / TUNEL_* última trama.
    - imei con menos de 5 caracteres: búsqueda exacta (comportamiento anterior).
    - 5+ caracteres: subcadena en Redis (y fallback Mongo), lista de coincidencias.
    """
    q = (datos.get("imei") or "").strip()
    ref = server_now().isoformat()
    if not q:
        return None

    if len(q) < redis_service.MIN_PARCIAL_LEN_IMEI:
        return await _ultimo_live_un_imei(q, tipo)

    candidates = await redis_service.buscar_imeis_parciales(tipo, q, limit=_MAX_CANDIDATOS)
    if not candidates:
        candidates = await _imeis_fallback_mongo(tipo, q, _MAX_CANDIDATOS)

    if not candidates:
        doc = await _ultimo_live_un_imei(q, tipo)
        return doc

    detalle: list[dict] = []
    for im in candidates:
        ult = await _ultimo_live_un_imei(im, tipo)
        if ult is not None:
            detalle.append({"imei": im, "ultimo": ult})

    detalle.sort(key=lambda x: _fecha_doc(x.get("ultimo")), reverse=True)

    if len(detalle) == 1:
        return detalle[0]["ultimo"]

    if not detalle:
        return {
            "busqueda": q,
            "mensaje": "sin tramas en colección para las coincidencias",
            "coincidencias_imei": candidates,
            "detalle": [],
            "ultimo": None,
            "parcial": True,
            "referencia_servidor": ref,
        }

    return {
        "busqueda": q,
        "coincidencias_imei": [d["imei"] for d in detalle],
        "detalle": detalle,
        "ultimo": detalle[0]["ultimo"],
        "total_coincidencias": len(detalle),
        "parcial": True,
        "referencia_servidor": ref,
    }
