"""conftest.py — mocks globais para isolar os testes do ambiente externo."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Variáveis de ambiente mínimas para que Settings() não falhe ao importar
# ---------------------------------------------------------------------------
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-key")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("API_SECRET_KEY", "test-api-secret-key")


@pytest.fixture(autouse=True)
def mock_supabase(monkeypatch):
    """Substitui o cliente Supabase por um MagicMock para todos os testes."""
    mock = MagicMock()
    monkeypatch.setattr("agent.tools.supabase_client.supabase", mock)
    return mock


@pytest.fixture(autouse=True)
def mock_llm(monkeypatch):
    """Substitui ChatAnthropic por MagicMock para evitar chamadas reais à API."""
    mock = MagicMock()
    monkeypatch.setattr("agent.graph._llm", mock)
    return mock
