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
_client_backup: Optional[AsyncMongoClient] = None
_database_backup = None

# Tipos cuyas escrituras se duplican en MongoDB de respaldo (misma estructura de colecciones)
MIRROR_TIPOS = frozenset({"Starcool", "Generador", "Datos"})


def es_tipo_respaldo(tipo: str) -> bool:
    return tipo in MIRROR_TIPOS


def backup_db_configured() -> bool:
    return _database_backup is not None


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
    global _client, _database, _client_backup, _database_backup
    settings = get_settings()

    _client_backup = None
    _database_backup = None

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

    backup_uri = (settings.mongo_backup_uri or "").strip()
    if backup_uri:
        backup_db_name = (settings.mongo_backup_database or "").strip() or settings.mongo_database
        _client_backup = AsyncMongoClient(
            backup_uri,
            maxPoolSize=settings.mongo_max_pool_size,
            minPoolSize=settings.mongo_min_pool_size,
            connectTimeoutMS=settings.mongo_connect_timeout_ms,
            serverSelectionTimeoutMS=settings.mongo_server_selection_timeout_ms,
            w=1,
            journal=True,
            retryWrites=True,
            appName="ztrack-api-backup",
        )
        _database_backup = _client_backup[backup_db_name]
        await _client_backup.admin.command("ping")
        logger.info("MongoDB respaldo conectado", db=backup_db_name)
        await _ensure_base_indexes_backup()


async def disconnect() -> None:
    """Cierra la conexión limpiamente en el shutdown."""
    global _client, _client_backup, _database_backup
    if _client_backup:
        _client_backup.close()
        _client_backup = None
        _database_backup = None
        logger.info("MongoDB respaldo desconectado")
    if _client:
        _client.close()
        logger.info("MongoDB desconectado")


async def health_check() -> bool:
    try:
        await _client.admin.command("ping")
        return True
    except Exception:
        return False


async def health_check_backup() -> Optional[bool]:
    """None si no hay BD de respaldo; True/False según ping."""
    if _client_backup is None:
        return None
    try:
        await _client_backup.admin.command("ping")
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

    TermoKing: TK_{imei}_{MM}_{YYYY}
    Túnel:     TUNEL_{imei}_{MM}_{YYYY}
    Datos:     D_{imei}_{MM}_{YYYY}
    Starcool:  S_{imei}_{MM}_{YYYY}
    Generador: G_{imei}_{MM}_{YYYY}
    """
    safe = str(imei).strip().translate(_MONGO_SAFE_REPLACE) or "unknown"
    mes, anio = _mes_anio(dt)
    if tipo == "TermoKing":
        return f"TK_{safe}_{mes}_{anio}"
    if tipo == "Tunel":
        return f"TUNEL_{safe}_{mes}_{anio}"
    if tipo == "Datos":
        return f"D_{safe}_{mes}_{anio}"
    if tipo == "Starcool":
        return f"S_{safe}_{mes}_{anio}"
    if tipo == "Generador":
        return f"G_{safe}_{mes}_{anio}"
    return f"trama_{safe}"


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
    """TK/TUNEL/D/S_dispositivos_MM_YYYY."""
    mes, anio = _mes_anio(dt)
    if tipo == "Tunel":
        name = f"TUNEL_dispositivos_{mes}_{anio}"
    elif tipo == "Datos":
        name = f"D_dispositivos_{mes}_{anio}"
    elif tipo == "Starcool":
        name = f"S_dispositivos_{mes}_{anio}"
    elif tipo == "Generador":
        name = f"G_dispositivos_{mes}_{anio}"
    else:
        name = f"TK_dispositivos_{mes}_{anio}"
    return _database.get_collection(name)


def get_control_collection(tipo: str = "TermoKing", dt: Optional[datetime] = None) -> Any:
    """TK/TUNEL/D/S/G_control_MM_YYYY."""
    mes, anio = _mes_anio(dt)
    if tipo == "Tunel":
        name = f"TUNEL_control_{mes}_{anio}"
    elif tipo == "Datos":
        name = f"D_control_{mes}_{anio}"
    elif tipo == "Starcool":
        name = f"S_control_{mes}_{anio}"
    elif tipo == "Generador":
        name = f"G_control_{mes}_{anio}"
    else:
        name = f"TK_control_{mes}_{anio}"
    return _database.get_collection(name)


def collection_backup(name: str):
    """Colección en la BD de respaldo (mismo nombre que en primaria)."""
    if _database_backup is None:
        raise RuntimeError("MongoDB respaldo no configurado")
    return _database_backup.get_collection(name)


def get_dispositivos_collection_backup(tipo: str = "TermoKing", dt: Optional[datetime] = None) -> Any:
    """Par de get_dispositivos_collection en la BD de respaldo."""
    if _database_backup is None:
        raise RuntimeError("MongoDB respaldo no configurado")
    mes, anio = _mes_anio(dt)
    if tipo == "Tunel":
        name = f"TUNEL_dispositivos_{mes}_{anio}"
    elif tipo == "Datos":
        name = f"D_dispositivos_{mes}_{anio}"
    elif tipo == "Starcool":
        name = f"S_dispositivos_{mes}_{anio}"
    elif tipo == "Generador":
        name = f"G_dispositivos_{mes}_{anio}"
    else:
        name = f"TK_dispositivos_{mes}_{anio}"
    return _database_backup.get_collection(name)


def get_control_collection_backup(tipo: str = "TermoKing", dt: Optional[datetime] = None) -> Any:
    """Par de get_control_collection en la BD de respaldo."""
    if _database_backup is None:
        raise RuntimeError("MongoDB respaldo no configurado")
    mes, anio = _mes_anio(dt)
    if tipo == "Tunel":
        name = f"TUNEL_control_{mes}_{anio}"
    elif tipo == "Datos":
        name = f"D_control_{mes}_{anio}"
    elif tipo == "Starcool":
        name = f"S_control_{mes}_{anio}"
    elif tipo == "Generador":
        name = f"G_control_{mes}_{anio}"
    else:
        name = f"TK_control_{mes}_{anio}"
    return _database_backup.get_collection(name)


async def crear_indices_coleccion_dispositivo_backup(nombre_col: str) -> None:
    """Índices en colección de tramas del dispositivo (respaldo)."""
    if _database_backup is None:
        return
    from pymongo import IndexModel
    col = _database_backup.get_collection(nombre_col)
    await col.create_indexes([
        IndexModel([("fecha", DESCENDING)], name="idx_fecha"),
        IndexModel([("estado", ASCENDING), ("fecha", DESCENDING)], name="idx_estado_fecha"),
        IndexModel([("fecha", ASCENDING)], name="idx_ttl", expireAfterSeconds=7_776_000),
    ])


async def mirror_insert_comando_control(tipo: str, datos: dict) -> None:
    """Duplica insert de comando en S/D/G_control_* del respaldo (no rompe si falla)."""
    if not es_tipo_respaldo(tipo) or not backup_db_configured():
        return
    try:
        col = get_control_collection_backup(tipo)
        doc = {k: v for k, v in datos.items() if k != "_id"}
        await col.insert_one(doc)
    except Exception as e:
        logger.warning("Mongo backup: insert comando control falló", tipo=tipo, error=str(e))


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
    await _ensure_indexes_dispositivos(get_dispositivos_collection("Datos"))
    await _ensure_indexes_dispositivos(get_dispositivos_collection("Starcool"))
    await _ensure_indexes_dispositivos(get_dispositivos_collection("Generador"))
    await _ensure_indexes_control(get_control_collection("TermoKing"))
    await _ensure_indexes_control(get_control_collection("Tunel"))
    await _ensure_indexes_control(get_control_collection("Datos"))
    await _ensure_indexes_control(get_control_collection("Starcool"))
    await _ensure_indexes_control(get_control_collection("Generador"))
    logger.info("Índices base verificados")


async def _ensure_base_indexes_backup() -> None:
    if _database_backup is None:
        return
    await _ensure_indexes_dispositivos(get_dispositivos_collection_backup("TermoKing"))
    await _ensure_indexes_dispositivos(get_dispositivos_collection_backup("Tunel"))
    await _ensure_indexes_dispositivos(get_dispositivos_collection_backup("Datos"))
    await _ensure_indexes_dispositivos(get_dispositivos_collection_backup("Starcool"))
    await _ensure_indexes_dispositivos(get_dispositivos_collection_backup("Generador"))
    await _ensure_indexes_control(get_control_collection_backup("TermoKing"))
    await _ensure_indexes_control(get_control_collection_backup("Tunel"))
    await _ensure_indexes_control(get_control_collection_backup("Datos"))
    await _ensure_indexes_control(get_control_collection_backup("Starcool"))
    await _ensure_indexes_control(get_control_collection_backup("Generador"))
    logger.info("Índices base verificados (MongoDB respaldo)")


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
