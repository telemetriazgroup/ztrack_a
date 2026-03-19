"""
app/workers/batch_writer.py — Worker batch Redis → MongoDB.

Lee tramas de la cola Redis en lotes y las persiste en la colección
correcta de MongoDB (una colección por dispositivo, patrón bd_gene).

Redis serializa con JSON: datetime → string. Al deserializar, received_at
viene como string; _mes_anio y bd_gene deben manejarlo para el nombre de colección.

Ejecución:
    python -m app.workers.batch_writer
"""
import asyncio
import signal
from datetime import datetime, timezone

from app.core.config import get_settings
from app.core.datetime_utils import server_now
from app.core.logging import get_logger, setup_logging
from app.core.metrics import MONGO_BATCH_INSERT_DURATION, MONGO_BATCH_SIZE, MONGO_INSERT_ERRORS
from app.database import mongodb
from app.services import redis_service

logger = get_logger(__name__)
_shutdown = False


def _to_datetime(v) -> datetime:
    """Convierte string ISO a datetime (viene de Redis/JSON)."""
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return server_now()


def _handle_signal(signum, frame):
    global _shutdown
    logger.info("Shutdown señalado — esperando batch actual")
    _shutdown = True


async def _insert_batch(documents: list[dict]) -> int:
    """
    Inserta un lote de documentos agrupados por colección.
    TermoKing: TK_{imei}_{MM}_{YYYY} | Túnel: TUNEL_{imei}_{MM}_{YYYY}
    Usa received_at del doc para determinar mes/año.
    """
    from pymongo.errors import BulkWriteError
    from app.database.mongodb import bd_gene, collection

    # Agrupar por nombre de colección (imei + tipo + mes/año)
    by_collection: dict[str, list] = {}
    for doc in documents:
        imei = doc.get("i", "unknown")
        tipo = doc.get("tipo_dispositivo", "TermoKing")
        dt = doc.get("received_at")
        col_name = bd_gene(imei, tipo, dt)
        by_collection.setdefault(col_name, []).append(doc)

    total_inserted = 0

    with MONGO_BATCH_INSERT_DURATION.time():
        for col_name, imei_docs in by_collection.items():
            col = collection(col_name)
            try:
                # Asegurar fecha, estado; normalizar datetime (Redis/JSON devuelve strings)
                now = server_now()
                for d in imei_docs:
                    d.setdefault("estado", 1)
                    raw = d.get("received_at") or d.get("fecha") or now
                    d["fecha"] = _to_datetime(raw) if not isinstance(raw, datetime) else raw
                    d.setdefault("received_at", d["fecha"])
                result = await col.insert_many(imei_docs, ordered=False)
                inserted = len(result.inserted_ids)
                total_inserted += inserted
            except BulkWriteError as e:
                inserted = e.details.get("nInserted", 0)
                total_inserted += inserted
                errors = len(e.details.get("writeErrors", []))
                MONGO_INSERT_ERRORS.inc(errors)
                logger.warning(
                    "Batch parcial con errores",
                    coleccion=col_name,
                    insertados=inserted,
                    errores=errors,
                )
            except Exception as e:
                logger.error("Error al insertar batch", coleccion=col_name, error=str(e))
                MONGO_INSERT_ERRORS.inc()

    MONGO_BATCH_SIZE.observe(total_inserted)
    return total_inserted


async def run_batch_writer() -> None:
    """Loop principal del worker."""
    global _shutdown

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    settings = get_settings()
    consecutive_errors = 0
    max_consecutive_errors = 10

    logger.info(
        "Batch writer iniciado",
        batch_size=settings.batch_size,
        timeout=settings.batch_timeout_seconds,
    )

    while not _shutdown:
        try:
            documents = await redis_service.dequeue_batch(
                batch_size=settings.batch_size,
                timeout=settings.batch_timeout_seconds,
            )

            if not documents:
                await asyncio.sleep(settings.batch_worker_sleep_on_empty)
                continue

            # Agregar timestamp de procesamiento batch
            batch_ts = server_now()
            for doc in documents:
                doc.setdefault("batch_processed_at", batch_ts)

            try:
                inserted = await _insert_batch(documents)
                consecutive_errors = 0
                logger.info(
                    "Batch procesado",
                    total=len(documents),
                    insertados=inserted,
                    fallidos=len(documents) - inserted,
                )

            except Exception as e:
                consecutive_errors += 1
                logger.error(
                    "Error crítico en batch",
                    error=str(e),
                    docs=len(documents),
                    errores_consecutivos=consecutive_errors,
                )
                # Guardar en DLQ para no perder las tramas
                await redis_service.move_to_dlq(documents)

                if consecutive_errors >= max_consecutive_errors:
                    backoff = min(60, 2 ** (consecutive_errors - max_consecutive_errors))
                    logger.error(f"Backoff exponencial: esperando {backoff}s")
                    await asyncio.sleep(backoff)

        except asyncio.CancelledError:
            logger.info("Batch writer cancelado")
            break
        except Exception as e:
            logger.error("Error inesperado en loop del batch writer", error=str(e))
            await asyncio.sleep(5)

    logger.info("Batch writer terminado limpiamente")


async def _main():
    setup_logging()
    await redis_service.connect()
    await mongodb.connect()
    try:
        await run_batch_writer()
    finally:
        await redis_service.disconnect()
        await mongodb.disconnect()


if __name__ == "__main__":
    asyncio.run(_main())
