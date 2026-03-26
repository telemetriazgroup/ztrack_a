# ZTRACK API v2.0

Sistema de telemetría IoT para dispositivos **TermoKing** y **Túnel**.  
Adaptación del proyecto original con arquitectura de alta disponibilidad.

---

## Qué cambió vs. el proyecto original

| Aspecto | Original | Esta versión |
|---------|----------|--------------|
| Servidor | `uvicorn` directo (1 proceso) | `gunicorn` + múltiples workers |
| Driver MongoDB | `motor` (deprecated) | `pymongo` async nativo (v4.9+) |
| Escritura a MongoDB | Directa (bloquea el request) | Buffer Redis → batch worker |
| Seguridad | Sin autenticación | Seguridad Progresiva (legacy OK) |
| Monitoreo | Sin métricas | Prometheus + Grafana |
| Conexión DB | Al importar el módulo (frágil) | En el lifespan (robusta) |
| Rutas | Idénticas | Idénticas + `/health` + `/metrics` |

---

## Estructura del Proyecto

```
ztrack_api/
├── main.py                        # Entry point (reemplaza el original)
├── gunicorn.conf.py               # Config producción
├── requirements.txt
├── .env.example
├── app/
│   ├── main.py                    # FastAPI app con lifespan
│   ├── core/
│   │   ├── config.py              # Variables de entorno (Pydantic Settings)
│   │   ├── logging.py             # Logging estructurado JSON
│   │   └── metrics.py             # Métricas Prometheus
│   ├── database/
│   │   └── mongodb.py             # Reemplaza database.py (PyMongo async)
│   ├── models/
│   │   ├── termoking.py           # TermoKingSchema (corrige d08 duplicado)
│   │   ├── tunel.py               # TunelSchema
│   │   └── common.py              # ComandoSchema, BusquedaSchema, ResponseModel
│   ├── functions/
│   │   ├── guardar_datos.py       # Lógica central (porta Guardar_Datos)
│   │   ├── termoking.py           # Funciones de negocio TermoKing
│   │   └── tunel.py               # Funciones de negocio Túnel
│   ├── routes/
│   │   ├── termoking.py           # 16 rutas (idénticas al original)
│   │   └── tunel.py               # 9 rutas (idénticas al original)
│   ├── middleware/
│   │   └── auth.py                # Seguridad Progresiva
│   ├── services/
│   │   └── redis_service.py       # Cola de mensajes y cache de auth
│   └── workers/
│       └── batch_writer.py        # Redis → MongoDB (proceso separado)
└── tests/
    ├── test_models.py             # Validación de schemas Pydantic
    ├── test_endpoints.py          # Tests HTTP de endpoints
    └── test_guardar_datos.py      # Tests de lógica de negocio
```

---

## Flujo de Datos

```
Dispositivo IoT
    │  HTTP POST /TermoKing/  o  /Tunel/
    ▼
Nginx (reverse proxy, rate limiting)
    │
    ▼
Gunicorn + Uvicorn Workers (5 workers en servidor de 2 núcleos)
    │  1. Pydantic valida el payload
    │  2. progressive_auth clasifica el dispositivo (legacy/seguro)
    │  3. to_mongo_document() prepara el documento
    │  4. Redis.enqueue() → < 1ms (DESBLOQUEA el response)
    │  5. Sincroniza 'dispositivos' (update o auto-registro)
    │  6. Consulta colección 'control' por comandos pendientes
    │  7. Retorna: {status, imei, secured, comando, received_at}
    ▼
Redis (cola en memoria)
    │  BRPOP batch de 50 tramas
    ▼
Batch Writer (proceso separado)
    │  insert_many() por colección de dispositivo (bd_gene)
    ▼
MongoDB
    trama_{IMEI}            ← colecciones por dispositivo (patrón original)
    dispositivos            ← registro global
    control                 ← comandos de control
```

---

## Instalación

### Opción 1: Docker (recomendado)

**Stack con MongoDB externo + Redis interno** (puerto 6380):

```bash
cp .env.example .env
# Editar .env: MONGO_DETAILS_OK (URL de tu MongoDB), BD_DETAILS_OK
nano .env
docker compose up -d
curl http://localhost:9050/health
```

**Todo externo** (MongoDB y Redis fuera de Docker):

```bash
cp .env.docker.example .env
# Editar .env con MONGO_DETAILS_OK, REDIS_HOST, etc.
nano .env
docker compose -f docker-compose.external.yml up -d
```

### Opción 2: Instalación manual (systemd)

```bash
sudo bash scripts/install.sh
# Editar .env con los valores reales
nano .env
sudo systemctl start ztrack_api ztrack_batch
```

---

## Docker — Detalle

| Modo | Comando | MongoDB | Redis |
|------|---------|---------|-------|
| Actual | `docker compose up -d` | URL externa (.env) | Contenedor, puerto **6380** |
| Externos | `docker compose -f docker-compose.external.yml up -d` | Host / Atlas / externo | Host / externo |

**Redis en puerto 6380**: evita conflicto con otros Redis en 6379. Desde la red Docker, api/batch usan `redis:6379`; desde el host, `localhost:6380`.

---

## Modo desarrollo y documentación

| Variable | Valor | Efecto |
|----------|-------|--------|
| `APP_ENV=development` | Por defecto | `/docs`, `/redoc`, **reload** habilitados |
| `APP_ENV=production` | Producción | Docs deshabilitados, sin reload |

Con `APP_ENV=development`:
- Swagger en `http://localhost:9050/docs`
- **Reload automático** al cambiar código (tanto con `python main.py` como con `gunicorn`)

---

## Variables de Entorno

Compatible con el `.env` original:

```bash
# Nombres del original (siguen funcionando)
MONGO_DETAILS_OK=mongodb://localhost:27017
BD_DETAILS_OK=ztrack_db

# Nuevas variables
REDIS_HOST=localhost
ENABLE_AUTH=false          # false = acepta todos los dispositivos (legacy OK)
BATCH_SIZE=50
```

---

## Compatibilidad de Rutas

Todas las rutas del original siguen funcionando **sin cambios en los clientes**:

| Método | Ruta | Estado |
|--------|------|--------|
| POST | `/TermoKing/` | ✅ Idéntica + campo `comando` en respuesta |
| POST | `/TermoKing/imei/` | ✅ Idéntica |
| POST | `/TermoKing/live/` | ✅ Idéntica |
| POST | `/TermoKing/comando/` | ✅ Idéntica |
| POST | `/TermoKing/ListarTabla/` | ✅ Idéntica |
| GET  | `/TermoKing/ultimo_estado_dispositivos/` | ✅ Idéntica |
| POST | `/Tunel/` | ✅ Idéntica + campo `comando` en respuesta |
| GET  | `/health` | 🆕 Nueva |
| GET  | `/metrics` | 🆕 Nueva (Prometheus) |

**Nuevas (paridad consultas multi-mes / ventana 12 h):** `POST /TermoKing/comando/buscar/`, `POST /TermoKing/dispositivos/periodo/`, `POST /TermoKing/dispositivos/reporte_global/`, `POST /TermoKing/dispositivos/reporte/` (clasificación online/wait/offline por `ultimo_dato`) y las mismas bajo `/Tunel/`. `POST /TermoKing/imei/` y `POST /Tunel/imei/` recorren varios meses si el rango lo cruza; sin fechas usan las últimas 12 h.

---

## Ejecutar Tests

```bash
source .venv/bin/activate
pytest tests/ -v
pytest tests/ --cov=app --cov-report=term-missing
```

---

## Seguridad Progresiva

Los 300 dispositivos existentes **no pueden actualizar firmware**, por lo que
siguen funcionando **sin API Key** (campo `secured: false` en la respuesta).

Cuando un técnico actualice el firmware físicamente:
1. Llamar a `POST /admin/devices/register` con el IMEI
2. Programar la API Key en el firmware
3. El dispositivo empieza a enviar `X-Device-Key`
4. El campo `secured` pasa a `true` automáticamente

La métrica `devices_secured_total / (devices_secured_total + devices_legacy_total)`
en Grafana muestra el progreso de la migración.
# ztrack_a
