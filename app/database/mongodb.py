"""
app/database/mongodb.py

REEMPLAZA database.py del proyecto original.

CAMBIOS PRINCIPALES:
1. Motor (AsyncIOMotorClient) → PyMongo AsyncMongoClient (nativo desde 4.9)
2. Variables de entorno leídas por Pydantic Settings (validadas al arrancar)
3. La función collection() se mantiene igual para no romper el código existente
4. Se agregan las funciones auxiliares originales: guardar_evento_telemetria,
   contador_general, estaditica_general
5. Se agrega manejo de conexión con lifespan (connect/disconnect)
6. Se elimina el print("luis estuvo aqui") y prints de debug

COMPATIBILIDAD:
  El código que antes hacía:
    from server.database import collection, guardar_evento_telemetria
  Ahora hace:
    from app.database.mongodb import collection, guardar_evento_telemetria
  La API de las funciones es idéntica.
"""
from datetime import datetime, timedelta
from typing import Any, Optional

from bson.objectid import ObjectId
from pymongo import AsyncMongoClient, ASCENDING, DESCENDING

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Cliente global - se inicializa en connect() durante el lifespan de FastAPI
_client: Optional[AsyncMongoClient] = None
_database = None


async def connect() -> None:
    """
    Abre la conexión a MongoDB usando AsyncMongoClient de PyMongo.
    Llamado desde el lifespan de FastAPI al arrancar.

    ANTES (Motor):
        client = AsyncIOMotorClient(GENIAL)
        database_mongo = client[mongo_db_name]

    AHORA (PyMongo async nativo):
        _client = AsyncMongoClient(uri)
        _database = _client[db_name]
    """
    global _client, _database
    settings = get_settings()

    _client = AsyncMongoClient(
        settings.mongo_uri,
        maxPoolSize=settings.mongo_max_pool_size,
        minPoolSize=settings.mongo_min_pool_size,
        connectTimeoutMS=settings.mongo_connect_timeout_ms,
        serverSelectionTimeoutMS=settings.mongo_server_selection_timeout_ms,
        w=1,
        journal=True,
        retryWrites=True,
        appName="ztrack-api",
    )

    _database = _client[settings.mongo_database]

    # Verificar conectividad
    await _client.admin.command("ping")
    logger.info("MongoDB conectado", uri=settings.mongo_uri, db=settings.mongo_database)

    # Crear índices en colecciones base
    await _ensure_base_indexes()


async def disconnect() -> None:
    """Cierra la conexión limpiamente en el shutdown."""
    global _client
    if _client:
        _client.close()
        logger.info("MongoDB desconectado")


async def health_check() -> bool:
    try:
        await _client.admin.command("ping")
        return True
    except Exception:
        return False


# ── FUNCIÓN CENTRAL: collection() ────────────────────────────────────────────
# Idéntica al original. Toda la app la usa para obtener colecciones.
# El patrón bd_gene() del Guardar_Datos pasa el nombre del IMEI y esta
# función retorna la colección correspondiente.

def collection(name: str):
    """
    Retorna una colección MongoDB por nombre.
    Replica la función collection() del database.py original.

    Uso en Guardar_Datos (mismo patrón que el original):
        data_collection = collection(bd_gene(ztrack_data['i'], tipo))
    """
    return _database.get_collection(name)


def _mes_anio(dt: Optional[Any] = None) -> tuple[str, str]:
    """
    Retorna (mes, año) para el datetime dado o el actual.
    Acepta datetime o string ISO (viene de Redis/JSON tras serialización).
    """
    if dt is None:
        d = datetime.now()
    elif isinstance(dt, datetime):
        d = dt
    elif isinstance(dt, str):
        try:
            d = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            d = datetime.now()
    else:
        d = datetime.now()
    return d.strftime("%m"), d.strftime("%Y")


# Caracteres prohibidos en nombres de colección MongoDB: / \ " $ * < > : | ?
_MONGO_SAFE_REPLACE = str.maketrans({c: "_" for c in '/\\"$*<>:|?'})


def bd_gene(imei: str, tipo: Optional[str] = None, dt: Optional[datetime] = None) -> str:
    """
    Genera el nombre de colección para un IMEI dado.
    Usa el IMEI directamente (ej: UNIT222,ZGRU9999994); solo reemplaza caracteres
    prohibidos por MongoDB (/ \\ " $ * < > : | ?).

    TermoKing: TK_{imei}_{MM}_{YYYY}  (ej: TK_UNIT222,ZGRU9999994_03_2025)
    Túnel:     TUNEL_{imei}_{MM}_{YYYY}
    """
    safe = str(imei).strip().translate(_MONGO_SAFE_REPLACE) or "unknown"
    mes, anio = _mes_anio(dt)
    if tipo == "TermoKing":
        return f"TK_{safe}_{mes}_{anio}"
    if tipo == "Tunel":
        return f"TUNEL_{safe}_{mes}_{anio}"
    return f"trama_{safe}"


def bd_gene_oficial(imei: str, anio: int) -> str:
    """
    Colección de datos decodificados / procesados por IMEI y año civil (TermoKing).
    Formato: {IMEI_safe}_OFICIAL_{YYYY} (ej: ZGRU1234567_OFICIAL_2026).
    """
    safe = str(imei).strip().translate(_MONGO_SAFE_REPLACE) or "unknown"
    return f"{safe}_OFICIAL_{anio}"


def bd_gene_oficial_tunel(imei: str, anio: int) -> str:
    """
    Colección decodificados Túnel por IMEI y año civil.
    Formato: {IMEI_safe}_TUNEL_OFICIAL_{YYYY}.
    """
    safe = str(imei).strip().translate(_MONGO_SAFE_REPLACE) or "unknown"
    return f"{safe}_TUNEL_OFICIAL_{anio}"


# ── COLECCIONES BASE ─────────────────────────────────────────────────────────────

def get_log_general_collection():
    return _database.get_collection("log_general")

def get_ids_collection():
    return _database.get_collection("ids_proyectos")

def get_eventos_telemetria_collection():
    return _database.get_collection("eventos_telemetria")

def get_contador_general_collection():
    return _database.get_collection("contador_general")

def get_evento_telemetria_collection():
    return _database.get_collection("evento_telemetria")


def get_dispositivos_collection(tipo: str = "TermoKing", dt: Optional[datetime] = None) -> Any:
    """TK_dispositivos_MM_YYYY o TUNEL_dispositivos_MM_YYYY."""
    mes, anio = _mes_anio(dt)
    if tipo == "Tunel":
        name = f"TUNEL_dispositivos_{mes}_{anio}"
    else:
        name = f"TK_dispositivos_{mes}_{anio}"
    return _database.get_collection(name)


def get_control_collection(tipo: str = "TermoKing", dt: Optional[datetime] = None) -> Any:
    """TK_control_MM_YYYY o TUNEL_control_MM_YYYY."""
    mes, anio = _mes_anio(dt)
    if tipo == "Tunel":
        name = f"TUNEL_control_{mes}_{anio}"
    else:
        name = f"TK_control_{mes}_{anio}"
    return _database.get_collection(name)


# ── ÍNDICES BASE ─────────────────────────────────────────────────────────────

async def _ensure_indexes_dispositivos(col) -> None:
    """Crea índices en colección dispositivos (TK o TUNEL mensual)."""
    from pymongo import IndexModel
    await col.create_indexes([
        IndexModel([("imei", ASCENDING)], name="idx_imei_unique", unique=True),
        IndexModel([("estado", ASCENDING)], name="idx_estado"),
    ])


async def _ensure_indexes_control(col) -> None:
    """Crea índices en colección control (TK o TUNEL mensual)."""
    from pymongo import IndexModel
    await col.create_indexes([
        IndexModel([("imei", ASCENDING), ("estado", ASCENDING)], name="idx_imei_estado"),
    ])


async def _ensure_base_indexes() -> None:
    """Crea índices en colecciones base del mes actual al arrancar."""
    await _ensure_indexes_dispositivos(get_dispositivos_collection("TermoKing"))
    await _ensure_indexes_dispositivos(get_dispositivos_collection("Tunel"))
    await _ensure_indexes_control(get_control_collection("TermoKing"))
    await _ensure_indexes_control(get_control_collection("Tunel"))
    logger.info("Índices base verificados")


async def crear_indices_coleccion_dispositivo(nombre_col: str) -> None:
    """
    Crea índices en la colección de un dispositivo específico.
    Se llama la primera vez que aparece un dispositivo nuevo.
    """
    from pymongo import IndexModel
    col = _database.get_collection(nombre_col)
    await col.create_indexes([
        IndexModel([("fecha", DESCENDING)], name="idx_fecha"),
        IndexModel([("estado", ASCENDING), ("fecha", DESCENDING)], name="idx_estado_fecha"),
        # TTL: eliminar tramas de más de 90 días
        IndexModel([("fecha", ASCENDING)], name="idx_ttl", expireAfterSeconds=7_776_000),
    ])


# ── FUNCIONES AUXILIARES (portadas desde database.py original) ───────────────

TIPO_OPERACION = {
    1: "creado",
    2: "eliminado",
    3: "reestablecido",
    4: "editado"
}


async def guardar_evento_telemetria(
    responsable: str = "SIN RESPONSABLE",
    mensaje: str = "SIN MENSAJE",
    solicitud: int = 0,
) -> str:
    """
    Guarda un evento de telemetría con ID autoincrementado.
    Portada del database.py original sin cambios funcionales.
    """
    ids_collection = get_ids_collection()
    evento_collection = get_evento_telemetria_collection()

    ids_proyectos = await ids_collection.find_one({"id_evento_telemetria": {"$exists": True}})
    evento_data = {
        "responsable": responsable,
        "mensaje": mensaje,
        "solicitud_id": solicitud,
        "fecha_evento": datetime.now(),
        "estado_evento": 1,
        "id_evento_telemetria": ids_proyectos["id_evento_telemetria"] + 1 if ids_proyectos else 1,
    }

    await evento_collection.insert_one(evento_data)

    s_ids = {
        "id_evento_telemetria": evento_data["id_evento_telemetria"],
        "fecha": datetime.now(),
    }
    if ids_proyectos:
        await ids_collection.update_one({"_id": ids_proyectos["_id"]}, {"$set": s_ids})
    else:
        await ids_collection.insert_one(s_ids)

    return "ok"


async def contador_general(modulo: str = "SIN_MODULO", tipo: int = 1) -> Optional[str]:
    """
    Contador de operaciones por módulo y por día.
    Portada del database.py original sin cambios funcionales.
    """
    contador_collection = get_contador_general_collection()
    hoy = datetime.now().strftime("%d_%m_%Y")
    operacion = TIPO_OPERACION.get(tipo)
    if not operacion:
        return None

    campos_inc = {f"general.{operacion}": 1, f"{hoy}.{operacion}": 1}
    coincidencia = await contador_collection.find_one(
        {"modulo": str(modulo)}, {"_id": 0, "created_at": 1}
    )

    if coincidencia:
        await contador_collection.update_one(
            {"modulo": modulo},
            {"$inc": campos_inc, "$set": {"updated_at": datetime.now()}},
            upsert=True,
        )
    else:
        campos_set = {
            "modulo": modulo,
            "created_at": datetime.now(),
            "general": {operacion: 1},
            hoy: {operacion: 1},
        }
        await contador_collection.insert_one(campos_set)

    return "ok"


async def estaditica_general(modulo: str = "SIN_MODULO"):
    """Retorna estadísticas del módulo. Portada del original."""
    contador_collection = get_contador_general_collection()
    coincidencia = await contador_collection.find_one({"modulo": str(modulo)}, {"_id": 0})
    return coincidencia if coincidencia else []


async def validar_usuario(user_id: int) -> str:
    """Portada del original. Mantiene lógica de usuarios."""
    if user_id == 0:
        return "zgroup"
    return "dexterity"
