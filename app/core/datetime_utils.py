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
