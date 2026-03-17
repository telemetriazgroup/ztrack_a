"""
tests/test_guardar_datos.py — Tests unitarios de guardar_datos().

Valida la lógica de negocio portada del Guardar_Datos original:
  - Auto-registro de dispositivos nuevos
  - Actualización de ultimo_dato en dispositivos existentes
  - Despacho de comandos pendientes
  - Decremento del contador de intentos del comando
  - Comportamiento cuando no hay comandos
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

# Documento de prueba (lo que llega al guardar_datos después de to_mongo_document)
DOCUMENT = {
    "i": "860389053784506",
    "ip": "10.81.213.33,17,0",
    "estado": 2,
    "d02": "1B0204000082A7",
    "received_at": datetime.now(timezone.utc),
    "secured": False,
}

DOCUMENT_SECURED = dict(DOCUMENT, secured=True)


@pytest.fixture(autouse=True)
def mock_redis_enqueue():
    with patch("app.services.redis_service.enqueue", new=AsyncMock(return_value=True)):
        yield


@pytest.fixture
def mock_dispositivos_col():
    """Mock de la colección 'dispositivos'."""
    col = AsyncMock()
    col.find_one = AsyncMock(return_value=None)  # default: dispositivo no existe
    col.insert_one = AsyncMock()
    col.update_one = AsyncMock()
    return col


@pytest.fixture
def mock_control_col():
    """Mock de la colección 'control'."""
    col = AsyncMock()
    col.find_one = AsyncMock(return_value=None)  # default: sin comandos
    col.update_one = AsyncMock()
    return col


class TestAutoRegistro:

    @pytest.mark.asyncio
    async def test_nuevo_dispositivo_se_registra(self, mock_dispositivos_col, mock_control_col):
        """Dispositivo nuevo debe insertarse en la colección 'dispositivos'."""
        with patch("app.functions.guardar_datos.get_dispositivos_collection", return_value=mock_dispositivos_col):
            with patch("app.functions.guardar_datos.get_control_collection", return_value=mock_control_col):
                with patch("app.functions.guardar_datos.crear_indices_coleccion_dispositivo", new=AsyncMock()):
                    from app.functions.guardar_datos import guardar_datos
                    await guardar_datos(DOCUMENT, secured=False, tipo_dispositivo="TermoKing")

        mock_dispositivos_col.insert_one.assert_called_once()
        inserted = mock_dispositivos_col.insert_one.call_args[0][0]
        assert inserted["imei"] == "860389053784506"
        assert inserted["estado"] == 1
        assert inserted["tipo"] == "TermoKing"
        assert inserted["secured"] is False

    @pytest.mark.asyncio
    async def test_nuevo_dispositivo_secured_true(self, mock_dispositivos_col, mock_control_col):
        """Dispositivo nuevo con API Key → secured=True en el registro."""
        with patch("app.functions.guardar_datos.get_dispositivos_collection", return_value=mock_dispositivos_col):
            with patch("app.functions.guardar_datos.get_control_collection", return_value=mock_control_col):
                with patch("app.functions.guardar_datos.crear_indices_coleccion_dispositivo", new=AsyncMock()):
                    from app.functions.guardar_datos import guardar_datos
                    await guardar_datos(DOCUMENT_SECURED, secured=True, tipo_dispositivo="TermoKing")

        inserted = mock_dispositivos_col.insert_one.call_args[0][0]
        assert inserted["secured"] is True

    @pytest.mark.asyncio
    async def test_dispositivo_existente_actualiza_ultimo_dato(self, mock_dispositivos_col, mock_control_col):
        """Dispositivo existente → solo update_one con ultimo_dato."""
        mock_dispositivos_col.find_one = AsyncMock(
            return_value={"imei": "860389053784506", "estado": 1, "secured": False}
        )
        with patch("app.functions.guardar_datos.get_dispositivos_collection", return_value=mock_dispositivos_col):
            with patch("app.functions.guardar_datos.get_control_collection", return_value=mock_control_col):
                from app.functions.guardar_datos import guardar_datos
                await guardar_datos(DOCUMENT, secured=False)

        # No debe insertar (ya existe)
        mock_dispositivos_col.insert_one.assert_not_called()
        # Debe actualizar ultimo_dato
        mock_dispositivos_col.update_one.assert_called_once()
        update_args = mock_dispositivos_col.update_one.call_args[0]
        assert update_args[0] == {"imei": "860389053784506", "estado": 1}
        assert "ultimo_dato" in update_args[1]["$set"]

    @pytest.mark.asyncio
    async def test_dispositivo_migra_a_secured(self, mock_dispositivos_col, mock_control_col):
        """Dispositivo que pasa de legacy a seguro → secured=True en el update."""
        mock_dispositivos_col.find_one = AsyncMock(
            return_value={"imei": "860389053784506", "estado": 1, "secured": False}
        )
        with patch("app.functions.guardar_datos.get_dispositivos_collection", return_value=mock_dispositivos_col):
            with patch("app.functions.guardar_datos.get_control_collection", return_value=mock_control_col):
                from app.functions.guardar_datos import guardar_datos
                await guardar_datos(DOCUMENT_SECURED, secured=True)

        update_data = mock_dispositivos_col.update_one.call_args[0][1]["$set"]
        assert update_data.get("secured") is True


class TestComandos:

    @pytest.mark.asyncio
    async def test_sin_comandos_retorna_string_default(self, mock_dispositivos_col, mock_control_col):
        """Sin comandos pendientes → 'sin comandos pendientes'."""
        mock_dispositivos_col.find_one = AsyncMock(return_value={"imei": "860389053784506", "estado": 1})
        with patch("app.functions.guardar_datos.get_dispositivos_collection", return_value=mock_dispositivos_col):
            with patch("app.functions.guardar_datos.get_control_collection", return_value=mock_control_col):
                from app.functions.guardar_datos import guardar_datos
                resultado = await guardar_datos(DOCUMENT)

        assert resultado == "sin comandos pendientes"

    @pytest.mark.asyncio
    async def test_comando_pendiente_se_retorna(self, mock_dispositivos_col, mock_control_col):
        """Con comando pendiente → retorna el string del comando."""
        mock_dispositivos_col.find_one = AsyncMock(
            return_value={"imei": "860389053784506", "estado": 1}
        )
        mock_control_col.find_one = AsyncMock(return_value={
            "imei": "860389053784506",
            "comando": "Trama_Readout(3)",
            "estado": 1,
            "status": 1,
        })
        with patch("app.functions.guardar_datos.get_dispositivos_collection", return_value=mock_dispositivos_col):
            with patch("app.functions.guardar_datos.get_control_collection", return_value=mock_control_col):
                from app.functions.guardar_datos import guardar_datos
                resultado = await guardar_datos(DOCUMENT)

        assert resultado == "Trama_Readout(3)"

    @pytest.mark.asyncio
    async def test_comando_decrementa_estado(self, mock_dispositivos_col, mock_control_col):
        """
        El comando con estado=1 debe quedar en estado=0 y status=2 (ejecutado).
        Replica: veces_control = control_encontrado['estado'] - 1
        """
        mock_dispositivos_col.find_one = AsyncMock(
            return_value={"imei": "860389053784506", "estado": 1}
        )
        mock_control_col.find_one = AsyncMock(return_value={
            "imei": "860389053784506",
            "comando": "Trama_Readout(3)",
            "estado": 1,
        })
        with patch("app.functions.guardar_datos.get_dispositivos_collection", return_value=mock_dispositivos_col):
            with patch("app.functions.guardar_datos.get_control_collection", return_value=mock_control_col):
                from app.functions.guardar_datos import guardar_datos
                await guardar_datos(DOCUMENT)

        mock_control_col.update_one.assert_called_once()
        update_data = mock_control_col.update_one.call_args[0][1]["$set"]
        assert update_data["estado"] == 0       # 1 - 1 = 0
        assert update_data["status"] == 2       # status=2: ejecutado
        assert "fecha_ejecucion" in update_data

    @pytest.mark.asyncio
    async def test_comando_con_multiples_intentos(self, mock_dispositivos_col, mock_control_col):
        """Comando con estado=3 → queda en estado=2 (aún tiene intentos)."""
        mock_dispositivos_col.find_one = AsyncMock(
            return_value={"imei": "860389053784506", "estado": 1}
        )
        mock_control_col.find_one = AsyncMock(return_value={
            "imei": "860389053784506",
            "comando": "Trama_Readout(3)",
            "estado": 3,
        })
        with patch("app.functions.guardar_datos.get_dispositivos_collection", return_value=mock_dispositivos_col):
            with patch("app.functions.guardar_datos.get_control_collection", return_value=mock_control_col):
                from app.functions.guardar_datos import guardar_datos
                resultado = await guardar_datos(DOCUMENT)

        update_data = mock_control_col.update_one.call_args[0][1]["$set"]
        assert update_data["estado"] == 2       # 3 - 1 = 2
        assert resultado == "Trama_Readout(3)"

    @pytest.mark.asyncio
    async def test_imei_vacio_retorna_sin_comandos(self):
        """Sin IMEI → retorna 'sin comandos pendientes' sin tocar MongoDB."""
        from app.functions.guardar_datos import guardar_datos
        doc = dict(DOCUMENT, i="")
        resultado = await guardar_datos(doc)
        assert resultado == "sin comandos pendientes"
