"""Tests de _mes_anio: colección mensual alineada a GMT-5 (server_now)."""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest


@pytest.fixture
def mes_anio():
    with patch("app.database.mongodb._database", object()):
        from app.database.mongodb import _mes_anio
        yield _mes_anio


def test_mes_anio_sin_argumento_usa_server_now(mes_anio):
    lima_jul31 = datetime(2026, 7, 31, 22, 0, 0, tzinfo=timezone.utc)
    with patch("app.core.datetime_utils.server_now", return_value=lima_jul31):
        assert mes_anio() == ("07", "2026")


def test_mes_anio_no_usa_datetime_now_utc(mes_anio):
    """A las 22:00 GMT-5 del 31/jul, UTC ya es 01/ago — datetime.now() daría mes 08."""
    lima_jul31 = datetime(2026, 7, 31, 22, 0, 0, tzinfo=timezone.utc)
    utc_ago1 = datetime(2026, 8, 1, 3, 0, 0)

    with patch("app.core.datetime_utils.server_now", return_value=lima_jul31):
        with patch("app.database.mongodb.datetime") as mock_dt:
            mock_dt.now.return_value = utc_ago1
            mock_dt.fromisoformat = datetime.fromisoformat
            assert mes_anio() == ("07", "2026")


def test_mes_anio_desde_received_at_string(mes_anio):
    assert mes_anio("2026-07-21T19:00:00+00:00") == ("07", "2026")


def test_mes_anio_desde_datetime_explicito(mes_anio):
    dt = datetime(2026, 7, 21, 19, 0, 0, tzinfo=timezone.utc)
    assert mes_anio(dt) == ("07", "2026")
