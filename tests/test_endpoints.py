"""
tests/test_endpoints.py — Tests de integración de los endpoints FastAPI.

Usa mocks de MongoDB y Redis para correr sin servicios reales.
Cubre el comportamiento exacto esperado por los dispositivos en producción.
"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from fastapi import status
from httpx import ASGITransport, AsyncClient

# ── Payload real para todos los tests ────────────────────────────────────────
REAL_PAYLOAD = {
    "i": "860389053784506",
    "ip": "10.81.213.33,17,0",
    "c": "",
    "d00": None,
    "d01": "UNIT111",
    "d02": "1B0204000082A7000401FE7F04010C0114012301FF7F",
    "d03": "1B0204000082A70100009CFF3000030100FE02FE7F",
    "d04": None, "d05": None, "d06": None, "d07": None, "d08": None,
    "gps": None, "val": None, "rs": "&&&", "r": None,
    "estado": 2,
    "fecha": {"$date": "2025-11-04T14:34:25.870Z"},
}


@pytest.fixture(scope="session", autouse=True)
def set_test_env():
    import os
    os.environ.update({
        "APP_ENV": "testing",
        "ENABLE_AUTH": "false",
        "MONGO_DETAILS_OK": "mongodb://localhost:27017",
        "BD_DETAILS_OK": "ztrack_test",
        "REDIS_HOST": "localhost",
    })
    from app.core.config import get_settings
    get_settings.cache_clear()


@pytest.fixture
def mock_redis():
    with patch("app.services.redis_service.enqueue", new=AsyncMock(return_value=True)) as m:
        yield m


@pytest.fixture
def mock_guardar_datos():
    """Mock de la función central de negocio."""
    with patch(
        "app.functions.guardar_datos.guardar_datos",
        new=AsyncMock(return_value="sin comandos pendientes"),
    ) as m:
        yield m


@pytest.fixture
def mock_guardar_datos_con_comando():
    """Mock que simula un comando pendiente."""
    with patch(
        "app.functions.guardar_datos.guardar_datos",
        new=AsyncMock(return_value="Trama_Readout(3)"),
    ) as m:
        yield m


@pytest_asyncio.fixture
async def client(mock_redis, mock_guardar_datos):
    from app.main import create_app
    app = create_app()

    with patch("app.database.mongodb.connect", new=AsyncMock()):
        with patch("app.services.redis_service.connect", new=AsyncMock()):
            with patch("app.database.mongodb.disconnect", new=AsyncMock()):
                with patch("app.services.redis_service.disconnect", new=AsyncMock()):
                    with patch("app.database.mongodb.health_check", new=AsyncMock(return_value=True)):
                        with patch("app.services.redis_service.health_check", new=AsyncMock(return_value=True)):
                            with patch("app.services.redis_service.get_queue_lengths", new=AsyncMock(return_value={"main": 0, "dlq": 0})):
                                async with AsyncClient(
                                    transport=ASGITransport(app=app),
                                    base_url="http://test",
                                ) as c:
                                    yield c


# ══════════════════════════════════════════════════════════════════════════════
# TESTS: ROOT Y HEALTH
# ══════════════════════════════════════════════════════════════════════════════

class TestRoot:

    @pytest.mark.asyncio
    async def test_root_returns_welcome(self, client):
        response = await client.get("/")
        assert response.status_code == 200
        assert "message" in response.json()

    @pytest.mark.asyncio
    async def test_health_returns_200(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "components" in data
        assert "queues" in data

    @pytest.mark.asyncio
    async def test_metrics_endpoint_exists(self, client):
        response = await client.get("/metrics")
        assert response.status_code == 200
        # Prometheus devuelve texto plano
        assert "text/plain" in response.headers.get("content-type", "")


# ══════════════════════════════════════════════════════════════════════════════
# TESTS: TERMOKING POST (recepción de telemetría)
# ══════════════════════════════════════════════════════════════════════════════

class TestTermoKingPost:

    @pytest.mark.asyncio
    async def test_valid_payload_returns_200(self, client):
        response = await client.post("/TermoKing/", json=REAL_PAYLOAD)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_response_has_required_fields(self, client):
        response = await client.post("/TermoKing/", json=REAL_PAYLOAD)
        data = response.json()
        assert data["status"] == "ok"
        assert data["imei"] == REAL_PAYLOAD["i"]
        assert "secured" in data
        assert "comando" in data
        assert "received_at" in data

    @pytest.mark.asyncio
    async def test_legacy_device_secured_false(self, client):
        """Dispositivo sin API Key → secured=False (modo legacy)."""
        response = await client.post("/TermoKing/", json=REAL_PAYLOAD)
        # ENABLE_AUTH=false → todos los dispositivos son legacy en tests
        assert response.json()["secured"] is False

    @pytest.mark.asyncio
    async def test_response_includes_comando(self, client):
        """La respuesta incluye el campo 'comando' del sistema de control."""
        response = await client.post("/TermoKing/", json=REAL_PAYLOAD)
        assert response.json()["comando"] == "sin comandos pendientes"

    @pytest.mark.asyncio
    async def test_response_includes_active_command(self, mock_redis):
        """Si hay comando pendiente, debe venir en la respuesta."""
        from app.main import create_app
        app = create_app()

        with patch("app.functions.guardar_datos.guardar_datos", new=AsyncMock(return_value="Trama_Readout(3)")):
            with patch("app.database.mongodb.connect", new=AsyncMock()):
                with patch("app.services.redis_service.connect", new=AsyncMock()):
                    with patch("app.database.mongodb.disconnect", new=AsyncMock()):
                        with patch("app.services.redis_service.disconnect", new=AsyncMock()):
                            with patch("app.database.mongodb.health_check", new=AsyncMock(return_value=True)):
                                with patch("app.services.redis_service.health_check", new=AsyncMock(return_value=True)):
                                    with patch("app.services.redis_service.get_queue_lengths", new=AsyncMock(return_value={"main": 0, "dlq": 0})):
                                        async with AsyncClient(
                                            transport=ASGITransport(app=app),
                                            base_url="http://test",
                                        ) as c:
                                            response = await c.post("/TermoKing/", json=REAL_PAYLOAD)
                                            assert response.json()["comando"] == "Trama_Readout(3)"

    @pytest.mark.asyncio
    async def test_invalid_imei_returns_422(self, client):
        payload = dict(REAL_PAYLOAD, i="AB")  # Muy corto
        response = await client.post("/TermoKing/", json=payload)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_short_test_imei_accepted(self, client):
        """IDs cortos como 'test01' deben aceptarse."""
        payload = dict(REAL_PAYLOAD, i="test01")
        response = await client.post("/TermoKing/", json=payload)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_estado_out_of_range_rejected(self, client):
        payload = dict(REAL_PAYLOAD, estado=99)
        response = await client.post("/TermoKing/", json=payload)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_without_estado_uses_default(self, client):
        """Sin campo estado → se usa default=1."""
        payload = {k: v for k, v in REAL_PAYLOAD.items() if k != "estado"}
        response = await client.post("/TermoKing/", json=payload)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_with_d1_d4_termoking_protocol(self, client):
        """Canales d1-d4 del protocolo TermoKing original."""
        payload = dict(REAL_PAYLOAD, d1="1B0204000082A7", d2="FF00AA", d3=None, d4="DEADBEEF")
        response = await client.post("/TermoKing/", json=payload)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_fecha_mongodb_format_accepted(self, client):
        """Fecha en formato MongoDB aceptada."""
        payload = dict(REAL_PAYLOAD, fecha={"$date": "2025-11-04T14:34:25.870Z"})
        response = await client.post("/TermoKing/", json=payload)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_fecha_null_accepted(self, client):
        payload = dict(REAL_PAYLOAD, fecha=None)
        response = await client.post("/TermoKing/", json=payload)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_minimal_payload_accepted(self, client):
        """Payload mínimo con solo i, estado."""
        payload = {"i": "860389053784506", "estado": 1}
        response = await client.post("/TermoKing/", json=payload)
        assert response.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# TESTS: TUNEL POST
# ══════════════════════════════════════════════════════════════════════════════

class TestTunelPost:

    @pytest.mark.asyncio
    async def test_valid_payload_accepted(self, client):
        response = await client.post("/Tunel/", json=REAL_PAYLOAD)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_tunel_response_structure(self, client):
        response = await client.post("/Tunel/", json=REAL_PAYLOAD)
        data = response.json()
        assert data["status"] == "ok"
        assert "comando" in data
        assert "secured" in data


# ══════════════════════════════════════════════════════════════════════════════
# TESTS: CONSULTAS (rutas GET/POST de búsqueda)
# ══════════════════════════════════════════════════════════════════════════════

class TestConsultaRoutes:

    @pytest.mark.asyncio
    async def test_consultar_ultima_trama_route_exists(self, client):
        with patch("app.functions.termoking.consultar_trama_ultimo", new=AsyncMock(return_value=None)):
            response = await client.get("/TermoKing/ConsultarUltimaTrama/860389053784506")
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ultimo_estado_dispositivos_route(self, client):
        with patch(
            "app.functions.termoking.ultimo_estado_dispositivos_termoking",
            new=AsyncMock(return_value=[]),
        ):
            response = await client.get("/TermoKing/ultimo_estado_dispositivos/")
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_pre_termoking_route(self, client):
        response = await client.get("/TermoKing/PreTermoking/")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_live_route(self, client):
        with patch("app.functions.termoking.buscar_live", new=AsyncMock(return_value=None)):
            response = await client.post(
                "/TermoKing/live/",
                json={"imei": "860389053784506"},
            )
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_insertar_comando_route(self, client):
        with patch("app.functions.termoking.insertar_comando", new=AsyncMock(return_value={})):
            response = await client.post(
                "/TermoKing/comando/",
                json={"imei": "860389053784506", "comando": "Trama_Readout(3)"},
            )
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self, client):
        response = await client.get("/TermoKing/ruta_inexistente")
        assert response.status_code == 404
