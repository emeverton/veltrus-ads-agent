# AGENTS.md — veltrus-ads-agent

## Stack
- Python 3.12, FastAPI, LangGraph, APScheduler, Supabase
- VPS: 76.13.232.175 — agent standalone em `/opt/veltrus` (docker compose)
- API Swarm: stack `veltrus` (`veltrus_api` + `veltrus_redis`) na rede `emeverton`
- Traefik: `certresolver=letsencryptresolver` — NUNCA `letsencrypt`, NUNCA Caddy em produção

## Deploy Swarm (API pública)
```bash
docker build -t veltrus:latest .
docker stack deploy -c deploy/docker-stack.yml veltrus
```

## Deploy agent standalone (não tocar api Swarm)
```bash
cd /opt/veltrus
docker compose up -d agent
```

## Regra crítica — NÃO usar `docker service update --args`

**`docker service update --args` não funciona de forma confiável no Docker Swarm.**
Mudanças de `command`/`CMD` exigem **`docker stack deploy` com arquivo YAML atualizado**
(`deploy/docker-stack.yml`).

Tentativa com `--args` pode corromper o entrypoint (`exec: "1": executable file not found`)
e pausar o serviço com `FailureAction: pause`.

## OOM — veltrus_api
- `--workers 1` (nunca 2 no VPS 8.3GB sem swap)
- `deploy.resources.limits.memory: 512M`
- `REDIS_URL=redis://veltrus_redis:6379/0` (nunca `localhost` dentro do container Swarm)

## Convenções
- NUNCA commitar `.env`
- PR sempre DRAFT até validação em produção
