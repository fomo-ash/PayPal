"""Settings from environment / .env. Import get_settings() everywhere; never read os.environ."""

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
    sandbox_worker_email: str = ""            # demo worker's sandbox PayPal (payout receiver)
    paypal_login_redirect_uri: str = "http://localhost:3000/auth/callback"

    # LLM: any OpenAI-compatible provider. Default: Groq free tier, Gemini free tier as fallback.
    llm_provider: str = "groq"
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    judge_model: str = "openai/gpt-oss-120b"
    draft_model: str = "llama-3.1-8b-instant"
    llm_fallback_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_fallback_api_key: str = ""
    llm_fallback_model: str = "gemini-flash-latest"

    cors_origins: str = "http://localhost:3000"   # comma-separated web origins allowed to call the API
    session_secret: str = ""                  # signs login sessions; scripts/gen_secrets.py
    inline_worker: bool = False               # `make local`: grade + pay in-process, no Redis
    dev_auth: bool = True                     # X-User-Id header login; never with live
    sandbox_backend: str = "e2b"
    e2b_api_key: str = ""
    sandbox_test_timeout_ms: int = 2000
    sandbox_memory_mb: int = 512

    database_url: str = "postgresql+psycopg://verdict:verdict@localhost:5432/verdict"
    redis_url: str = "redis://localhost:6379/0"

    blob_dir: str = "data/blobs"               # LocalBlobStore root (git-ignored)
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
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

    @property
    def paypal_web_url(self) -> str:
        return "https://www.paypal.com" if self.paypal_env == "live" else "https://www.sandbox.paypal.com"

    @property
    def paypal_base_url(self) -> str:
        if self.paypal_env not in PAYPAL_BASE_URLS:
            raise ValueError("PAYPAL_ENV must be 'sandbox' or 'live'")
        return PAYPAL_BASE_URLS[self.paypal_env]


@lru_cache
def get_settings() -> Settings:
    return Settings()
