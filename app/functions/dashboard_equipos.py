"""
Catálogo persistente de equipos del dashboard (TK y Tunel).

Las colecciones TK_dispositivos_MM_YYYY / TUNEL_dispositivos_MM_YYYY rotan por mes;
este módulo guarda IMEI, número de telemetría, cliente y el historial de cambios.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.core.datetime_utils import format_for_display, server_now
from app.database.mongodb import collection

DASHBOARD_PANEL_COL = "dashboard_panel"
_TIPOS_VALIDOS = ("TermoKing", "Tunel")


def _equipo_doc_id(imei: str) -> str:
    return f"equipo_{imei}"


def _serialize_dt(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value) if value is not None else None


def _snapshot_equipo(doc: Optional[dict]) -> dict[str, Any]:
    """Estado editable del equipo para historial."""
    if not doc:
        return {
            "imei": "",
            "numero_telemetria": "",
            "cliente": "",
            "notas": "",
        }
    return {
        "imei": doc.get("imei") or "",
        "numero_telemetria": (doc.get("numero_telemetria") or "").strip(),
        "cliente": (doc.get("cliente") or "").strip(),
        "notas": (doc.get("notas") or "").strip(),
    }


def _tipos_para_api(doc: Optional[dict]) -> dict[str, Any]:
    raw = (doc or {}).get("tipos") or {}
    out: dict[str, Any] = {}
    for tipo in _TIPOS_VALIDOS:
        t = raw.get(tipo) or {}
        primera = t.get("primera_conexion")
        ultima = t.get("ultima_conexion")
        out[tipo] = {
            "activo": bool(t.get("activo", False)),
            "primera_conexion": _serialize_dt(primera),
            "primera_conexion_display": format_for_display(primera, with_timezone=False),
            "ultima_conexion": _serialize_dt(ultima),
            "ultima_conexion_display": format_for_display(ultima, with_timezone=False),
        }
    return out


def equipo_para_api(doc: Optional[dict]) -> dict[str, Any]:
    if not doc:
        return {
            "imei": "",
            "numero_telemetria": "",
            "cliente": "",
            "notas": "",
            "tipos": _tipos_para_api(None),
        }
    return {
        "imei": doc.get("imei") or "",
        "numero_telemetria": doc.get("numero_telemetria") or "",
        "cliente": doc.get("cliente") or "",
        "notas": doc.get("notas") or "",
        "tipos": _tipos_para_api(doc),
        "creado": _serialize_dt(doc.get("creado")),
        "creado_display": format_for_display(doc.get("creado"), with_timezone=False),
        "actualizado": _serialize_dt(doc.get("actualizado")),
        "actualizado_display": format_for_display(doc.get("actualizado"), with_timezone=False),
        "user": doc.get("user"),
    }


def _serialize_historial(doc: dict) -> dict[str, Any]:
    return {
        "fecha": _serialize_dt(doc.get("fecha")),
        "fecha_display": format_for_display(doc.get("fecha"), with_timezone=False),
        "user": doc.get("user"),
        "motivo": doc.get("motivo"),
        "anterior": doc.get("anterior"),
        "nuevo": doc.get("nuevo"),
    }


async def _panel_col():
    return collection(DASHBOARD_PANEL_COL)


async def obtener_equipo_catalogo(imei: str) -> Optional[dict[str, Any]]:
    imei = (imei or "").strip()
    if not imei:
        return None
    col = await _panel_col()
    doc = await col.find_one({"_id": _equipo_doc_id(imei)}, {"_id": 0})
    return equipo_para_api(doc) if doc else None


async def obtener_catalogo_por_imeis(imeis: list[str]) -> dict[str, dict[str, Any]]:
    ids = [_equipo_doc_id(i.strip()) for i in imeis if (i or "").strip()]
    if not ids:
        return {}
    col = await _panel_col()
    cursor = col.find({"_id": {"$in": ids}}, {"_id": 0})
    docs = await cursor.to_list(length=len(ids))
    by_imei: dict[str, dict[str, Any]] = {}
    for doc in docs:
        imei = doc.get("imei") or ""
        if imei:
            by_imei[imei] = equipo_para_api(doc)
    return by_imei


async def listar_equipos_catalogo(
    limite: int = 500,
    buscar: Optional[str] = None,
) -> list[dict[str, Any]]:
    col = await _panel_col()
    filtro: dict[str, Any] = {"tipo": "equipo"}
    if buscar:
        q = buscar.strip()
        if q:
            filtro["$or"] = [
                {"imei": {"$regex": q, "$options": "i"}},
                {"numero_telemetria": {"$regex": q, "$options": "i"}},
                {"cliente": {"$regex": q, "$options": "i"}},
            ]
    cursor = col.find(filtro, {"_id": 0}).sort("actualizado", -1).limit(max(limite, 1))
    docs = await cursor.to_list(length=limite)
    return [equipo_para_api(d) for d in docs]


async def listar_historial_equipo(imei: str, limite: int = 20) -> list[dict[str, Any]]:
    imei = (imei or "").strip()
    if not imei:
        return []
    col = await _panel_col()
    cursor = col.find(
        {"tipo": "equipo_historial", "equipo_imei": imei},
        {"_id": 0},
    ).sort("fecha", -1).limit(limite)
    docs = await cursor.to_list(length=limite)
    return [_serialize_historial(d) for d in docs]


async def _insertar_historial_equipo(
    col,
    *,
    imei: str,
    user: str,
    motivo: str,
    anterior: dict[str, Any],
    nuevo: dict[str, Any],
    now: datetime,
) -> None:
    if anterior == nuevo:
        return
    await col.insert_one(
        {
            "tipo": "equipo_historial",
            "equipo_imei": imei,
            "fecha": now,
            "user": user,
            "motivo": motivo,
            "anterior": anterior,
            "nuevo": nuevo,
        }
    )


async def registrar_equipo_por_ingesta(
    imei: str,
    tipo: str,
    *,
    es_nuevo_en_mes: bool = False,
) -> None:
    """
    Alta/actualización automática al recibir telemetría (TK o Tunel).
    No bloquea la ingesta si falla.
    """
    imei = (imei or "").strip()
    if not imei or tipo not in _TIPOS_VALIDOS:
        return

    col = await _panel_col()
    now = server_now()
    doc_id = _equipo_doc_id(imei)
    anterior_doc = await col.find_one({"_id": doc_id}, {"_id": 0})
    tipo_path = f"tipos.{tipo}"
    era_nuevo_catalogo = anterior_doc is None
    tipo_ya_activo = bool((anterior_doc or {}).get("tipos", {}).get(tipo, {}).get("activo"))

    set_fields: dict[str, Any] = {
        "tipo": "equipo",
        "imei": imei,
        f"{tipo_path}.activo": True,
        f"{tipo_path}.ultima_conexion": now,
        "actualizado": now,
        "user": "auto_ingesta",
    }
    if era_nuevo_catalogo:
        set_fields.update({
            "numero_telemetria": "",
            "cliente": "",
            "notas": "",
            "creado": now,
            f"{tipo_path}.primera_conexion": now,
        })
    elif es_nuevo_en_mes and not tipo_ya_activo:
        set_fields[f"{tipo_path}.primera_conexion"] = now

    await col.update_one(
        {"_id": doc_id},
        {"$set": set_fields},
        upsert=True,
    )

    nuevo_doc = await col.find_one({"_id": doc_id}, {"_id": 0})
    if era_nuevo_catalogo:
        await _insertar_historial_equipo(
            col,
            imei=imei,
            user="auto_ingesta",
            motivo=f"inscripcion_{tipo.lower()}",
            anterior=_snapshot_equipo(None),
            nuevo=_snapshot_equipo(nuevo_doc),
            now=now,
        )
    elif es_nuevo_en_mes and not tipo_ya_activo:
        await _insertar_historial_equipo(
            col,
            imei=imei,
            user="auto_ingesta",
            motivo=f"primera_conexion_{tipo.lower()}",
            anterior={"tipos": _tipos_para_api(anterior_doc)},
            nuevo={"tipos": _tipos_para_api(nuevo_doc)},
            now=now,
        )


async def guardar_equipo_catalogo(
    imei: str,
    *,
    numero_telemetria: Optional[str] = None,
    cliente: Optional[str] = None,
    notas: Optional[str] = None,
    user: str = "dashboard_panel",
) -> dict[str, Any]:
    """Actualiza ficha del equipo y registra historial de cambios."""
    imei = (imei or "").strip()
    if not imei:
        return {"ok": False, "error": "IMEI vacío"}

    col = await _panel_col()
    doc_id = _equipo_doc_id(imei)
    now = server_now()
    anterior_doc = await col.find_one({"_id": doc_id}, {"_id": 0})

    nuevo_numero = (numero_telemetria if numero_telemetria is not None else (anterior_doc or {}).get("numero_telemetria") or "").strip()
    nuevo_cliente = (cliente if cliente is not None else (anterior_doc or {}).get("cliente") or "").strip()
    nuevo_notas = (notas if notas is not None else (anterior_doc or {}).get("notas") or "").strip()

    anterior_snap = _snapshot_equipo(anterior_doc)
    nuevo_snap = {
        "imei": imei,
        "numero_telemetria": nuevo_numero,
        "cliente": nuevo_cliente,
        "notas": nuevo_notas,
    }

    if not anterior_doc:
        await col.update_one(
            {"_id": doc_id},
            {
                "$set": {
                    "tipo": "equipo",
                    "imei": imei,
                    "numero_telemetria": nuevo_numero,
                    "cliente": nuevo_cliente,
                    "notas": nuevo_notas,
                    "creado": now,
                    "actualizado": now,
                    "user": user,
                    "tipos": {
                        "TermoKing": {"activo": False},
                        "Tunel": {"activo": False},
                    },
                }
            },
            upsert=True,
        )
        motivo = "alta_manual"
    else:
        await col.update_one(
            {"_id": doc_id},
            {
                "$set": {
                    "numero_telemetria": nuevo_numero,
                    "cliente": nuevo_cliente,
                    "notas": nuevo_notas,
                    "actualizado": now,
                    "user": user,
                }
            },
        )
        motivo = "edicion"

    await _insertar_historial_equipo(
        col,
        imei=imei,
        user=user,
        motivo=motivo,
        anterior=anterior_snap,
        nuevo=nuevo_snap,
        now=now,
    )

    guardado = await col.find_one({"_id": doc_id}, {"_id": 0})
    historial = await listar_historial_equipo(imei)
    return {
        "ok": True,
        "mensaje": "Equipo guardado",
        "equipo": equipo_para_api(guardado),
        "historial": historial,
    }
