from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database + Redis (validated at connect time, not import time, so tests can import without env)
    aicore_db_url: str = ""
    redis_url: str = "redis://localhost:6379"

    # Risk envelope (hardcoded defaults; agent_config overrides per-asset)
    size_per_signal_usd: float = 50.0
    total_exposure_cap_usd: float = 1000.0
    default_stop_loss_pct: float = 0.02
    default_take_profit_pct: float = 0.04
    default_time_stop_hours: int = 24
    min_confidence: float = 0.65

    # Position polling cadence
    poll_interval_seconds: int = 60

    # Kill switch — set TRADING_AGENT_HALT=1 to stop opening new positions
    trading_agent_halt: bool = False

    # Brokers — paper is the only one wired in v0.1
    default_broker: str = "paper"

    # Price feeds (used by paper broker)
    finnhub_key: str = ""
    binance_base_url: str = "https://api.binance.com"

    # Notifications
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Sentry
    sentry_dsn: str = ""


settings = Settings()
