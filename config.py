from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).parent / ".env"


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"           # resumo executivo
    claude_model_chat: str = "claude-haiku-4-5-20251001"  # chat interativo
    max_tokens_resumo: int = 16384
    max_tokens_chat: int = 2048

    # Comparativo multi-provider
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-pro"

    # Databricks
    databricks_host: str = ""
    databricks_token: str = ""
    databricks_cluster_id: str = ""
    databricks_catalog: str = "hive_metastore"
    databricks_schema: str = "default"

    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_ignore_empty=True, extra="ignore")


settings = Settings()
