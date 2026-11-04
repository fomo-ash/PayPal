"""Settings loaded from environment / .env. Import `settings` everywhere; never read os.environ directly."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

PAYPAL_BASE_URLS = {
    "sandbox": "https://api-m.sandbox.paypal.com",
    "live": "https://api-m.paypal.com",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    paypal_env: str = "sandbox"
    paypal_client_id: str = ""
    paypal_secret: str = ""
    paypal_webhook_id: str = ""
    paypal_return_url: str = "http://localhost:3000/fund/return"
    paypal_cancel_url: str = "http://localhost:3000/fund/cancel"
    paypal_login_redirect_uri: str = "http://localhost:3000/auth/callback"

    anthropic_api_key: str = ""
    judge_model: str = "claude-sonnet-5-5"
    draft_model: str = "claude-haiku-5-5"

    sandbox_backend: str = "e2b"
    e2b_api_key: str = ""
    sandbox_test_timeout_ms: int = 2000
    sandbox_memory_mb: int = 512

    database_url: str = "postgresql+psycopg://verdict:verdict@localhost:5432/verdict"
    redis_url: str = "redis://localhost:6379/0"

    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "verdict-dev"

    platform_fee_bps: int = 500
    max_job_deadline_hours: int = 48
    fresh_input_count: int = 200
    new_buyer_payout_delay_hours: int = 0

    receipt_signing_key_b64: str = ""

    @property
    def paypal_base_url(self) -> str:
        if self.paypal_env not in PAYPAL_BASE_URLS:
            raise ValueError("PAYPAL_ENV must be 'sandbox' or 'live'")
        return PAYPAL_BASE_URLS[self.paypal_env]


@lru_cache
def get_settings() -> Settings:
    return Settings()
