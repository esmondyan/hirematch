from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    llm_provider: str = "deepseek"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    dashscope_api_key: str = ""
    openai_api_key: str = ""
    match_threshold: int = 60
    max_upload_size_mb: int = 5
    database_url: str = "sqlite:///./data/hirematch.db"
    session_secret_key: str = "hirematch-dev-secret-change-in-production"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
