-- Migration 010: trailing_stop close_reason + metadata.peak_price
--
-- Adds 'trailing_stop' as a valid close_reason on trades. The trailing-stop
-- exit fires when price retraces `metadata.trailing_stop_pct` from the peak
-- (high for longs, low for shorts) AFTER the position has gone profitable.
--
-- peak_price lives in trades.metadata JSONB (no schema column needed):
--   metadata.trailing_stop_pct  — config (set at intent time, immutable)
--   metadata.peak_price         — running track (UPDATE on each price tick)

ALTER TABLE trades DROP CONSTRAINT IF EXISTS trades_close_reason_check;

ALTER TABLE trades ADD CONSTRAINT trades_close_reason_check
  CHECK (
    close_reason IS NULL OR close_reason = ANY (
      ARRAY['tp', 'sl', 'time_stop', 'trailing_stop',
            'manual', 'error', 'reverse_signal']::text[]
    )
  );
