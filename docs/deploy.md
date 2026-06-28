# Deploy — Docker Swarm via Portainer

Este guia descreve o deploy do Veltrus Ads Agent em produção usando **Docker Swarm** orquestrado pelo **Portainer**, com **Traefik** como proxy reverso e TLS automático via Let's Encrypt.

---

## Pré-requisitos

- Servidor Linux (Ubuntu 22.04+ recomendado) com Docker instalado
- Domínio apontando para o IP do servidor (`api.seudominio.com`, `n8n.seudominio.com`, etc.)
- Portainer CE instalado e acessível
- Redis disponível (container ou serviço externo)
- Supabase provisionado e migrations aplicadas

---

## Ordem de Inicialização dos Serviços

```
1. traefik          (proxy + TLS — deve iniciar primeiro)
2. redis            (broker Celery — dependência do api e worker)
3. api              (FastAPI — depende de redis + supabase)
4. worker           (Celery worker — depende de redis + api)
5. n8n              (automação — pode iniciar independentemente)
6. evolution        (WhatsApp — pode iniciar após n8n)
```

---

## Stack Docker Swarm — `docker-compose.swarm.yml`

```yaml
version: "3.9"

networks:
  traefik-public:
    external: true
  veltrus-internal:
    driver: overlay
    attachable: true

volumes:
  redis-data:
  n8n-data:
  traefik-certs:

services:

  # ─────────────────────────────────────────────
  # TRAEFIK — Proxy reverso + TLS automático
  # ─────────────────────────────────────────────
  traefik:
    image: traefik:v3.0
    command:
      - "--api.dashboard=true"
      - "--providers.docker=true"
      - "--providers.docker.swarmMode=true"
      - "--providers.docker.exposedByDefault=false"
      - "--providers.docker.network=traefik-public"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      - "--certificatesresolvers.letsencrypt.acme.tlschallenge=true"
      - "--certificatesresolvers.letsencrypt.acme.email=${ACME_EMAIL}"
      - "--certificatesresolvers.letsencrypt.acme.storage=/certs/acme.json"
      - "--entrypoints.web.http.redirections.entrypoint.to=websecure"
      - "--entrypoints.web.http.redirections.entrypoint.scheme=https"
      - "--log.level=INFO"
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
      - "traefik-certs:/certs"
    networks:
      - traefik-public
    deploy:
      placement:
        constraints:
          - node.role == manager
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.traefik-dashboard.rule=Host(`traefik.${DOMAIN}`)"
        - "traefik.http.routers.traefik-dashboard.entrypoints=websecure"
        - "traefik.http.routers.traefik-dashboard.tls.certresolver=letsencrypt"
        - "traefik.http.routers.traefik-dashboard.service=api@internal"
        - "traefik.http.routers.traefik-dashboard.middlewares=basic-auth"
        - "traefik.http.middlewares.basic-auth.basicauth.users=${TRAEFIK_DASHBOARD_AUTH}"

  # ─────────────────────────────────────────────
  # REDIS — Broker Celery
  # ─────────────────────────────────────────────
  redis:
    image: redis:7-alpine
    command: redis-server --save 60 1 --loglevel warning
    volumes:
      - redis-data:/data
    networks:
      - veltrus-internal
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
        delay: 5s

  # ─────────────────────────────────────────────
  # API — FastAPI (Veltrus Ads Agent)
  # ─────────────────────────────────────────────
  api:
    image: ${REGISTRY}/veltrus-api:${IMAGE_TAG:-latest}
    command: uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 2
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - ANTHROPIC_MODEL=${ANTHROPIC_MODEL:-claude-sonnet-4-6}
      - SUPABASE_URL=${SUPABASE_URL}
      - SUPABASE_ANON_KEY=${SUPABASE_ANON_KEY}
      - SUPABASE_SERVICE_ROLE_KEY=${SUPABASE_SERVICE_ROLE_KEY}
      - META_APP_ID=${META_APP_ID}
      - META_APP_SECRET=${META_APP_SECRET}
      - META_ACCESS_TOKEN=${META_ACCESS_TOKEN}
      - META_AD_ACCOUNT_ID=${META_AD_ACCOUNT_ID}
      - META_API_VERSION=${META_API_VERSION:-v21.0}
      - GOOGLE_ADS_DEVELOPER_TOKEN=${GOOGLE_ADS_DEVELOPER_TOKEN}
      - GOOGLE_ADS_CLIENT_ID=${GOOGLE_ADS_CLIENT_ID}
      - GOOGLE_ADS_CLIENT_SECRET=${GOOGLE_ADS_CLIENT_SECRET}
      - GOOGLE_ADS_REFRESH_TOKEN=${GOOGLE_ADS_REFRESH_TOKEN}
      - GOOGLE_ADS_CUSTOMER_ID=${GOOGLE_ADS_CUSTOMER_ID}
      - GOOGLE_ADS_LOGIN_CUSTOMER_ID=${GOOGLE_ADS_LOGIN_CUSTOMER_ID}
      - API_SECRET_KEY=${API_SECRET_KEY}
      - API_ALLOWED_ORIGINS=https://${DASHBOARD_DOMAIN}
      - REDIS_URL=redis://redis:6379/0
      - BREVO_API_KEY=${BREVO_API_KEY}
      - AGENT_CYCLE_INTERVAL_MINUTES=${AGENT_CYCLE_INTERVAL_MINUTES:-30}
      - AGENT_MAX_DAILY_SPEND_USD=${AGENT_MAX_DAILY_SPEND_USD:-500}
      - AGENT_MAX_BUDGET_CHANGE_PCT=${AGENT_MAX_BUDGET_CHANGE_PCT:-20}
      - AGENT_AUTONOMOUS_MODE=${AGENT_AUTONOMOUS_MODE:-false}
      - N8N_WEBHOOK_URL=https://n8n.${DOMAIN}/webhook/agent-decision
      - NOTIFY_PHONE_NUMBER=${NOTIFY_PHONE_NUMBER}
      - ENVIRONMENT=production
      - DEBUG=false
    networks:
      - traefik-public
      - veltrus-internal
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
        delay: 10s
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.veltrus-api.rule=Host(`api.${DOMAIN}`)"
        - "traefik.http.routers.veltrus-api.entrypoints=websecure"
        - "traefik.http.routers.veltrus-api.tls.certresolver=letsencrypt"
        - "traefik.http.services.veltrus-api.loadbalancer.server.port=8000"

  # ─────────────────────────────────────────────
  # WORKER — Celery (tarefas assíncronas e cron)
  # ─────────────────────────────────────────────
  worker:
    image: ${REGISTRY}/veltrus-api:${IMAGE_TAG:-latest}
    command: celery -A agent.celery_app worker --loglevel=info --concurrency=2
    environment:
      # Mesmas variáveis de ambiente do serviço api
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - SUPABASE_URL=${SUPABASE_URL}
      - SUPABASE_SERVICE_ROLE_KEY=${SUPABASE_SERVICE_ROLE_KEY}
      - REDIS_URL=redis://redis:6379/0
      - AGENT_AUTONOMOUS_MODE=${AGENT_AUTONOMOUS_MODE:-false}
      - AGENT_MAX_DAILY_SPEND_USD=${AGENT_MAX_DAILY_SPEND_USD:-500}
      - AGENT_MAX_BUDGET_CHANGE_PCT=${AGENT_MAX_BUDGET_CHANGE_PCT:-20}
      - ENVIRONMENT=production
      - DEBUG=false
    networks:
      - veltrus-internal
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
        delay: 10s

  # ─────────────────────────────────────────────
  # N8N — Automação (aprovação via WhatsApp)
  # ─────────────────────────────────────────────
  n8n:
    image: n8nio/n8n:latest
    environment:
      - N8N_BASIC_AUTH_ACTIVE=true
      - N8N_BASIC_AUTH_USER=${N8N_BASIC_AUTH_USER}
      - N8N_BASIC_AUTH_PASSWORD=${N8N_BASIC_AUTH_PASSWORD}
      - N8N_HOST=n8n.${DOMAIN}
      - N8N_PORT=5678
      - N8N_PROTOCOL=https
      - WEBHOOK_URL=https://n8n.${DOMAIN}/
      - N8N_ENCRYPTION_KEY=${N8N_ENCRYPTION_KEY}
    volumes:
      - n8n-data:/home/node/.n8n
    networks:
      - traefik-public
      - veltrus-internal
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
        delay: 5s
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.n8n.rule=Host(`n8n.${DOMAIN}`)"
        - "traefik.http.routers.n8n.entrypoints=websecure"
        - "traefik.http.routers.n8n.tls.certresolver=letsencrypt"
        - "traefik.http.services.n8n.loadbalancer.server.port=5678"

  # ─────────────────────────────────────────────
  # EVOLUTION API — WhatsApp Business
  # ─────────────────────────────────────────────
  evolution:
    image: atendai/evolution-api:latest
    environment:
      - SERVER_URL=https://evo.${DOMAIN}
      - AUTHENTICATION_API_KEY=${EVOLUTION_API_KEY}
      - DATABASE_PROVIDER=postgresql
      - DATABASE_CONNECTION_URI=${SUPABASE_DB_URI}
      - RABBITMQ_ENABLED=false
      - WEBHOOK_GLOBAL_ENABLED=true
      - WEBHOOK_GLOBAL_URL=https://n8n.${DOMAIN}/webhook/whatsapp-reply
      - WEBHOOK_GLOBAL_WEBHOOK_BY_EVENTS=true
    networks:
      - traefik-public
      - veltrus-internal
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
        delay: 10s
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.evolution.rule=Host(`evo.${DOMAIN}`)"
        - "traefik.http.routers.evolution.entrypoints=websecure"
        - "traefik.http.routers.evolution.tls.certresolver=letsencrypt"
        - "traefik.http.services.evolution.loadbalancer.server.port=8080"
```

---

## Variáveis de Ambiente Obrigatórias

Crie um arquivo `.env` na mesma pasta do compose (ou use os Secrets do Portainer):

```bash
# ──────────────────────────────────────────
# DOMÍNIO
# ──────────────────────────────────────────
DOMAIN=seudominio.com
DASHBOARD_DOMAIN=dashboard.seudominio.com
ACME_EMAIL=ops@seudominio.com

# ──────────────────────────────────────────
# IMAGEM
# ──────────────────────────────────────────
REGISTRY=registry.seudominio.com
IMAGE_TAG=latest

# ──────────────────────────────────────────
# TRAEFIK
# ──────────────────────────────────────────
TRAEFIK_DASHBOARD_AUTH=admin:$$apr1$$...  # htpasswd format

# ──────────────────────────────────────────
# ANTHROPIC (LLM)
# ──────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-6

# ──────────────────────────────────────────
# SUPABASE
# ──────────────────────────────────────────
SUPABASE_URL=https://<project-id>.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_ROLE_KEY=eyJ...
SUPABASE_DB_URI=postgresql://postgres:senha@db.supabase.co:5432/postgres

# ──────────────────────────────────────────
# META ADS
# ──────────────────────────────────────────
META_APP_ID=
META_APP_SECRET=
META_ACCESS_TOKEN=
META_AD_ACCOUNT_ID=act_
META_API_VERSION=v21.0

# ──────────────────────────────────────────
# GOOGLE ADS
# ──────────────────────────────────────────
GOOGLE_ADS_DEVELOPER_TOKEN=
GOOGLE_ADS_CLIENT_ID=
GOOGLE_ADS_CLIENT_SECRET=
GOOGLE_ADS_REFRESH_TOKEN=
GOOGLE_ADS_CUSTOMER_ID=
GOOGLE_ADS_LOGIN_CUSTOMER_ID=

# ──────────────────────────────────────────
# API
# ──────────────────────────────────────────
API_SECRET_KEY=gere-uma-chave-forte-aqui

# ──────────────────────────────────────────
# AGENTE
# ──────────────────────────────────────────
AGENT_CYCLE_INTERVAL_MINUTES=30
AGENT_MAX_DAILY_SPEND_USD=500
AGENT_MAX_BUDGET_CHANGE_PCT=20
AGENT_AUTONOMOUS_MODE=false   # true somente após validação completa em produção

# ──────────────────────────────────────────
# NOTIFICAÇÕES — n8n / WhatsApp
# ──────────────────────────────────────────
NOTIFY_PHONE_NUMBER=5511999998888

# ──────────────────────────────────────────
# BREVO
# ──────────────────────────────────────────
BREVO_API_KEY=xkeysib-...

# ──────────────────────────────────────────
# N8N
# ──────────────────────────────────────────
N8N_BASIC_AUTH_USER=admin
N8N_BASIC_AUTH_PASSWORD=senhaforte
N8N_ENCRYPTION_KEY=chave-de-32-chars-aleatoria

# ──────────────────────────────────────────
# EVOLUTION API
# ──────────────────────────────────────────
EVOLUTION_API_KEY=chave-secreta-evolution
```

---

## Deploy via Portainer

### 1. Criar rede overlay pública

```bash
docker network create --driver overlay --attachable traefik-public
```

### 2. Deploy pelo Portainer UI

1. Acesse `https://portainer.seudominio.com`
2. Vá em **Stacks → Add Stack**
3. Nome: `veltrus`
4. Cole o conteúdo do `docker-compose.swarm.yml`
5. Em **Environment variables**, adicione todas as variáveis acima
6. Clique **Deploy the stack**

### 3. Deploy via CLI

```bash
# Inicializar Swarm (se ainda não iniciado)
docker swarm init

# Deploy da stack
docker stack deploy -c docker-compose.swarm.yml veltrus

# Verificar serviços
docker stack services veltrus

# Logs de um serviço específico
docker service logs veltrus_api -f --tail=100
```

---

## Aplicar Migrations do Supabase

As migrations são aplicadas manualmente via Supabase CLI ou pelo painel:

```bash
# Via Supabase CLI
supabase db push

# Ou manualmente pelo Supabase SQL Editor, na ordem:
# 1. supabase/migrations/001_initial_schema.sql
# 2. supabase/migrations/002_add_normalized_fields.sql
# 3. supabase/migrations/003_kill_switch_log.sql
# 4. supabase/migrations/004_email_campaigns.sql
```

---

## Kill Switch via Cron

O `scripts/kill_switch.py` deve rodar a cada hora no servidor host ou em um container dedicado:

```bash
# Crontab no servidor host (crontab -e)
0 * * * * docker exec $(docker ps -qf "name=veltrus_api") \
  python scripts/kill_switch.py >> /var/log/veltrus-kill-switch.log 2>&1

# Ou via container dedicado no Swarm:
# Adicionar serviço "kill_switch" com command: "sh -c 'while true; do python scripts/kill_switch.py; sleep 3600; done'"
```

---

## Healthcheck e Monitoramento

```bash
# Verificar saúde da API
curl https://api.seudominio.com/health

# Escalar o serviço api
docker service scale veltrus_api=2

# Atualizar imagem sem downtime
docker service update --image ${REGISTRY}/veltrus-api:nova-tag veltrus_api

# Rollback
docker service rollback veltrus_api
```

---

## Build da Imagem

```dockerfile
# Dockerfile (adicionar ao projeto conforme necessário)
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
# Build e push
docker build -t ${REGISTRY}/veltrus-api:latest .
docker push ${REGISTRY}/veltrus-api:latest
```
