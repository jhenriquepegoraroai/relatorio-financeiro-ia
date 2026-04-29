from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).parent / ".env"


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"
    max_tokens_resumo: int = 16384
    max_tokens_chat: int = 400

    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_ignore_empty=True, extra="ignore")


settings = Settings()
