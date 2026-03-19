"""
app/core/datetime_utils.py

Compatibilidad con datos históricos: la base guardaba hora local (GMT-5)
con sufijo +00:00. Para no descuadrar el flujo, seguimos ese patrón.
"""
from datetime import datetime, timezone


def server_now() -> datetime:
    """
    Hora actual del servidor (local) etiquetada como UTC.
    Formato: 2026-03-19T14:15:50.563+00:00 (hora local con +00:00)
    Compatible con datos históricos que usaban GMT-5 sin conversión.
    """
    return datetime.now().replace(tzinfo=timezone.utc)
