#!/usr/bin/env bash
# Deploy Swarm stack veltrus (api + redis) — NÃO toca agent standalone
set -euo pipefail
cd /opt/veltrus
docker build -t veltrus:latest .
docker stack deploy -c deploy/docker-stack.yml veltrus
echo "Health: curl -s https://veltrus-api.ehos.com.br/health"
