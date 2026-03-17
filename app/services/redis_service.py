"""
app/services/redis_service.py

Buffer de escrituras entre FastAPI y MongoDB.
Las tramas recibidas se encolan aquí (< 1ms) y el batch writer
las persiste en MongoDB de forma asíncrona.
"""
import json
from typing import Optional

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_client: Optional[aioredis.Redis] = None
_pool = None

QUEUE_KEY = "ztrack:telemetry:queue"
DLQ_KEY = "ztrack:telemetry:dlq"
AUTH_CACHE_PREFIX = "ztrack:auth:"


async def connect() -> None:
    global _client, _pool
    settings = get_settings()
    _pool = aioredis.ConnectionPool.from_url(
        settings.redis_url,
        max_connections=settings.redis_max_connections,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=3,
        retry_on_timeout=True,
    )
    _client = aioredis.Redis(connection_pool=_pool)
    await _client.ping()
    logger.info("Redis conectado", host=settings.redis_host)


async def disconnect() -> None:
    global _pool
    if _pool:
        await _pool.aclose()
        logger.info("Redis desconectado")


async def health_check() -> bool:
    try:
        await _client.ping()
        return True
    except Exception:
        return False


async def enqueue(document: dict, queue_key: str = QUEUE_KEY) -> bool:
    """
    Agrega un documento a la cola de telemetría.
    Operación < 1ms. Retorna True si se encoló exitosamente.
    """
    try:
        await _client.lpush(queue_key, json.dumps(document, default=str))
        return True
    except RedisError as e:
        logger.error("Error al encolar en Redis", error=str(e))
        return False


async def dequeue_batch(batch_size: int = 50, timeout: float = 2.0) -> list[dict]:
    """Extrae hasta batch_size mensajes de la cola."""
    try:
        queue_len = await _client.llen(QUEUE_KEY)
        if queue_len == 0:
            item = await _client.brpop(QUEUE_KEY, timeout=int(timeout) or 1)
            if not item:
                return []
            return [json.loads(item[1])]

        actual = min(queue_len, batch_size)
        async with _client.pipeline(transaction=True) as pipe:
            pipe.lrange(QUEUE_KEY, -actual, -1)
            pipe.ltrim(QUEUE_KEY, 0, -(actual + 1))
            results = await pipe.execute()

        documents = []
        for msg in results[0]:
            try:
                documents.append(json.loads(msg))
            except json.JSONDecodeError:
                pass
        return documents
    except RedisError as e:
        logger.error("Error al leer cola Redis", error=str(e))
        return []


async def move_to_dlq(documents: list[dict]) -> None:
    """Mueve documentos fallidos a la Dead Letter Queue."""
    try:
        pipeline = _client.pipeline()
        for doc in documents:
            pipeline.lpush(DLQ_KEY, json.dumps(doc, default=str))
        await pipeline.execute()
        logger.warning("Documentos movidos a DLQ", count=len(documents))
    except RedisError as e:
        logger.error("Error al escribir en DLQ", error=str(e))


async def get_queue_lengths() -> dict:
    try:
        return {
            "main": await _client.llen(QUEUE_KEY),
            "dlq": await _client.llen(DLQ_KEY),
        }
    except RedisError:
        return {"main": -1, "dlq": -1}


# ── Cache de autenticación ───────────────────────────────────────────────────

async def get_auth_cache(imei: str) -> Optional[dict]:
    try:
        cached = await _client.get(f"{AUTH_CACHE_PREFIX}{imei}")
        return json.loads(cached) if cached else None
    except RedisError:
        return None


async def set_auth_cache(imei: str, data: dict, ttl: int = 300) -> None:
    try:
        await _client.setex(f"{AUTH_CACHE_PREFIX}{imei}", ttl, json.dumps(data))
    except RedisError:
        pass


async def invalidate_auth_cache(imei: str) -> None:
    try:
        await _client.delete(f"{AUTH_CACHE_PREFIX}{imei}")
    except RedisError:
        pass
