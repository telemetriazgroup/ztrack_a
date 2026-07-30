"""
Datos agregados para el panel web de flota (último dato + estado por IMEI).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.core.datetime_utils import format_for_display, server_now, timezone_label
from app.database.mongodb import bd_gene, collection, get_control_collection
from app.functions.device_queries import (
    _months_between,
    dispositivos_reporte_clasificado,
)
from app.functions.dashboard_equipos import obtener_catalogo_por_imeis
from app.functions.live_helpers import _ultimo_live_un_imei


def _serialize_dt(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value) if value is not None else None


def _device_summary(doc: dict, status: str) -> dict:
    ultimo = doc.get("ultimo_dato")
    return {
        "imei": doc.get("imei") or "",
        "status": status,
        "ultimo_dato": _serialize_dt(ultimo),
        "ultimo_dato_display": format_for_display(ultimo),
        "last_ip": doc.get("last_ip"),
        "secured": bool(doc.get("secured", False)),
        "tipo": doc.get("tipo"),
        "fecha_registro": _serialize_dt(doc.get("fecha")),
        "fecha_registro_display": format_for_display(doc.get("fecha")),
    }


def _trama_resumen(trama: Optional[dict]) -> Optional[dict]:
    if not trama:
        return None
    keys = (
        "i", "ip", "fecha", "received_at", "gps", "val", "rs", "c",
        "d00", "d01", "d02", "d03", "d04", "d05", "d06", "d07", "d08",
        "d1", "d2", "d3", "d4",
    )
    out = {k: trama[k] for k in keys if k in trama and trama[k] is not None}
    if "fecha" in out:
        out["fecha_display"] = format_for_display(out["fecha"])
        out["fecha"] = _serialize_dt(out["fecha"])
    if "received_at" in out:
        out["received_at_display"] = format_for_display(out["received_at"])
        out["received_at"] = _serialize_dt(out["received_at"])
    return out or None


async def _enrich_with_trama(device: dict, tipo: str) -> dict:
    imei = device.get("imei") or ""
    if not imei:
        device["ultima_trama"] = None
        return device
    trama = await _ultimo_live_un_imei(imei, tipo)
    device["ultima_trama"] = _trama_resumen(trama)
    return device


async def obtener_flota_dashboard(
    tipo: str = "TermoKing",
    online_h: float = 1.0,
    wait_h: float = 24.0,
    incluir_trama: bool = True,
    limite_tramas: int = 200,
) -> dict:
    """
    Combina reporte online/wait/offline con última trama por dispositivo (campo i / imei).
    """
    now = server_now()
    report = await dispositivos_reporte_clasificado(
        tipo,
        {
            "mes": now.month,
            "anio": now.year,
            "online_hasta_horas": online_h,
            "wait_hasta_horas": wait_h,
        },
    )

    dispositivos: list[dict] = []
    for status, rows in (
        ("online", report.get("online") or []),
        ("wait", report.get("wait") or []),
        ("offline", report.get("offline") or []),
    ):
        for doc in rows:
            dispositivos.append(_device_summary(doc, status))

    dispositivos.sort(
        key=lambda d: d.get("ultimo_dato") or "",
        reverse=True,
    )

    if incluir_trama and dispositivos:
        to_enrich = dispositivos[: max(limite_tramas, 0)]
        enriched = await asyncio.gather(
            *[_enrich_with_trama(d, tipo) for d in to_enrich]
        )
        by_imei = {d["imei"]: d for d in enriched}
        dispositivos = [by_imei.get(d["imei"], d) for d in dispositivos]

    if dispositivos:
        catalogo = await obtener_catalogo_por_imeis([d["imei"] for d in dispositivos])
        for d in dispositivos:
            cat = catalogo.get(d["imei"])
            if cat:
                d["numero_telemetria"] = cat.get("numero_telemetria") or ""
                d["cliente"] = cat.get("cliente") or ""
                d["catalogo"] = cat

    totales = report.get("totales") or {}
    return {
        "tipo": tipo,
        "zona_horaria": timezone_label(),
        "referencia_servidor": report.get("referencia_servidor") or _serialize_dt(now),
        "referencia_servidor_display": format_for_display(now),
        "coleccion": report.get("coleccion"),
        "umbrales": report.get("umbrales"),
        "totales": {
            "online": totales.get("online", 0),
            "wait": totales.get("wait", 0),
            "offline": totales.get("offline", 0),
            "registros": totales.get("registros", len(dispositivos)),
        },
        "dispositivos": dispositivos,
    }


async def obtener_ultima_trama_dispositivo(imei: str, tipo: str = "TermoKing") -> dict:
    """Última trama cruda de TK_{imei}_* o TUNEL_{imei}_*."""
    imei = (imei or "").strip()
    if not imei:
        return {"imei": "", "ultima_trama": None, "coleccion": None}

    trama = await _ultimo_live_un_imei(imei, tipo)
    col_name = bd_gene(imei, tipo) if imei else None
    trama_out = trama
    if trama and isinstance(trama, dict):
        trama_out = dict(trama)
        if trama_out.get("fecha"):
            trama_out["fecha_display"] = format_for_display(trama_out["fecha"])
        if trama_out.get("received_at"):
            trama_out["received_at_display"] = format_for_display(trama_out["received_at"])

    return {
        "imei": imei,
        "tipo": tipo,
        "zona_horaria": timezone_label(),
        "coleccion": col_name,
        "ultima_trama": trama_out,
    }


def _serialize_comando(doc: dict) -> dict:
    return {
        "comando": doc.get("comando"),
        "status": doc.get("status"),
        "estado": doc.get("estado"),
        "dispositivo": doc.get("dispositivo"),
        "user": doc.get("user"),
        "evento": doc.get("evento"),
        "fecha_creacion": _serialize_dt(doc.get("fecha_creacion")),
        "fecha_creacion_display": format_for_display(doc.get("fecha_creacion")),
        "fecha_ejecucion": _serialize_dt(doc.get("fecha_ejecucion")),
        "fecha_ejecucion_display": format_for_display(doc.get("fecha_ejecucion")),
    }


async def obtener_comandos_ejecutados_dispositivo(
    imei: str,
    tipo: str = "TermoKing",
    page: int = 1,
    page_size: int = 10,
    dias: int = 90,
    max_total: int = 500,
) -> dict:
    """
    Comandos ya despachados al dispositivo (status=2), paginados de a page_size.
    """
    imei = (imei or "").strip()
    page = max(1, page)
    page_size = max(1, min(page_size, 50))

    empty = {
        "imei": imei,
        "tipo": tipo,
        "zona_horaria": timezone_label(),
        "total": 0,
        "page": page,
        "page_size": page_size,
        "total_pages": 0,
        "comandos": [],
    }
    if not imei:
        return {**empty, "imei": ""}

    now = server_now()
    now_naive = now.replace(tzinfo=None) if now.tzinfo else now
    inicio = now_naive - timedelta(days=max(dias, 1))

    encontrados: list[dict] = []
    for y, m in _months_between(inicio, now_naive):
        col = get_control_collection(tipo, datetime(y, m, 1))
        cursor = col.find(
            {
                "imei": imei,
                "status": 2,
                "fecha_ejecucion": {"$ne": None, "$gte": inicio, "$lte": now_naive},
            },
            {"_id": 0},
        ).sort("fecha_ejecucion", -1)
        chunk = await cursor.to_list(length=max_total)
        encontrados.extend(chunk)
        if len(encontrados) >= max_total:
            break

    def _sort_key(d: dict) -> datetime:
        f = d.get("fecha_ejecucion")
        return f if isinstance(f, datetime) else datetime.min

    encontrados.sort(key=_sort_key, reverse=True)
    encontrados = encontrados[:max_total]

    total = len(encontrados)
    total_pages = (total + page_size - 1) // page_size if total else 0
    if total_pages and page > total_pages:
        page = total_pages
    start = (page - 1) * page_size
    pagina = encontrados[start : start + page_size]

    return {
        "imei": imei,
        "tipo": tipo,
        "zona_horaria": timezone_label(),
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "comandos": [_serialize_comando(c) for c in pagina],
    }
