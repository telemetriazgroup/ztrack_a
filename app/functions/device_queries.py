"""
Consultas multi-mes y ventanas por defecto para TermoKing y Tunel.

Paridad con la lógica descrita para otros módulos: ventana 12 h si no hay fechas,
recorrido de colecciones mensuales (TK_/TUNEL_*), límites de seguridad en rango y totales.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta
from typing import Any, Optional

from app.core.datetime_utils import server_now
from app.core.logging import get_logger
from app.database.mongodb import bd_gene, collection, get_control_collection, get_dispositivos_collection

logger = get_logger(__name__)

_VENTANA_DEFAULT_HORAS = 12
_MAX_RANGO_DIAS = 732
_COMANDOS_LIMITE_POR_COLECCION = 3000
_COMANDOS_LIMITE_TOTAL = 5000
_TRAMAS_LIMITE_POR_COLECCION = 3000
_TRAMAS_LIMITE_TOTAL = 5000


def _now_naive() -> datetime:
    return server_now().replace(tzinfo=None)


def _parse_fecha(s: Optional[str]) -> Optional[datetime]:
    if not s or str(s).strip() in ("0", ""):
        return None
    try:
        return datetime.strptime(str(s).strip(), "%d-%m-%Y_%H-%M-%S")
    except ValueError:
        return None


def _months_between(start: datetime, end: datetime):
    """Meses de calendario que intersectan [start, end] (fechas naive)."""
    y1, m1 = start.year, start.month
    y2, m2 = end.year, end.month
    y, m = y1, m1
    while (y < y2) or (y == y2 and m <= m2):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def _month_bounds_naive(y: int, m: int) -> tuple[datetime, datetime]:
    last = monthrange(y, m)[1]
    start = datetime(y, m, 1, 0, 0, 0)
    end = datetime(y, m, last, 23, 59, 59)
    return start, end


def _rango_desde_datos(datos: dict) -> tuple[Optional[datetime], Optional[datetime], Optional[str]]:
    """
    Devuelve (inicio, fin, error_msg). Si no hay fechas válidas y se usó default, error_msg None.
    Usa ventana de _VENTANA_DEFAULT_HORAS si fecha_inicio/fecha_fin ausentes o "0".
    """
    fi_raw = datos.get("fecha_inicio", "0") or "0"
    ff_raw = datos.get("fecha_fin", "0") or "0"
    if str(fi_raw).strip() in ("0", "") or str(ff_raw).strip() in ("0", ""):
        fin = _now_naive()
        inicio = fin - timedelta(hours=_VENTANA_DEFAULT_HORAS)
        return inicio, fin, None
    inicio = _parse_fecha(str(fi_raw))
    fin = _parse_fecha(str(ff_raw))
    if not inicio or not fin:
        return None, None, "Rango de fechas inválido (use DD-MM-YYYY_HH-MM-SS)"
    if fin < inicio:
        inicio, fin = fin, inicio
    if (fin - inicio).days > _MAX_RANGO_DIAS:
        fin = inicio + timedelta(days=_MAX_RANGO_DIAS)
    return inicio, fin, None


def _rango_desde_mes_anio(datos: dict) -> tuple[Optional[datetime], Optional[datetime], Optional[str]]:
    mes_d = datos.get("mes_desde")
    anio_d = datos.get("anio_desde")
    mes_h = datos.get("mes_hasta")
    anio_h = datos.get("anio_hasta")
    if mes_d is None or anio_d is None or mes_h is None or anio_h is None:
        return None, None, None
    try:
        y1, m1 = int(anio_d), int(mes_d)
        y2, m2 = int(anio_h), int(mes_h)
        inicio = datetime(y1, m1, 1, 0, 0, 0)
        last = monthrange(y2, m2)[1]
        fin = datetime(y2, m2, last, 23, 59, 59)
        return inicio, fin, None
    except (TypeError, ValueError):
        return None, None, "Parámetros mes_desde/anio_desde/mes_hasta/anio_hasta inválidos"


async def buscar_imei_multimes(tipo: str, datos: dict) -> list:
    imei = datos.get("imei", "")
    if not imei:
        return []
    inicio_m, fin_m, err_m = _rango_desde_mes_anio(datos)
    if inicio_m is not None and fin_m is not None:
        if err_m:
            return []
        inicio, fin = inicio_m, fin_m
    else:
        inicio, fin, err = _rango_desde_datos(datos)
        if err:
            return []
        if not inicio or not fin:
            return []
    out: list = []
    for y, m in _months_between(inicio, fin):
        ms, me = _month_bounds_naive(y, m)
        seg_a = max(inicio, ms)
        seg_b = min(fin, me)
        if seg_a > seg_b:
            continue
        col = collection(bd_gene(imei, tipo, datetime(y, m, 15)))
        q = {"fecha": {"$gte": seg_a, "$lte": seg_b}}
        cursor = col.find(q, {"_id": 0}).sort("fecha", -1).limit(_TRAMAS_LIMITE_POR_COLECCION)
        chunk = await cursor.to_list(length=_TRAMAS_LIMITE_POR_COLECCION)
        out.extend(chunk)
        if len(out) >= _TRAMAS_LIMITE_TOTAL:
            break

    def _key(d: dict) -> datetime:
        f = d.get("fecha")
        if isinstance(f, datetime):
            return f
        return datetime.min

    out.sort(key=_key, reverse=True)
    return out[:_TRAMAS_LIMITE_TOTAL]


async def buscar_comandos_control_multimes(tipo: str, datos: dict) -> dict:
    inicio_m, fin_m, err_m = _rango_desde_mes_anio(datos)
    if inicio_m is not None and fin_m is not None:
        if err_m:
            return {"mensaje": err_m, "total": 0, "comandos": []}
        inicio, fin = inicio_m, fin_m
    else:
        inicio, fin, err = _rango_desde_datos(datos)
        if err:
            return {"mensaje": err, "total": 0, "comandos": []}
        if not inicio or not fin:
            return {"mensaje": "Rango inválido", "total": 0, "comandos": []}
    imei = (datos.get("imei") or "").strip() or None
    comandos: list = []
    for y, m in _months_between(inicio, fin):
        ms, me = _month_bounds_naive(y, m)
        seg_a = max(inicio, ms)
        seg_b = min(fin, me)
        if seg_a > seg_b:
            continue
        col = get_control_collection(tipo, datetime(y, m, 1))
        q: dict[str, Any]
        if imei:
            q = {
                "imei": imei,
                "fecha_creacion": {"$gte": seg_a, "$lte": seg_b},
            }
        else:
            q = {"fecha_creacion": {"$gte": seg_a, "$lte": seg_b}}
        cursor = col.find(q, {"_id": 0}).sort("fecha_creacion", -1).limit(_COMANDOS_LIMITE_POR_COLECCION)
        chunk = await cursor.to_list(length=_COMANDOS_LIMITE_POR_COLECCION)
        comandos.extend(chunk)
        if len(comandos) >= _COMANDOS_LIMITE_TOTAL:
            break

    def _ck(d: dict) -> datetime:
        f = d.get("fecha_creacion")
        return f if isinstance(f, datetime) else datetime.min

    comandos.sort(key=_ck, reverse=True)
    comandos = comandos[:_COMANDOS_LIMITE_TOTAL]
    return {"mensaje": "Comandos recuperados", "total": len(comandos), "comandos": comandos}


def _dedupe_dispositivos_por_imei(rows: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for d in rows:
        im = d.get("imei") or ""
        u = d.get("ultimo_dato")
        if im not in best:
            best[im] = d
            continue
        old = best[im].get("ultimo_dato")
        if isinstance(u, datetime) and isinstance(old, datetime) and u > old:
            best[im] = d
        elif old is None and u is not None:
            best[im] = d
    return list(best.values())


async def dispositivos_periodo_multimes(tipo: str, datos: dict) -> dict:
    inicio_m, fin_m, err_m = _rango_desde_mes_anio(datos)
    if inicio_m and fin_m:
        if err_m:
            return {"mensaje": err_m, "total": 0, "dispositivos": []}
        inicio, fin = inicio_m, fin_m
    else:
        inicio, fin, err = _rango_desde_datos(datos)
        if err:
            return {"mensaje": err, "total": 0, "dispositivos": []}
        if not inicio or not fin:
            return {"mensaje": "Rango inválido", "total": 0, "dispositivos": []}
    raw: list = []
    for y, m in _months_between(inicio, fin):
        dcol = get_dispositivos_collection(tipo, datetime(y, m, 1))
        cursor = dcol.find({"tipo": tipo}, {"_id": 0}).sort("ultimo_dato", -1).limit(5000)
        raw.extend(await cursor.to_list(length=5000))
    merged = _dedupe_dispositivos_por_imei(raw)
    return {"mensaje": "Dispositivos en periodo", "total": len(merged), "dispositivos": merged}


async def reporte_global_dispositivos_multimes(tipo: str, datos: dict) -> dict:
    base = await dispositivos_periodo_multimes(tipo, datos)
    if "dispositivos" not in base:
        return base
    disps = base.get("dispositivos") or []
    estados: dict[Any, int] = {}
    secured_n = 0
    for d in disps:
        estados[d.get("estado", "?")] = estados.get(d.get("estado", "?"), 0) + 1
        if d.get("secured"):
            secured_n += 1
    return {
        "mensaje": "Reporte global",
        "total_dispositivos": len(disps),
        "con_secured": secured_n,
        "por_estado": estados,
        "referencia_servidor": server_now().isoformat(),
        "dispositivos_muestra": disps[:200],
    }
