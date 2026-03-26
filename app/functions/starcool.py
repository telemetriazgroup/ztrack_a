"""
app/functions/starcool.py

Funciones de negocio para el módulo Starcool.
Acoplado a la lógica del proyecto: Redis → batch_writer, guardar_datos compartido.
Colecciones: S_{imei}_MM_YYYY, S_dispositivos_MM_YYYY, S_control_MM_YYYY.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.core.datetime_utils import server_now
from app.database.mongodb import (
    bd_gene,
    collection,
    get_control_collection,
    get_dispositivos_collection,
)
from app.functions.guardar_datos import guardar_datos

# Ventanas respecto a ultimo_dato (última trama recibida)
_ONLINE_MAX = timedelta(hours=1)
_WAIT_MAX = timedelta(hours=24)

# Búsqueda por ventana temporal (comandos S_control_* y tramas S_{imei}_*)
_VENTANA_DEFAULT_HORAS = 12
_MAX_RANGO_DIAS = 732  # ~24 meses
_COMANDOS_LIMITE_POR_COLECCION = 3000
_COMANDOS_LIMITE_TOTAL = 5000
_TRAMAS_LIMITE_POR_COLECCION = 3000
_TRAMAS_LIMITE_TOTAL = 5000


def _resolve_mes_anio(mes: Optional[int], anio: Optional[int]) -> tuple[int, int]:
    ref = server_now()
    m = mes if mes is not None else ref.month
    y = anio if anio is not None else ref.year
    return m, y


def _dt_for_collection(mes: int, anio: int) -> datetime:
    """Datetime dentro del mes solicitado (nombre de colección S_dispositivos_MM_YYYY)."""
    return datetime(anio, mes, 15, tzinfo=timezone.utc)


def _normalize_fecha_servidor(v: Any) -> Optional[datetime]:
    """
    Alinea con fechas guardadas por server_now() (misma convención de tz en todo el proyecto).
    No usa astimezone: el histórico etiqueta hora local con +00:00.
    """
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _connection_bucket(ultimo: Optional[datetime], now_ref: datetime) -> str:
    """
    online: ultimo_dato dentro de la última hora.
    wait: entre 1 h y 24 h sin datos.
    offline: más de 24 h sin datos o sin fecha.
    """
    if ultimo is None:
        return "offline"
    delta = now_ref - ultimo
    if delta <= _ONLINE_MAX:
        return "online"
    if delta <= _WAIT_MAX:
        return "wait"
    return "offline"


def _iso_fecha(v: Optional[datetime]) -> Optional[str]:
    return v.isoformat() if v else None


def _iter_meses_inclusivo(
    anio_desde: int, mes_desde: int, anio_hasta: int, mes_hasta: int
):
    y, m = anio_desde, mes_desde
    while (y, m) <= (anio_hasta, mes_hasta):
        yield m, y
        m += 1
        if m > 12:
            m = 1
            y += 1


def _meses_en_intervalo_datetimes(inicio: datetime, fin: datetime) -> list[tuple[int, int]]:
    """Meses (m, y) que deben consultarse en S_control_MM_YYYY para cubrir [inicio, fin]."""
    y, m = inicio.year, inicio.month
    y2, m2 = fin.year, fin.month
    out: list[tuple[int, int]] = []
    while (y, m) <= (y2, m2):
        out.append((m, y))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def _parse_fecha_busqueda_comando(s: str) -> datetime:
    """
    ISO 8601 (como en ComandoSchema) o dd-mm-yyyy_hh-mm-ss (como /Starcool/imei/).
    """
    raw = str(s).strip()
    if not raw:
        raise ValueError("Fecha vacía")
    dt = _normalize_fecha_servidor(raw)
    if dt is not None:
        return dt
    try:
        naive = datetime.strptime(raw, "%d-%m-%Y_%H-%M-%S")
        return naive.replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise ValueError(
            f"Fecha no válida '{raw}': use ISO 8601 o dd-mm-yyyy_hh-mm-ss"
        ) from e


def _ultimo_ts(doc: dict) -> Optional[datetime]:
    return _normalize_fecha_servidor(doc.get("ultimo_dato") or doc.get("fecha"))


def _elegir_dispositivo_mas_reciente(actual: dict, candidato: dict) -> dict:
    """Misma IMEI en varias colecciones mensuales: conserva el de ultimo_dato más reciente."""
    ta = _ultimo_ts(actual)
    tb = _ultimo_ts(candidato)
    if tb is None:
        return actual
    if ta is None or tb > ta:
        return candidato
    return actual


def _clasificar_docs_conexion(raw: list[dict], now_ref: datetime) -> dict:
    """Parte común del reporte: listas online / wait / offline y totales."""
    online: list[dict] = []
    wait: list[dict] = []
    offline: list[dict] = []

    for doc in raw:
        ultimo = _ultimo_ts(doc)
        bucket = _connection_bucket(ultimo, now_ref)
        delta = (now_ref - ultimo) if ultimo else None
        enriched = {
            **doc,
            "estado_conexion": bucket,
            "minutos_desde_ultimo_dato": round(delta.total_seconds() / 60, 1) if delta is not None else None,
            "ultimo_dato_iso": _iso_fecha(ultimo),
        }
        if bucket == "online":
            online.append(enriched)
        elif bucket == "wait":
            wait.append(enriched)
        else:
            offline.append(enriched)

    return {
        "totales": {
            "online": len(online),
            "wait": len(wait),
            "offline": len(offline),
            "registros": len(raw),
        },
        "online": online,
        "wait": wait,
        "offline": offline,
    }


async def listar_dispositivos_starcool(
    mes: Optional[int] = None,
    anio: Optional[int] = None,
) -> dict:
    """
    Lista equipos en S_dispositivos_MM_YYYY (estado=1), ordenados por ultimo_dato descendente.
    """
    m, y = _resolve_mes_anio(mes, anio)
    col = get_dispositivos_collection("Starcool", _dt_for_collection(m, y))
    cursor = col.find({"estado": 1}, {"_id": 0}).sort("ultimo_dato", -1)
    items = await cursor.to_list(length=10_000)
    return {
        "coleccion": col.name,
        "mes": m,
        "anio": y,
        "total": len(items),
        "dispositivos": items,
    }


async def reporte_dispositivos_starcool(
    mes: Optional[int] = None,
    anio: Optional[int] = None,
) -> dict:
    """
    Clasifica equipos por ultimo_dato vs hora actual:
    online ≤1 h, wait (1 h, 24 h], offline >24 h o sin ultimo_dato.
    """
    m, y = _resolve_mes_anio(mes, anio)
    col = get_dispositivos_collection("Starcool", _dt_for_collection(m, y))
    now_ref = server_now()

    cursor = col.find({"estado": 1}, {"_id": 0})
    raw = await cursor.to_list(length=10_000)
    part = _clasificar_docs_conexion(raw, now_ref)

    return {
        "coleccion": col.name,
        "mes": m,
        "anio": y,
        "referencia_servidor": now_ref.isoformat(),
        "umbrales": {
            "online_hasta_horas": _ONLINE_MAX.total_seconds() / 3600,
            "wait_hasta_horas": _WAIT_MAX.total_seconds() / 3600,
            "offline": "más de 24 h sin ultimo_dato",
        },
        **part,
    }


async def reporte_dispositivos_starcool_global(
    mes_desde: int,
    anio_desde: int,
    mes_hasta: int,
    anio_hasta: int,
) -> dict:
    """
    Cruza todas las colecciones S_dispositivos_MM_YYYY del rango inclusivo.
    Por IMEI se toma el registro con ultimo_dato más reciente entre meses.
    """
    now_ref = server_now()
    colecciones_consultadas: list[str] = []
    colecciones_con_datos: list[str] = []
    por_imei: dict[str, dict] = {}

    for mes, anio in _iter_meses_inclusivo(anio_desde, mes_desde, anio_hasta, mes_hasta):
        col = get_dispositivos_collection("Starcool", _dt_for_collection(mes, anio))
        colecciones_consultadas.append(col.name)
        cursor = col.find({"estado": 1}, {"_id": 0})
        chunk = await cursor.to_list(length=10_000)
        if chunk:
            colecciones_con_datos.append(col.name)
        for doc in chunk:
            imei = str(doc.get("imei", "")).strip()
            if not imei:
                continue
            if imei not in por_imei:
                por_imei[imei] = doc
            else:
                por_imei[imei] = _elegir_dispositivo_mas_reciente(por_imei[imei], doc)

    raw = list(por_imei.values())
    raw.sort(key=lambda d: _ultimo_ts(d) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    part = _clasificar_docs_conexion(raw, now_ref)

    return {
        "modo": "global",
        "mes_desde": mes_desde,
        "anio_desde": anio_desde,
        "mes_hasta": mes_hasta,
        "anio_hasta": anio_hasta,
        "colecciones_consultadas": colecciones_consultadas,
        "colecciones_con_datos": colecciones_con_datos,
        "imeis_unicos": len(raw),
        "referencia_servidor": now_ref.isoformat(),
        "umbrales": {
            "online_hasta_horas": _ONLINE_MAX.total_seconds() / 3600,
            "wait_hasta_horas": _WAIT_MAX.total_seconds() / 3600,
            "offline": "más de 24 h sin ultimo_dato",
        },
        **part,
    }


async def Guardar_Datos(ztrack_data: dict, secured: bool = False) -> str:
    """Entry point del POST /Starcool/. Delega a guardar_datos() con tipo="Starcool"."""
    return await guardar_datos(ztrack_data, secured=secured, tipo_dispositivo="Starcool")


async def insertar_comando(datos: dict) -> dict:
    """Inserta comando en S_control_MM_YYYY."""
    control_col = get_control_collection("Starcool")
    datos["fecha_creacion"] = server_now()
    if not datos.get("fecha_ejecucion"):
        datos["fecha_ejecucion"] = None
    result = await control_col.insert_one(datos)
    nuevo = await control_col.find_one({"_id": result.inserted_id}, {"_id": 0})
    return nuevo or {}


async def buscar_comandos_starcool(
    imei: Optional[str] = None,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
) -> dict:
    """
    Consulta comandos en S_control_MM_YYYY recorriendo cada mes que intersecte el intervalo.

    Por defecto: últimas _VENTANA_DEFAULT_HORAS horas (fecha_creacion).
    Con fecha_inicio y fecha_fin: rango explícito (máximo _MAX_RANGO_DIAS días).
    """
    now = server_now()
    fi_raw = (fecha_inicio or "").strip() or None
    ff_raw = (fecha_fin or "").strip() or None

    if fi_raw is None and ff_raw is None:
        fin = now
        inicio = fin - timedelta(hours=_VENTANA_DEFAULT_HORAS)
        ventana_predefinida = True
    else:
        inicio = _parse_fecha_busqueda_comando(fi_raw)
        fin = _parse_fecha_busqueda_comando(ff_raw)
        ventana_predefinida = False
        if inicio > fin:
            inicio, fin = fin, inicio
        if (fin - inicio).days > _MAX_RANGO_DIAS:
            raise ValueError(
                f"El rango no puede superar {_MAX_RANGO_DIAS} días (~24 meses)"
            )

    imei_f = (imei or "").strip() or None
    meses = _meses_en_intervalo_datetimes(inicio, fin)
    colecciones: list[str] = []
    comandos: list[dict] = []

    for mes, anio in meses:
        col = get_control_collection("Starcool", _dt_for_collection(mes, anio))
        colecciones.append(col.name)
        q: dict[str, Any] = {
            "fecha_creacion": {"$gte": inicio, "$lte": fin},
        }
        if imei_f:
            q["imei"] = imei_f
        cur = col.find(q, {"_id": 0}).sort("fecha_creacion", -1).limit(_COMANDOS_LIMITE_POR_COLECCION)
        comandos.extend(await cur.to_list(length=_COMANDOS_LIMITE_POR_COLECCION))

    def _sort_key(d: dict) -> datetime:
        t = _normalize_fecha_servidor(d.get("fecha_creacion"))
        return t or datetime.min.replace(tzinfo=timezone.utc)

    comandos.sort(key=_sort_key, reverse=True)
    if len(comandos) > _COMANDOS_LIMITE_TOTAL:
        comandos = comandos[:_COMANDOS_LIMITE_TOTAL]

    return {
        "ventana_predefinida_12h": ventana_predefinida,
        "fecha_inicio": inicio.isoformat(),
        "fecha_fin": fin.isoformat(),
        "filtro_imei": imei_f,
        "colecciones_consultadas": colecciones,
        "total": len(comandos),
        "comandos": comandos,
    }


async def buscar_imei_starcool(
    imei: str,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
) -> dict:
    """
    Tramas en S_{imei}_MM_YYYY recorriendo cada mes que cubra el intervalo (bd_gene).

    Por defecto: últimas _VENTANA_DEFAULT_HORAS horas filtradas por campo `fecha`.
    Con fecha_inicio y fecha_fin: rango inclusivo (máximo _MAX_RANGO_DIAS días).
    """
    imei_clean = str(imei).strip()
    if not imei_clean:
        raise ValueError("IMEI requerido")

    fi_raw = (fecha_inicio or "").strip() or None
    ff_raw = (fecha_fin or "").strip() or None

    if fi_raw is None and ff_raw is None:
        fin = server_now()
        inicio = fin - timedelta(hours=_VENTANA_DEFAULT_HORAS)
        ventana_predefinida = True
    else:
        inicio = _parse_fecha_busqueda_comando(fi_raw)
        fin = _parse_fecha_busqueda_comando(ff_raw)
        ventana_predefinida = False
        if inicio > fin:
            inicio, fin = fin, inicio
        if (fin - inicio).days > _MAX_RANGO_DIAS:
            raise ValueError(
                f"El rango no puede superar {_MAX_RANGO_DIAS} días (~24 meses)"
            )

    meses = _meses_en_intervalo_datetimes(inicio, fin)
    tramas: list[dict] = []
    colecciones: list[str] = []

    for mes, anio in meses:
        col_name = bd_gene(imei_clean, "Starcool", _dt_for_collection(mes, anio))
        colecciones.append(col_name)
        col = collection(col_name)
        q: dict[str, Any] = {"fecha": {"$gte": inicio, "$lte": fin}}
        cur = col.find(q, {"_id": 0}).sort("fecha", -1).limit(_TRAMAS_LIMITE_POR_COLECCION)
        tramas.extend(await cur.to_list(length=_TRAMAS_LIMITE_POR_COLECCION))

    def _sort_key(d: dict) -> datetime:
        t = _normalize_fecha_servidor(d.get("fecha"))
        return t or datetime.min.replace(tzinfo=timezone.utc)

    tramas.sort(key=_sort_key, reverse=True)
    if len(tramas) > _TRAMAS_LIMITE_TOTAL:
        tramas = tramas[:_TRAMAS_LIMITE_TOTAL]

    return {
        "ventana_predefinida_12h": ventana_predefinida,
        "imei": imei_clean,
        "fecha_inicio": inicio.isoformat(),
        "fecha_fin": fin.isoformat(),
        "colecciones_consultadas": colecciones,
        "total": len(tramas),
        "datos": tramas,
    }


async def datos_totales(datos: dict) -> list:
    """Lista paginada de registros del dispositivo."""
    imei = datos.get("imei", "")
    col = collection(bd_gene(imei, "Starcool"))
    cursor = col.find({}, {"_id": 0}).sort("fecha", -1).limit(500)
    return await cursor.to_list(length=500)


async def buscar_live(datos: dict) -> Optional[dict]:
    """Último registro del dispositivo (vista en vivo)."""
    imei = datos.get("imei", "")
    col = collection(bd_gene(imei, "Starcool"))
    return await col.find_one({}, {"_id": 0}, sort=[("fecha", -1)])
