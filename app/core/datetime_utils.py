"""
app/core/datetime_utils.py

Compatibilidad con datos históricos: la base guardaba hora local (GMT-5)
con sufijo +00:00. Docker usa UTC, por eso datetime.now() daba hora incorrecta.
Usamos APP_TIMEZONE (America/Lima) para obtener la hora local real.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def server_now() -> datetime:
    """
    Hora en APP_TIMEZONE (ej: America/Lima = GMT-5) etiquetada como +00:00.
    Formato: 2026-03-19T14:44:16.181+00:00 (hora local con +00:00)
    Compatible con datos históricos.
    """
    from app.core.config import get_settings
    tz_name = get_settings().app_timezone
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Lima")
    now_local = datetime.now(tz)
    return now_local.replace(tzinfo=timezone.utc)


def timezone_label() -> str:
    """Etiqueta para UI (ej. America/Lima → GMT-5)."""
    from app.core.config import get_settings
    name = get_settings().app_timezone
    if name == "America/Lima":
        return "GMT-5 (America/Lima)"
    return name


def parse_stored_datetime(value) -> datetime | None:
    """Parsea ISO almacenado (hora local con sufijo +00:00)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def format_for_display(value, *, with_timezone: bool = True) -> str | None:
    """
    Formatea fecha para el panel: hora de reloj ya guardada en BD (no convertir UTC→Lima).
    Los documentos usan hora local APP_TIMEZONE con etiqueta +00:00.
    """
    dt = parse_stored_datetime(value)
    if not dt:
        return str(value) if value is not None else None
    base = dt.strftime("%d/%m/%Y %H:%M:%S")
    if with_timezone:
        return f"{base} {timezone_label()}"
    return base
