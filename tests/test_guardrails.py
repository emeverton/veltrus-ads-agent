"""Testes do enforcement programático de guardrails."""
from __future__ import annotations

from decimal import Decimal

from agent.guardrails import GuardrailsConfig, GuardrailsEnforcer


def _enforcer() -> GuardrailsEnforcer:
    return GuardrailsEnforcer(
        GuardrailsConfig(
            daily_budget_brl=Decimal("200"),
            max_budget_change_pct=20,
            min_roas=Decimal("2.0"),
            max_cpa_brl=Decimal("100.0"),
            max_campaigns_paused_per_cycle=2,
        )
    )


def test_budget_teto_absoluto() -> None:
    enforcer = _enforcer()
    ok, reason = enforcer.validate_budget_change(
        current_budget_brl=Decimal("100"),
        proposed_budget_brl=Decimal("201"),
        total_daily_spend_after=Decimal("201"),
    )
    assert ok is False
    assert "Teto diário excedido" in reason


def test_variacao_maxima() -> None:
    enforcer = _enforcer()
    ok, reason = enforcer.validate_budget_change(
        current_budget_brl=Decimal("100"),
        proposed_budget_brl=Decimal("125"),
        total_daily_spend_after=Decimal("125"),
    )
    assert ok is False
    assert "25.0%" in reason


def test_pausa_maxima_por_ciclo() -> None:
    enforcer = _enforcer()
    ok, reason = enforcer.validate_pause_action(campaigns_paused_this_cycle=2)
    assert ok is False
    assert "Limite de 2 pausas" in reason


def test_batch_parcialmente_aprovado() -> None:
    enforcer = _enforcer()
    actions = [
        {"type": "pause_campaign"},
        {"type": "pause_campaign"},
        {"type": "pause_campaign"},
    ]
    result = enforcer.validate_action_batch(
        actions,
        {"total_daily_spend": 50, "campaigns_paused_this_cycle": 0},
    )
    approved = [a for a in result if a.get("approved")]
    rejected = [a for a in result if not a.get("approved")]
    assert len(approved) == 2
    assert len(rejected) == 1
    assert rejected[0]["rejected_reason"]


def test_budget_minimo() -> None:
    enforcer = _enforcer()
    ok, reason = enforcer.validate_budget_change(
        current_budget_brl=Decimal("10"),
        proposed_budget_brl=Decimal("3"),
        total_daily_spend_after=Decimal("50"),
    )
    assert ok is False
    assert reason == "Budget mínimo é R$5/dia"
