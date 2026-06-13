FROM python:3.12-slim

WORKDIR /app

# Instala dependências do sistema necessárias para pacotes nativos (google-ads, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Comando padrão: API. Substituído por python -m agent.main no serviço agent.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
