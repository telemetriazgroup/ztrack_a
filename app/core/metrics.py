"""
app/core/metrics.py — Métricas Prometheus del proyecto ZTRACK.

CÓMO LEER ESTAS MÉTRICAS EN GRAFANA:
──────────────────────────────────────
Prometheus raspa /metrics cada 15s. Con estos datos puedes crear:

  Panel 1 — "Tramas recibidas por módulo (req/min)"
    rate(telemetry_received_total[1m]) by (modulo)
    → Ver si TermoKing o Tunel tiene caída de tráfico

  Panel 2 — "% Dispositivos con seguridad activa"
    devices_secured_total / (devices_secured_total + devices_legacy_total) * 100
    → Progreso de actualización de firmware

  Panel 3 — "Cola Redis (buffer)"
    redis_queue_length{queue="main"}
    → Alerta si supera 1000: el batch writer no da abasto

  Panel 4 — "Latencia P99 de recepción"
    histogram_quantile(0.99, rate(telemetry_processing_duration_seconds_bucket[5m]))
    → Objetivo: < 500ms

  Panel 5 — "Comandos despachados"
    rate(control_commands_dispatched_total[5m])
    → Actividad del sistema de control

  Alerta recomendada: redis_queue_length{queue="dlq"} > 0
    → Documentos que fallaron al persistir en MongoDB
"""
from prometheus_client import Counter, Gauge, Histogram

# ── SEGURIDAD PROGRESIVA ─────────────────────────────────────────────────────

DEVICES_LEGACY = Counter(
    "devices_legacy_total",
    "Requests de dispositivos sin API Key (firmware no actualizado).",
)

DEVICES_SECURED = Counter(
    "devices_secured_total",
    "Requests de dispositivos con API Key válida (firmware actualizado).",
)

# ── TELEMETRÍA ───────────────────────────────────────────────────────────────

TELEMETRY_RECEIVED = Counter(
    "telemetry_received_total",
    "Total de tramas de telemetría recibidas.",
    ["modulo", "status"],   # modulo: termoking | tunel
)

TELEMETRY_PROCESSING_DURATION = Histogram(
    "telemetry_processing_duration_seconds",
    "Tiempo desde recepción hasta respuesta al dispositivo.",
    ["modulo"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)

TELEMETRY_PAYLOAD_SIZE = Histogram(
    "telemetry_payload_size_bytes",
    "Tamaño de los payloads recibidos en bytes.",
    buckets=[128, 256, 512, 1024, 2048, 4096, 8192, 16384],
)

# ── COMANDOS DE CONTROL ──────────────────────────────────────────────────────

CONTROL_COMMANDS_DISPATCHED = Counter(
    "control_commands_dispatched_total",
    "Comandos enviados a dispositivos vía respuesta HTTP POST.",
)

# ── DISPOSITIVOS ─────────────────────────────────────────────────────────────

DEVICE_AUTO_REGISTERED = Counter(
    "device_auto_registered_total",
    "Dispositivos nuevos auto-registrados en la colección 'dispositivos'.",
    ["tipo"],   # tipo: TermoKing | Tunel
)

# ── COLA REDIS ───────────────────────────────────────────────────────────────

REDIS_QUEUE_LENGTH = Gauge(
    "redis_queue_length",
    "Mensajes pendientes en la cola Redis.",
    ["queue"],  # main | dlq
)

REDIS_ENQUEUE_DURATION = Histogram(
    "redis_enqueue_duration_seconds",
    "Tiempo de escritura en Redis (objetivo: < 1ms).",
    buckets=[0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05],
)

REDIS_ERRORS = Counter(
    "redis_errors_total",
    "Errores al operar con Redis.",
    ["operation"],
)

# ── MONGODB ──────────────────────────────────────────────────────────────────

MONGO_BATCH_INSERT_DURATION = Histogram(
    "mongo_batch_insert_duration_seconds",
    "Tiempo del insertMany batch en MongoDB.",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

MONGO_BATCH_SIZE = Histogram(
    "mongo_batch_size_documents",
    "Documentos por batch insertado.",
    buckets=[1, 5, 10, 25, 50, 100, 200],
)

MONGO_INSERT_ERRORS = Counter(
    "mongo_insert_errors_total",
    "Errores al insertar documentos en MongoDB.",
)

# ── AUTENTICACIÓN ────────────────────────────────────────────────────────────

AUTH_SUCCESS = Counter(
    "auth_success_total",
    "Autenticaciones exitosas con API Key.",
    ["source"],  # cache | database
)

AUTH_FAILURE = Counter(
    "auth_failure_total",
    "Intentos fallidos de autenticación.",
    ["reason"],
)
