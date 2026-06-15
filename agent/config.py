from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Anthropic
    anthropic_api_key: str
    anthropic_model: str = "claude-sonnet-4-6"

    # Supabase — REST only (porta 5432 não exposta externamente)
    supabase_url: str
    supabase_anon_key: str = ""
    supabase_service_role_key: str

    # Meta Ads
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_access_token: str = ""
    meta_ad_account_id: str = ""
    meta_api_version: str = "v21.0"

    # Google Ads
    google_ads_developer_token: str = ""
    google_ads_client_id: str = ""
    google_ads_client_secret: str = ""
    google_ads_refresh_token: str = ""
    google_ads_customer_id: str = ""
    google_ads_login_customer_id: str = ""
    # Read-only: quando true, o agente apenas loga ações Google sem executá-las na API.
    google_ads_read_only: bool = True

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_secret_key: str
    api_allowed_origins: str = "http://localhost:3000"

    environment: str = "development"
    debug: bool = True

    # Brevo (email marketing)
    brevo_api_key: str = ""
    brevo_api_base_url: str = "https://api.brevo.com/v3"

    # Agent
    agent_cycle_interval_minutes: int = 30
    agent_max_daily_spend_usd: float = 500.0
    agent_max_budget_change_pct: float = 20.0
    agent_autonomous_mode: bool = False

    # Notificações humanas — n8n / WhatsApp
    n8n_webhook_url: str = ""          # URL do webhook n8n (POST com payload de decisão)
    notify_phone_number: str = ""      # Número WhatsApp no formato E.164 (ex: 5511999998888)


settings = Settings()  # type: ignore[call-arg]
