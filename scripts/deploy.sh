#!/usr/bin/env bash
# Veltrus Ads Agent — deploy rápido (rebuild + restart)
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/veltrus}"
cd "$APP_DIR"

docker compose pull 2>/dev/null || true
docker compose up -d --build --remove-orphans
docker compose ps
curl -fsS http://127.0.0.1:8000/health && echo
