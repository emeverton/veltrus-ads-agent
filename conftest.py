"""
conftest.py raiz — define variáveis de ambiente mínimas para a suite de testes.

Deve ser carregado antes de qualquer import de agent.config para que
Settings() não falhe com campos obrigatórios ausentes.
"""
from __future__ import annotations

import os

# Variáveis obrigatórias (campos sem default em agent/config.py)
_REQUIRED_ENV = {
    "ANTHROPIC_API_KEY":           "sk-ant-test-key",           # pragma: allowlist secret
    "SUPABASE_URL":                "https://test.supabase.co",  # pragma: allowlist secret
    "SUPABASE_SERVICE_ROLE_KEY":   "test-service-role-key",     # pragma: allowlist secret
    "API_SECRET_KEY":              "test-api-secret-key",       # pragma: allowlist secret
    # BigQuery (opcional — testes mockam BigQuery Client)
    "GOOGLE_CLOUD_PROJECT":        "veltrus-ads-agent",
    "BIGQUERY_DATASET":            "veltrus_attribution",
    "BIGQUERY_LOCATION":           "southamerica-east1",
}

for key, value in _REQUIRED_ENV.items():
    os.environ.setdefault(key, value)
