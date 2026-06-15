"""Utilitários de validação de UUID para proteção de INSERTs no Supabase.

Separado de graph.py para permitir import em testes sem as dependências pesadas
(google-ads, facebook_business, langchain, etc.).
"""
from __future__ import annotations

import uuid as _uuid_mod
from typing import Any


def _is_invalid_uuid(value: Any) -> bool:
    """Retorna True se *value* NÃO for um UUID válido (v4 ou qualquer versão).

    Bloqueia IDs externos numéricos do Meta/Google (ex: "120249189080650247"),
    placeholders do LLM ("None", "n/a", "") e qualquer string que o Postgres
    rejeitaria com "invalid input syntax for type uuid".

    Exemplos:
        _is_invalid_uuid("120249189080650247")                → True  (Meta campaign_id)
        _is_invalid_uuid("n/a")                               → True
        _is_invalid_uuid(None)                                → True
        _is_invalid_uuid("f888f617-1692-4d9d-852f-a9d46a02b917") → False
    """
    if not value:
        return True
    try:
        _uuid_mod.UUID(str(value))
        return False
    except (ValueError, AttributeError):
        return True
