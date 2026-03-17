"""
app/workers/batch_writer.py — Worker batch Redis → MongoDB.

Lee tramas de la cola Redis en lotes y las persiste en la colección
correcta de MongoDB (una colección por dispositivo, patrón bd_gene).

Se ejecuta como proceso independiente para no competir con los
workers de Gunicorn que reciben las tramas.

Ejecución:
    python -m app.workers.batch_writer
"""
import asyncio
import signal
from datetime import datetime, timezone

from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.core.metrics import MONGO_BATCH_INSERT_DURATION, MONGO_BATCH_SIZE, MONGO_INSERT_ERRORS
from app.database import mongodb
from app.services import redis_service

logger = get_logger(__name__)
_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logger.info("Shutdown señalado — esperando batch actual")
    _shutdown = True


async def _insert_batch(documents: list[dict]) -> int:
    """
    Inserta un lote de documentos agrupados por IMEI.
    Cada IMEI tiene su propia colección MongoDB (patrón bd_gene original).
    """
    from pymongo.errors import BulkWriteError
    from app.database.mongodb import bd_gene, collection

    # Agrupar por IMEI para un insertMany por colección
    by_imei: dict[str, list] = {}
    for doc in documents:
        imei = doc.get("i", "unknown")
        by_imei.setdefault(imei, []).append(doc)

    total_inserted = 0

    with MONGO_BATCH_INSERT_DURATION.time():
        for imei, imei_docs in by_imei.items():
            col = collection(bd_gene(imei))
            try:
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
                    imei=imei,
                    insertados=inserted,
                    errores=errors,
                )
            except Exception as e:
                logger.error("Error al insertar batch", imei=imei, error=str(e))
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
            batch_ts = datetime.now(timezone.utc)
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
