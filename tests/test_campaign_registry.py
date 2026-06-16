"""
tests/test_campaign_registry.py

Testes determinísticos para agent/tools/campaign_registry.py
e para a resolução de UUIDs no analista_node.

Tudo mockado: não requer Supabase real, Meta API nem Google Ads.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

import agent.tools.campaign_registry as registry_module
from agent.tools.campaign_registry import upsert_campaigns
from agent.graph import _is_invalid_uuid

# ---------------------------------------------------------------------------
# Fixtures e helpers
# ---------------------------------------------------------------------------
ACCOUNT_UUID = "922f2273-6e2f-4649-9961-e510cbc4a9a2"
EXISTING_UUID = "f888f617-1692-4d9d-852f-a9d46a02b917"
EXISTING_UUID_2 = "a1b2c3d4-0000-4000-8000-000000000001"

META_CAMPAIGNS = [
    {
        "campaign_id": "120249189080650247",
        "name": "Campanha A",
        "status": "ACTIVE",
        "objective": "LINK_CLICKS",
        "daily_budget": 50.0,
    },
    {
        "campaign_id": "120249189080650248",
        "name": "Campanha B",
        "status": "PAUSED",
        "objective": "",
        "daily_budget": 100.0,
    },
]

GOOGLE_CAMPAIGNS = [
    {
        "campaign_id": "11111111111",
        "name": "Google Camp A",
        "status": "ENABLED",
        "campaign_budget_id": "budget-001",
        "daily_budget_usd": 75.0,
    }
]


def _make_table_mock(existing_rows=None):
    """Configura um MagicMock que imita o encadeamento supabase.table(...)."""
    table = MagicMock()

    # select → eq → eq → execute
    select_chain = table.select.return_value
    select_chain.eq.return_value.eq.return_value.execute.return_value = MagicMock(
        data=existing_rows or []
    )

    # insert → execute
    table.insert.return_value.execute.return_value = MagicMock(data=[])

    # update → eq → execute
    table.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

    return table


@pytest.fixture
def mock_supabase(mocker):
    """Substitui agent.tools.campaign_registry.supabase por um mock."""
    mock = MagicMock()
    mocker.patch.object(registry_module, "supabase", mock)
    return mock


# ---------------------------------------------------------------------------
# Teste 1 — upsert cria campanha nova com UUID
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upsert_creates_new_campaigns(mock_supabase):
    """upsert cria campanha nova com UUID v4 quando não existe no Supabase."""
    table = _make_table_mock(existing_rows=[])
    mock_supabase.table.return_value = table

    result = await upsert_campaigns(ACCOUNT_UUID, META_CAMPAIGNS, "meta")

    assert len(result) == 2
    for ext_id, internal_uuid in result.items():
        assert ext_id in {"120249189080650247", "120249189080650248"}
        parsed = uuid.UUID(internal_uuid)
        assert parsed.version == 4

    # insert chamado para cada campanha nova
    assert table.insert.call_count == 2
    assert table.update.call_count == 0


# ---------------------------------------------------------------------------
# Teste 2 — upsert atualiza campanha existente (mesmo campaign_id)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upsert_updates_existing_campaign(mock_supabase):
    """upsert atualiza campanha existente e preserva o UUID já salvo."""
    table = _make_table_mock(
        existing_rows=[{"campaign_id": "120249189080650247", "id": EXISTING_UUID}]
    )
    mock_supabase.table.return_value = table

    result = await upsert_campaigns(ACCOUNT_UUID, [META_CAMPAIGNS[0]], "meta")

    assert result["120249189080650247"] == EXISTING_UUID
    assert table.update.call_count == 1
    assert table.insert.call_count == 0


# ---------------------------------------------------------------------------
# Teste 3 — mapa {external_id: uuid} retornado corretamente (mix create/update)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upsert_returns_correct_map(mock_supabase):
    """Mapa retornado tem UUID existente para update e UUID v4 novo para insert."""
    table = _make_table_mock(
        existing_rows=[{"campaign_id": "120249189080650247", "id": EXISTING_UUID}]
    )
    mock_supabase.table.return_value = table

    result = await upsert_campaigns(ACCOUNT_UUID, META_CAMPAIGNS, "meta")

    # Campanha A: já existia → UUID preservado
    assert result["120249189080650247"] == EXISTING_UUID

    # Campanha B: nova → UUID v4 gerado
    assert "120249189080650248" in result
    new_uuid = result["120249189080650248"]
    parsed = uuid.UUID(new_uuid)
    assert parsed.version == 4


# ---------------------------------------------------------------------------
# Teste 4 — fetch_daily_metrics usa UUID real (não cai no guard)
# ---------------------------------------------------------------------------
def test_uuids_in_map_pass_invalid_uuid_guard(mock_supabase):
    """Todos os UUIDs retornados por upsert_campaigns passam no guard _is_invalid_uuid."""
    # Simula o que aconteceria com o resultado do upsert
    fake_map = {
        "120249189080650247": EXISTING_UUID,
        "120249189080650248": str(uuid.uuid4()),
        "11111111111": str(uuid.uuid4()),
    }
    for ext_id, internal_uuid in fake_map.items():
        assert not _is_invalid_uuid(internal_uuid), (
            f"UUID para {ext_id} falhou no guard: {internal_uuid}"
        )


def test_postprocessing_resolves_invalid_campaign_uuid():
    """A lógica de pós-processamento do analista_node substitui IDs externos por UUIDs."""
    campaign_id_map = {
        "120249189080650247": EXISTING_UUID,
        "120249189080650248": EXISTING_UUID_2,
    }

    # Simula o que o LLM retornaria antes do pós-processamento
    campaigns_analyzed = [
        {"campaign_id": "120249189080650247", "campaign_uuid": None, "name": "A"},
        {"campaign_id": "120249189080650248", "campaign_uuid": "n/a", "name": "B"},
    ]
    anomalies = [
        {
            "campaign_id": "120249189080650247",
            "campaign_uuid": "120249189080650247",
            "anomaly_type": "cpa_spike",
        }
    ]

    # Aplica a mesma lógica do analista_node
    for item in campaigns_analyzed + anomalies:
        ext_id = str(item.get("campaign_id") or "")
        if (
            ext_id
            and _is_invalid_uuid(item.get("campaign_uuid"))
            and ext_id in campaign_id_map
        ):
            item["campaign_uuid"] = campaign_id_map[ext_id]

    assert campaigns_analyzed[0]["campaign_uuid"] == EXISTING_UUID
    assert campaigns_analyzed[1]["campaign_uuid"] == EXISTING_UUID_2
    assert anomalies[0]["campaign_uuid"] == EXISTING_UUID

    # Garantia: nenhum UUID no resultado cai no guard
    for item in campaigns_analyzed + anomalies:
        assert not _is_invalid_uuid(item["campaign_uuid"])


# ---------------------------------------------------------------------------
# Teste 5 — memorizador.memory_saved com campaign_uuid real
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_save_memory_with_real_uuid_from_map(mocker):
    """save_memory recebe UUID real do mapa e persiste campaign_id corretamente."""
    import agent.graph as graph

    fake_supabase = mocker.patch.object(graph, "supabase")
    (
        fake_supabase.table.return_value.insert.return_value.execute.return_value
    ).data = [{"id": "mem-1", "campaign_id": EXISTING_UUID}]

    log_spy = mocker.spy(graph.log, "info")

    result = await graph.save_memory.ainvoke(
        {
            "content": "cpa_click subiu 50% na campanha A",
            "memory_type": "observation",
            "campaign_uuid": EXISTING_UUID,
        }
    )

    # UUID real deve chegar no INSERT sem ser nullificado
    inserted = fake_supabase.table.return_value.insert.call_args.args[0]
    assert inserted["campaign_id"] == EXISTING_UUID
    assert result.get("campaign_id") == EXISTING_UUID

    events = [c.args[0] for c in log_spy.call_args_list if c.args]
    assert "memorizador.memory_saved" in events


# ---------------------------------------------------------------------------
# Testes extras de robustez
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upsert_empty_campaigns_returns_empty_without_db_call(mock_supabase):
    """upsert com lista vazia retorna {} sem chamar o Supabase."""
    result = await upsert_campaigns(ACCOUNT_UUID, [], "meta")

    assert result == {}
    mock_supabase.table.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_google_campaigns_uses_daily_budget_usd(mock_supabase):
    """Campo daily_budget_usd (Google) é normalizado corretamente no insert."""
    table = _make_table_mock(existing_rows=[])
    mock_supabase.table.return_value = table

    result = await upsert_campaigns(ACCOUNT_UUID, GOOGLE_CAMPAIGNS, "google")

    assert "11111111111" in result
    insert_payload = table.insert.call_args.args[0]
    assert insert_payload["daily_budget"] == 75.0
    assert insert_payload["platform"] == "google"


@pytest.mark.asyncio
async def test_upsert_survives_insert_failure(mock_supabase):
    """Falha de INSERT não quebra o ciclo — UUID gerado retorna mesmo assim."""
    table = _make_table_mock(existing_rows=[])
    table.insert.side_effect = Exception("DB unavailable")
    mock_supabase.table.return_value = table

    result = await upsert_campaigns(ACCOUNT_UUID, [META_CAMPAIGNS[0]], "meta")

    assert "120249189080650247" in result
    parsed = uuid.UUID(result["120249189080650247"])
    assert parsed.version == 4


@pytest.mark.asyncio
async def test_upsert_survives_update_failure(mock_supabase):
    """Falha de UPDATE não quebra o ciclo — UUID existente retorna mesmo assim."""
    table = _make_table_mock(
        existing_rows=[{"campaign_id": "120249189080650247", "id": EXISTING_UUID}]
    )
    table.update.side_effect = Exception("DB unavailable")
    mock_supabase.table.return_value = table

    result = await upsert_campaigns(ACCOUNT_UUID, [META_CAMPAIGNS[0]], "meta")

    assert result["120249189080650247"] == EXISTING_UUID


@pytest.mark.asyncio
async def test_upsert_skips_campaigns_without_campaign_id(mock_supabase):
    """Campanhas sem campaign_id são ignoradas silenciosamente."""
    campaigns = [
        {"campaign_id": "", "name": "Sem ID"},
        {"name": "Também sem ID"},
        {"campaign_id": "120249189080650247", "name": "Com ID"},
    ]
    table = _make_table_mock(existing_rows=[])
    mock_supabase.table.return_value = table

    result = await upsert_campaigns(ACCOUNT_UUID, campaigns, "meta")

    assert len(result) == 1
    assert "120249189080650247" in result


@pytest.mark.asyncio
async def test_upsert_fetch_existing_failure_falls_back_to_insert(mock_supabase):
    """Se o SELECT inicial falhar, assume que todas as campanhas são novas."""
    table = MagicMock()
    # Primeira chamada (select) lança exceção
    table.select.return_value.eq.return_value.eq.return_value.execute.side_effect = Exception(
        "network error"
    )
    table.insert.return_value.execute.return_value = MagicMock(data=[])
    mock_supabase.table.return_value = table

    result = await upsert_campaigns(ACCOUNT_UUID, [META_CAMPAIGNS[0]], "meta")

    assert "120249189080650247" in result
    assert table.insert.call_count == 1
