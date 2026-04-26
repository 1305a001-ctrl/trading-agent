"""Pure function: signal + agent_config + strategy.trading → TradeIntent or None.

agent_config is per-asset (UI: /trading page, slug = asset symbol).
SL/TP precedence: agent_config (editable in UI) > strategy.trading > settings defaults.

UI config schema (from control-plane /trading/new):
  enabled, position_size_pct, max_open_positions, take_profit_pct,
  stop_loss_pct, min_signal_confidence, max_daily_trades, notes
"""
import logging

from trading_agent.models import Signal, TradeIntent, TradingRules
from trading_agent.settings import settings

log = logging.getLogger(__name__)


def _resolve_rules(agent_config_data: dict, strategy_trading: dict) -> TradingRules:
    """Layered defaults: agent_config (UI) → strategy.trading → settings."""
    def pick(key: str, default):
        if key in agent_config_data and agent_config_data[key] is not None:
            return agent_config_data[key]
        if key in strategy_trading and strategy_trading[key] is not None:
            return strategy_trading[key]
        return default

    return TradingRules(
        stop_loss_pct=float(pick("stop_loss_pct", settings.default_stop_loss_pct)),
        take_profit_pct=float(pick("take_profit_pct", settings.default_take_profit_pct)),
        time_stop_hours=int(pick("time_stop_hours", settings.default_time_stop_hours)),
        size_usd=float(settings.size_per_signal_usd),  # MVP: fixed $50/signal
        broker=pick("broker", settings.default_broker),
    )


def decide(
    signal: Signal,
    agent_config: dict | None,
    strategy_trading: dict,
    *,
    open_total_usd: float,
    open_count_asset: int,
    trades_today_asset: int,
    has_open_same_direction: bool,
    halt: bool,
) -> tuple[TradeIntent | None, str]:
    """Return (intent, skip_reason). Exactly one is set."""
    if halt:
        return None, "halt switch on"
    if signal.direction not in ("long", "short"):
        return None, f"non-actionable direction {signal.direction!r}"
    if agent_config is None:
        return None, f"no trading config for asset {signal.asset}"

    cfg = agent_config["config"]

    if not cfg.get("enabled", True):
        return None, f"config for {signal.asset} is disabled"

    min_conf = float(cfg.get("min_signal_confidence", settings.min_confidence))
    if signal.confidence < min_conf:
        return None, f"confidence {signal.confidence:.2f} < {min_conf:.2f}"

    max_open = int(cfg.get("max_open_positions", 1))
    if open_count_asset >= max_open:
        return None, f"already {open_count_asset}/{max_open} open positions for {signal.asset}"

    if has_open_same_direction:
        return None, f"already open {signal.asset} {signal.direction}"

    max_daily = int(cfg.get("max_daily_trades", 2))
    if trades_today_asset >= max_daily:
        return None, f"already {trades_today_asset}/{max_daily} trades today for {signal.asset}"

    rules = _resolve_rules(cfg, strategy_trading)

    if open_total_usd + rules.size_usd > settings.total_exposure_cap_usd:
        return None, (
            f"would exceed exposure cap: ${open_total_usd:.0f} + ${rules.size_usd:.0f} "
            f"> ${settings.total_exposure_cap_usd:.0f}"
        )

    return TradeIntent(
        signal_id=signal.id,
        agent_config_id=agent_config["id"],
        agent_config_version=agent_config["version"],
        asset=signal.asset,
        direction=signal.direction,
        rules=rules,
    ), ""
