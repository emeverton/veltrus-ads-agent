"""Testes para _is_invalid_uuid em agent/tools/uuid_utils.py.

Garante que IDs externos numéricos do Meta/Google (ex: "120249189080650247")
são rejeitados e que UUIDs v4 legítimos são aceitos.
"""
from agent.tools.uuid_utils import _is_invalid_uuid


# ---------------------------------------------------------------------------
# Valores inválidos → True
# ---------------------------------------------------------------------------
class TestIsInvalidUuidRetornaTrue:
    def test_id_numerico_meta(self):
        assert _is_invalid_uuid("120249189080650247") is True

    def test_id_numerico_google(self):
        assert _is_invalid_uuid("9876543210") is True

    def test_string_none(self):
        assert _is_invalid_uuid("None") is True

    def test_string_na(self):
        assert _is_invalid_uuid("n/a") is True

    def test_string_vazia(self):
        assert _is_invalid_uuid("") is True

    def test_valor_none_python(self):
        assert _is_invalid_uuid(None) is True

    def test_string_null(self):
        assert _is_invalid_uuid("null") is True

    def test_string_placeholder(self):
        assert _is_invalid_uuid("uuid-placeholder") is True

    def test_numero_inteiro(self):
        assert _is_invalid_uuid(120249189080650247) is True


# ---------------------------------------------------------------------------
# UUID v4 válido → False
# ---------------------------------------------------------------------------
class TestIsInvalidUuidRetornaFalse:
    def test_uuid_v4(self):
        assert _is_invalid_uuid("f888f617-1692-4d9d-852f-a9d46a02b917") is False

    def test_uuid_v4_outro(self):
        assert _is_invalid_uuid("550e8400-e29b-41d4-a716-446655440000") is False

    def test_uuid_sem_hifens(self):
        assert _is_invalid_uuid("f888f61716924d9d852fa9d46a02b917") is False
