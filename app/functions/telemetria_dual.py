"""
IMEIs que se persisten en TermoKing y Tunel (doble colección TK_* y TUNEL_*).

POST /Tunel/ solo acepta IMEIs de esta lista; el resto se ignora sin error al dispositivo.
POST /TermoKing/ guarda en TermoKing y, si el IMEI está en la lista, también en Tunel.
"""
from __future__ import annotations

import copy
from typing import Any

from app.core.logging import get_logger
from app.functions.guardar_datos import guardar_datos

logger = get_logger(__name__)

# Misma lista que en tunel.py (dispositivos con telemetría duplicada)
IMEIS_DOBLE_PERSISTENCIA: frozenset[str] = frozenset({
    "868428040551750",
    "860389052988223",
    "868428047365683",
    "867856038562796",
    "866782049840560",
    "866262036100104",
})

_TIPOS = ("TermoKing", "Tunel")


def imei_en_lista_dual(imei: str) -> bool:
    return bool(imei) and imei in IMEIS_DOBLE_PERSISTENCIA


def _resumen_doc(doc: dict) -> dict[str, Any]:
    """Campos útiles para logs (sin volcar toda la trama)."""
    return {
        "i": doc.get("i"),
        "tipo_dispositivo": doc.get("tipo_dispositivo"),
        "rs_len": len(doc["rs"]) if isinstance(doc.get("rs"), str) else None,
        "d02_len": len(doc["d02"]) if isinstance(doc.get("d02"), str) else None,
        "keys": sorted(k for k in doc if k not in ("rs", "d02")),
    }


async def persistir_telemetria(
    doc: dict,
    *,
    secured: bool,
    tipo_entrada: str,
) -> str:
    """
    Guarda telemetría según el endpoint de entrada y duplica en el otro tipo si aplica.

    - TermoKing: siempre guarda en TermoKing; IMEIs de lista → también en Tunel.
    - Tunel: solo IMEIs de lista (guarda Tunel + TermoKing); otros → sin persistir.
    """
    imei = (doc.get("i") or "").strip()
    if not imei:
        logger.warning("Telemetría sin IMEI", tipo_entrada=tipo_entrada)
        return "sin comandos pendientes"

    if tipo_entrada == "Tunel" and not imei_en_lista_dual(imei):
        logger.info(
            "POST Tunel omitido (IMEI no en lista dual)",
            imei=imei,
            lista_dual=sorted(IMEIS_DOBLE_PERSISTENCIA),
        )
        return "sin comandos pendientes"

    logger.info(
        "Ingesta telemetría",
        imei=imei,
        tipo_entrada=tipo_entrada,
        resumen=_resumen_doc(doc),
    )

    comando = await guardar_datos(doc, secured=secured, tipo_dispositivo=tipo_entrada)

    if imei_en_lista_dual(imei):
        otro = "Tunel" if tipo_entrada == "TermoKing" else "TermoKing"
        doc_copia = copy.deepcopy(doc)
        comando_copia = await guardar_datos(
            doc_copia,
            secured=secured,
            tipo_dispositivo=otro,
        )
        logger.info(
            "Telemetría duplicada en segundo tipo",
            imei=imei,
            tipo_primario=tipo_entrada,
            tipo_copia=otro,
            comando_primario=comando,
            comando_copia=comando_copia,
            resumen=_resumen_doc(doc_copia),
        )

    return comando
