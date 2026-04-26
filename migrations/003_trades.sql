-- Phase 5 trading agent: trades table.
-- Tracks every order placed (paper or live) from signal to close.
-- Run: cat migrations/003_trades.sql | ssh benadmin@ai-primary "sudo docker exec -i postgres psql -U benadmin -d aicore"

CREATE TABLE IF NOT EXISTS trades (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  signal_id UUID NOT NULL REFERENCES market_signals(id),
  agent_config_id UUID NOT NULL REFERENCES agent_configs(id),
  agent_config_version INTEGER NOT NULL,
  asset TEXT NOT NULL,
  direction TEXT NOT NULL,
  broker TEXT NOT NULL,
  size_usd REAL NOT NULL,
  entry_price REAL,
  qty REAL,
  take_profit_price REAL,
  stop_loss_price REAL,
  time_stop_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'pending',
  broker_order_id TEXT,
  opened_at TIMESTAMPTZ,
  closed_at TIMESTAMPTZ,
  exit_price REAL,
  pnl_usd REAL,
  close_reason TEXT,
  errors JSONB NOT NULL DEFAULT '[]'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (status IN ('pending','open','closed','cancelled','rejected','error')),
  CHECK (direction IN ('long','short')),
  CHECK (broker IN ('paper','alpaca','binance','ibkr')),
  CHECK (close_reason IS NULL OR close_reason IN ('tp','sl','time_stop','manual','error','reverse_signal'))
);

CREATE INDEX IF NOT EXISTS trades_status_idx ON trades (status);
CREATE INDEX IF NOT EXISTS trades_signal_idx ON trades (signal_id);
CREATE INDEX IF NOT EXISTS trades_asset_open_idx ON trades (asset) WHERE status IN ('pending','open');
CREATE INDEX IF NOT EXISTS trades_opened_at_idx ON trades (opened_at);
