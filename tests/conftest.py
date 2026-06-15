"""Configuração global de testes: variáveis de ambiente mínimas para importar módulos."""
import os

# Variáveis obrigatórias pelo Settings (pydantic-settings) sem .env real
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-dummy")
os.environ.setdefault("SUPABASE_URL", "http://localhost:54321")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("API_SECRET_KEY", "test-api-secret-key")
