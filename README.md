# trading-agent

Phase 5. Long-running daemon that consumes `signals:trading` + `signals:critical` from Redis and opens / closes trades. Paper broker is the default; live brokers are pluggable.

For system context, read [`infra-core/docs/ARCHITECTURE.md`](https://github.com/1305a001-ctrl/infra-core/blob/main/docs/ARCHITECTURE.md) first.

## What it does

Two concurrent loops:

| Loop | Trigger | Action |
|---|---|---|
| `signal_loop` | Redis pubsub message | look up agent_config (slug = asset), evaluate gates, open paper trade |
| `position_loop` | every `POLL_INTERVAL_SECONDS` | walk every open trade, fetch current price, close on TP / SL / time-stop |

Both write to the same `trades` table. Closed trades also get a `signal_outcomes` row so consistency tracking works downstream.

## SL/TP precedence

```
agent_config (UI-editable)  →  strategy.frontmatter.trading  →  hardcoded defaults
```

Edit per-asset SL/TP, take-profit, min confidence, max positions etc. via the control-plane `/trading` page — the agent picks up changes on the next signal (no restart needed).

## Module map

```
src/trading_agent/
├── main.py            # asyncio entry — runs signal_loop + position_loop concurrently
├── settings.py        # pydantic-settings; all env vars + tunables
├── db.py              # asyncpg pool + JSONB codec + every read/write the agent needs
├── decision.py        # PURE — signal × agent_config × strategy.trading → TradeIntent
│                      #         (covered by tests/test_decision.py)
├── models.py          # Signal, TradingRules, TradeIntent, Fill — pydantic types
├── prices.py          # Binance public (crypto) + Finnhub (US equities) price feeds
├── positions.py       # the polling loop — TP / SL / time-stop check + close
├── alerts.py          # Telegram open / close formatters
└── brokers/
    ├── base.py        # Broker protocol
    ├── paper.py       # default — fills using live mid prices, no real orders
    ├── alpaca.py      # US equities — paper at paper-api.alpaca.markets, flip ALPACA_BASE_URL for live
    ├── __init__.py    # registry — get_broker(name); Alpaca only registers when creds present
    └── (binance.py, ibkr.py — TODO; see "Adding a broker" below)
```

## Adding a broker

1. Create `src/trading_agent/brokers/<name>.py` implementing the `Broker` protocol from `base.py`:
   ```python
   class MyBroker:
       name = "my_broker"
       async def open(self, asset: str, direction: str, size_usd: float) -> Fill: ...
       async def close(self, broker_order_id: str, asset: str) -> float: ...
   ```
2. Register it in `brokers/__init__.py`
3. Add to the `broker` literal in `models.py::TradingRules` and the `CHECK (broker IN ...)` constraint in `migrations/003_trades.sql`
4. Add env vars (API key, base URL) to `settings.py` and `/srv/secrets/trading-agent.env`
5. Update the agent_config or strategy.trading block to set `broker: "<name>"`

Paper mode is always the safety net — if a live broker call raises, the trade is `rejected` and never partially opens.

### Enabling Alpaca

1. Sign up at https://alpaca.markets, generate **Paper** API keys from the dashboard
2. Set `ALPACA_API_KEY` + `ALPACA_SECRET` in `/srv/secrets/trading-agent.env`
3. `ALPACA_BASE_URL` defaults to `https://paper-api.alpaca.markets` — flip to `https://api.alpaca.markets` for live (and use a live key)
4. Set the broker per-asset:
   - via control-plane `/trading/new` config: add `"broker": "alpaca"` to that asset's config (UI exposing this is a TODO)
   - or via strategy frontmatter `trading.broker: alpaca`
5. Restart the container — Alpaca auto-registers on startup when creds are present

Alpaca paper accounts have $100k of fake cash; orders queue if placed outside RTH and time out at `ALPACA_FILL_TIMEOUT_SECONDS` (default 30s).

## Risk envelope (defaults; override in env file)

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

## Tests

```bash
pip install -e '.[dev]'
pytest -q
```

`tests/test_decision.py` covers every decision branch (halt, no-config, low-confidence, max-positions, dup-direction, max-daily, exposure-cap, fallback chain).

## Wire-up

1. Apply migration:
   ```bash
   cat migrations/003_trades.sql | ssh ai-primary 'sudo docker exec -i postgres psql -U benadmin -d aicore'
   ```
2. Create per-asset configs via control-plane `/trading/new`
3. Set env at `/srv/secrets/trading-agent.env` (Postgres, Redis, Finnhub key for stock prices, Telegram creds, optional Sentry)
4. `docker compose -f infra-core/compose/trading-agent/docker-compose.yml up -d`

See [LOCAL-DEV.md](https://github.com/1305a001-ctrl/infra-core/blob/main/docs/LOCAL-DEV.md) for running locally + hand-publishing test signals.
