"""Decision logic tests — pure-function, no DB/Redis."""
from datetime import UTC, datetime
from uuid import uuid4

from trading_agent.decision import decide
from trading_agent.models import Signal


def _make_signal(**overrides) -> Signal:
    base = dict(
        id=uuid4(),
        strategy_id=uuid4(),
        research_config_id=uuid4(),
        strategy_git_sha="abc123",
        research_config_version=1,
        asset="BTC",
        direction="long",
        confidence=0.80,
        composite_risk_score=0.7,
        risk_score={"source_credibility": 0.7, "narrative_novelty": 0.6,
                    "timing_precision": 0.7, "evidence_strength": 0.7},
        source_article_ids=[],
        payload={},
        published_at=datetime.now(UTC),
    )
    base.update(overrides)
    return Signal.model_validate(base)


def _cfg(**overrides) -> dict:
    base = {
        "id": uuid4(),
        "version": 1,
        "config": {
            "enabled": True,
            "min_signal_confidence": 0.70,
            "max_open_positions": 1,
            "max_daily_trades": 5,
            "stop_loss_pct": 0.02,
            "take_profit_pct": 0.04,
        },
    }
    base["config"].update(overrides)
    return base


def test_basic_long_passes():
    intent, skip = decide(
        _make_signal(), _cfg(), {},
        open_total_usd=0, open_count_asset=0, trades_today_asset=0,
        has_open_same_direction=False, halt=False,
    )
    assert skip == ""
    assert intent is not None
    assert intent.asset == "BTC"
    assert intent.direction == "long"
    assert intent.rules.stop_loss_pct == 0.02
    assert intent.rules.take_profit_pct == 0.04


def test_halt_blocks():
    intent, skip = decide(
        _make_signal(), _cfg(), {},
        open_total_usd=0, open_count_asset=0, trades_today_asset=0,
        has_open_same_direction=False, halt=True,
    )
    assert intent is None and "halt" in skip


def test_no_config_skips():
    intent, skip = decide(
        _make_signal(asset="ZZZ"), None, {},
        open_total_usd=0, open_count_asset=0, trades_today_asset=0,
        has_open_same_direction=False, halt=False,
    )
    assert intent is None and "no trading config" in skip


def test_disabled_skips():
    intent, skip = decide(
        _make_signal(), _cfg(enabled=False), {},
        open_total_usd=0, open_count_asset=0, trades_today_asset=0,
        has_open_same_direction=False, halt=False,
    )
    assert intent is None and "disabled" in skip


def test_low_confidence_skips():
    intent, skip = decide(
        _make_signal(confidence=0.50), _cfg(min_signal_confidence=0.70), {},
        open_total_usd=0, open_count_asset=0, trades_today_asset=0,
        has_open_same_direction=False, halt=False,
    )
    assert intent is None and "confidence" in skip


def test_max_open_positions_blocks():
    intent, skip = decide(
        _make_signal(), _cfg(max_open_positions=1), {},
        open_total_usd=0, open_count_asset=1, trades_today_asset=0,
        has_open_same_direction=False, halt=False,
    )
    assert intent is None and "open positions" in skip


def test_duplicate_direction_blocks():
    intent, skip = decide(
        _make_signal(), _cfg(), {},
        open_total_usd=0, open_count_asset=0, trades_today_asset=0,
        has_open_same_direction=True, halt=False,
    )
    assert intent is None and "already open" in skip


def test_max_daily_blocks():
    intent, skip = decide(
        _make_signal(), _cfg(max_daily_trades=2), {},
        open_total_usd=0, open_count_asset=0, trades_today_asset=2,
        has_open_same_direction=False, halt=False,
    )
    assert intent is None and "trades today" in skip


def test_exposure_cap_blocks():
    intent, skip = decide(
        _make_signal(), _cfg(), {},
        open_total_usd=980.0,  # plus default $50 = $1030 > $1000 cap
        open_count_asset=0, trades_today_asset=0,
        has_open_same_direction=False, halt=False,
    )
    assert intent is None and "exposure cap" in skip


def test_strategy_trading_block_provides_default():
    """If agent_config doesn't set time_stop_hours, strategy.trading does."""
    cfg = _cfg()
    del cfg["config"]["stop_loss_pct"]  # fall through
    intent, _ = decide(
        _make_signal(), cfg, {"stop_loss_pct": 0.05, "time_stop_hours": 12},
        open_total_usd=0, open_count_asset=0, trades_today_asset=0,
        has_open_same_direction=False, halt=False,
    )
    assert intent is not None
    assert intent.rules.stop_loss_pct == 0.05
    assert intent.rules.time_stop_hours == 12
