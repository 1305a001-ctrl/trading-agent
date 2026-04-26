# trading-agent

Phase 5 consumer for `signals:trading` + `signals:critical` Redis channels published by [news-consolidator](https://github.com/1305a001-ctrl/news-consolidator).

**Status:** v0.1 — paper broker only. Alpaca / Binance / IBKR are stubs.

## What it does

1. Subscribes to `signals:trading` + `signals:critical` on Redis.
2. For each signal, looks up the matching `agent_configs` row (slug = asset symbol) from the control plane.
3. If the signal passes filters (confidence, max open positions, max daily trades, exposure cap) → opens a paper trade.
4. Polls open positions every 60s; closes on TP / SL / time-stop using live Binance/Finnhub prices.
5. Writes `signal_outcomes` rows for every closed trade so consistency tracking works.
6. Telegram alert on every fill (open + close).

## SL/TP precedence

```
agent_config (UI: /trading)  →  strategy.frontmatter.trading  →  hardcoded settings defaults
```

Edit per-asset SL/TP, take-profit, min confidence, max positions etc. via the control-plane `/trading` page — the agent picks up changes on the next signal.

## Risk envelope (v0.1 hardcoded; configurable later)

| Setting | Default | Env var |
|---|---|---|
| Size per signal | $50 | `SIZE_PER_SIGNAL_USD` |
| Total exposure cap | $1000 | `TOTAL_EXPOSURE_CAP_USD` |
| Default SL | 2% | `DEFAULT_STOP_LOSS_PCT` |
| Default TP | 4% | `DEFAULT_TAKE_PROFIT_PCT` |
| Default time stop | 24h | `DEFAULT_TIME_STOP_HOURS` |
| Min confidence | 0.65 | `MIN_CONFIDENCE` |
| Position poll | 60s | `POLL_INTERVAL_SECONDS` |
| Halt switch | off | `TRADING_AGENT_HALT=1` |

Setting `TRADING_AGENT_HALT=1` blocks new opens but lets existing positions exit normally.

## Wire-up

1. Apply migration: `psql ... < migrations/003_trades.sql`
2. Set env (Redis URL, Postgres URL, Finnhub key for stock prices, Telegram creds).
3. `docker compose up -d` — agent runs forever, restarts on failure.
