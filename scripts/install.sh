#!/usr/bin/env bash
# ==============================================================================
# install.sh — Instalación del sistema ZTRACK API
# ==============================================================================
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$PROJECT_DIR/.venv"

info "Instalando ZTRACK API en $PROJECT_DIR"
python3.12 -m venv "$VENV"
source "$VENV/bin/activate"
pip install --upgrade pip --quiet
pip install -r "$PROJECT_DIR/requirements.txt" --quiet
info "Dependencias instaladas"

[ ! -f "$PROJECT_DIR/.env" ] && cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env" \
    && warning "Revisar $PROJECT_DIR/.env antes de iniciar en producción"

mkdir -p /var/log/ztrack

# ── Servicio API principal ────────────────────────────────────────────────────
cat > /etc/systemd/system/ztrack_api.service << EOF
[Unit]
Description=ZTRACK API - Telemetría IoT
After=network.target mongod.service redis.service

[Service]
Type=simple
User=www-data
WorkingDirectory=${PROJECT_DIR}
Environment=PATH=${VENV}/bin:/usr/bin
ExecStart=${VENV}/bin/gunicorn -c gunicorn.conf.py app.main:app
Restart=always
RestartSec=5
KillMode=mixed
TimeoutStopSec=30
StandardOutput=append:/var/log/ztrack/api.log
StandardError=append:/var/log/ztrack/api_error.log

[Install]
WantedBy=multi-user.target
EOF

# ── Servicio Batch Writer ─────────────────────────────────────────────────────
cat > /etc/systemd/system/ztrack_batch.service << EOF
[Unit]
Description=ZTRACK Batch Writer - Redis a MongoDB
After=network.target mongod.service redis.service

[Service]
Type=simple
User=www-data
WorkingDirectory=${PROJECT_DIR}
Environment=PATH=${VENV}/bin:/usr/bin
Environment=APP_ENV=production
ExecStart=${VENV}/bin/python -m app.workers.batch_writer
Restart=always
RestartSec=5
StandardOutput=append:/var/log/ztrack/batch.log
StandardError=append:/var/log/ztrack/batch_error.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ztrack_api ztrack_batch
info "Servicios registrados"

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  INSTALACIÓN COMPLETA${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  1. Editar configuración: nano $PROJECT_DIR/.env"
echo "  2. Iniciar: sudo systemctl start ztrack_api ztrack_batch"
echo "  3. Verificar: curl http://localhost:9050/health"
echo "  4. Tests: source .venv/bin/activate && pytest"
echo ""
