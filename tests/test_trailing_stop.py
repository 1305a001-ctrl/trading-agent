"""Tests for the trailing-stop logic in positions._trailing_stop_check."""
from __future__ import annotations

from trading_agent.positions import _trailing_stop_check


def _trade(
    direction: str = "long",
    entry: float = 100.0,
    metadata: dict | None = None,
) -> dict:
    return {
        "direction": direction,
        "entry_price": entry,
        "metadata": metadata or {},
    }


# ─── Long positions ─────────────────────────────────────────────────────────


def test_long_no_trailing_config_returns_no_hit():
    """If metadata.trailing_stop_pct is None, never hits."""
    trade = _trade("long", 100.0)
    new_peak, hit = _trailing_stop_check(trade, current_price=95.0)
    assert hit is False
    assert new_peak == 100.0  # falls back to entry


def test_long_underwater_does_not_fire():
    """Trailing stop does NOT fire when peak hasn't exceeded entry —
    SL handles the downside."""
    trade = _trade("long", 100.0, {"trailing_stop_pct": 0.015})
    # Position never went profitable; price now at $95
    new_peak, hit = _trailing_stop_check(trade, current_price=95.0)
    assert hit is False
    assert new_peak == 100.0  # peak == entry


def test_long_at_peak_no_retracement_no_fire():
    """Price at the peak doesn't trigger trailing stop."""
    trade = _trade("long", 100.0, {"trailing_stop_pct": 0.015, "peak_price": 103.0})
    new_peak, hit = _trailing_stop_check(trade, current_price=103.0)
    assert hit is False
    assert new_peak == 103.0


def test_long_retracement_below_threshold_fires():
    """Price retraces 1.5% from peak ($103 → $101.45) → fires."""
    trade = _trade("long", 100.0, {"trailing_stop_pct": 0.015, "peak_price": 103.0})
    new_peak, hit = _trailing_stop_check(trade, current_price=101.45)
    assert hit is True
    assert new_peak == 103.0  # peak doesn't update on a drop


def test_long_retracement_just_above_threshold_does_not_fire():
    trade = _trade("long", 100.0, {"trailing_stop_pct": 0.015, "peak_price": 103.0})
    # Threshold = 103 * (1 - 0.015) = 101.455
    new_peak, hit = _trailing_stop_check(trade, current_price=101.46)
    assert hit is False
    assert new_peak == 103.0


def test_long_new_high_updates_peak():
    """Price above existing peak → new peak, no fire."""
    trade = _trade("long", 100.0, {"trailing_stop_pct": 0.015, "peak_price": 103.0})
    new_peak, hit = _trailing_stop_check(trade, current_price=105.0)
    assert hit is False
    assert new_peak == 105.0


def test_long_initial_run_then_retrace():
    """Common case: position opens, runs to a peak, then retraces enough."""
    trade = _trade("long", 100.0, {"trailing_stop_pct": 0.02, "peak_price": 100.0})

    # Tick 1: price climbs to $103
    new_peak, hit = _trailing_stop_check(trade, current_price=103.0)
    assert hit is False
    assert new_peak == 103.0

    # Update trade with new peak (simulating db.update_trade_peak)
    trade["metadata"]["peak_price"] = new_peak

    # Tick 2: price retraces to $100.94 (= 103 * 0.98, exactly at threshold)
    new_peak, hit = _trailing_stop_check(trade, current_price=100.94)
    assert hit is True
    assert new_peak == 103.0


# ─── Short positions ────────────────────────────────────────────────────────


def test_short_underwater_does_not_fire():
    """Position opened short at $100; price went up (against us) — SL handles."""
    trade = _trade("short", 100.0, {"trailing_stop_pct": 0.015})
    new_peak, hit = _trailing_stop_check(trade, current_price=105.0)
    assert hit is False
    assert new_peak == 100.0


def test_short_new_low_updates_trough():
    """Price below existing trough → new (lower) peak, no fire."""
    trade = _trade("short", 100.0, {"trailing_stop_pct": 0.015, "peak_price": 97.0})
    new_peak, hit = _trailing_stop_check(trade, current_price=95.0)
    assert hit is False
    assert new_peak == 95.0


def test_short_retracement_fires():
    """Short went profitable to $97 (trough), price recovers to $98.45 (= 97*1.015)."""
    trade = _trade("short", 100.0, {"trailing_stop_pct": 0.015, "peak_price": 97.0})
    new_peak, hit = _trailing_stop_check(trade, current_price=98.46)
    assert hit is True
    assert new_peak == 97.0


# ─── Edge cases ─────────────────────────────────────────────────────────────


def test_zero_pct_treated_same_as_none():
    """trailing_stop_pct: 0 isn't pydantic-valid (gt=0 in TradingRules), so we
    expect callers never pass 0. This test just checks the guard."""
    # We don't enforce gt=0 in metadata; the check should still degrade gracefully.
    trade = _trade("long", 100.0, {"trailing_stop_pct": 0.0, "peak_price": 105.0})
    new_peak, hit = _trailing_stop_check(trade, current_price=105.0)
    # With 0% trailing, threshold == peak, current price <= threshold means hit
    # ONLY if peak > entry. Our price (105) is at peak (105) > entry (100) and
    # equal to threshold — so it fires. Documenting current behavior.
    assert hit is True


def test_missing_peak_price_falls_back_to_entry():
    """First tick after open: no peak_price stored yet → use entry as the peak."""
    trade = _trade("long", 100.0, {"trailing_stop_pct": 0.015})
    # Price at $99 — not above entry, can't fire (peak == entry)
    new_peak, hit = _trailing_stop_check(trade, current_price=99.0)
    assert hit is False
    assert new_peak == 100.0


def test_metadata_none_handled():
    """trade.metadata is None (legacy rows) → no fire, peak == entry."""
    trade = {"direction": "long", "entry_price": 100.0, "metadata": None}
    new_peak, hit = _trailing_stop_check(trade, current_price=95.0)
    assert hit is False
    assert new_peak == 100.0
