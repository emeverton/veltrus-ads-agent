"""Enforcement programático de guardrails — sem LLM."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass
class GuardrailsConfig:
    daily_budget_brl: Decimal
    max_budget_change_pct: int = 20
    min_roas: Decimal = Decimal("2.0")
    max_cpa_brl: Decimal = Decimal("100.0")
    max_campaigns_paused_per_cycle: int = 2
    max_total_change_pct: int = 30


class GuardrailsEnforcer:
    def __init__(self, config: GuardrailsConfig) -> None:
        self.config = config

    def validate_budget_change(
        self,
        current_budget_brl: Decimal,
        proposed_budget_brl: Decimal,
        total_daily_spend_after: Decimal,
    ) -> tuple[bool, str]:
        if proposed_budget_brl < Decimal("5.0"):
            return False, "Budget mínimo é R$5/dia"

        if total_daily_spend_after > self.config.daily_budget_brl:
            return (
                False,
                f"Teto diário excedido: R${total_daily_spend_after} > R${self.config.daily_budget_brl}",
            )

        if current_budget_brl > 0:
            change_pct = abs(proposed_budget_brl - current_budget_brl) / current_budget_brl * 100
            if change_pct > self.config.max_budget_change_pct:
                return (
                    False,
                    f"Variação {change_pct:.1f}% excede limite {self.config.max_budget_change_pct}%",
                )

        return True, ""

    def validate_pause_action(self, campaigns_paused_this_cycle: int) -> tuple[bool, str]:
        if campaigns_paused_this_cycle >= self.config.max_campaigns_paused_per_cycle:
            return (
                False,
                f"Limite de {self.config.max_campaigns_paused_per_cycle} pausas por ciclo atingido",
            )
        return True, ""

    def validate_roas(self, roas: Decimal) -> tuple[bool, str]:
        if roas < self.config.min_roas:
            return False, f"ROAS {roas:.2f}x abaixo do mínimo {self.config.min_roas}x"
        return True, ""

    def validate_cpa(self, cpa_brl: Decimal) -> tuple[bool, str]:
        if cpa_brl > self.config.max_cpa_brl:
            return False, f"CPA R${cpa_brl:.2f} acima do máximo R${self.config.max_cpa_brl}"
        return True, ""

    def validate_action_batch(
        self,
        actions: list[dict[str, Any]],
        current_state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        approved_actions: list[dict[str, Any]] = []
        pauses_this_cycle = int(current_state.get("campaigns_paused_this_cycle", 0))
        total_spend_after = Decimal(str(current_state.get("total_daily_spend", 0)))

        for action in actions:
            action_type = action.get("type") or action.get("action_type", "")

            if action_type == "pause_campaign":
                ok, reason = self.validate_pause_action(pauses_this_cycle)
                if ok:
                    pauses_this_cycle += 1
                    approved_actions.append({**action, "approved": True})
                else:
                    approved_actions.append({**action, "approved": False, "rejected_reason": reason})

            elif action_type in ("update_budget", "budget_increase", "budget_decrease"):
                current_budget = Decimal(str(action.get("current_budget", 0)))
                new_budget = Decimal(str(action.get("new_budget", 0)))
                new_total = (
                    total_spend_after
                    - current_budget
                    + new_budget
                )
                ok, reason = self.validate_budget_change(
                    current_budget_brl=current_budget,
                    proposed_budget_brl=new_budget,
                    total_daily_spend_after=new_total,
                )
                if ok:
                    total_spend_after = new_total
                    approved_actions.append({**action, "approved": True})
                else:
                    approved_actions.append({**action, "approved": False, "rejected_reason": reason})

            else:
                approved_actions.append({**action, "approved": True})

        return approved_actions


def decision_to_guardrail_action(
    decision: dict[str, Any],
    *,
    current_budget_brl: Decimal,
    usd_brl_rate: Decimal = Decimal("5.0"),
) -> dict[str, Any] | None:
    """Converte decisão do estrategista para formato do enforcer."""
    action_type = decision.get("action_type", "")
    if not action_type or action_type == "monitor_only":
        return None

    params = decision.get("params") or {}

    if action_type == "pause_campaign":
        return {"type": "pause_campaign", "action_type": action_type}

    if action_type in ("budget_increase", "budget_decrease"):
        new_budget_raw = (
            params.get("new_budget_brl")
            or params.get("new_budget_usd")
            or params.get("daily_budget_usd")
        )
        if new_budget_raw is None:
            return None

        new_budget = Decimal(str(new_budget_raw))
        if "new_budget_usd" in params or "daily_budget_usd" in params:
            if "new_budget_brl" not in params:
                new_budget = new_budget * usd_brl_rate

        return {
            "type": "update_budget",
            "action_type": action_type,
            "current_budget": current_budget_brl,
            "new_budget": new_budget,
        }

    if action_type == "activate_campaign":
        return {"type": "activate_campaign", "action_type": action_type}

    return {"type": action_type, "action_type": action_type}
