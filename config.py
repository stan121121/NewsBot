"""
config.py — настройки из переменных окружения
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Telegram Bot Token
    BOT_TOKEN: str

    # OpenRouter API Key — https://openrouter.ai/keys
    OPENROUTER_API_KEY: str

    # Модель OpenRouter
    OPENROUTER_MODEL: str = "liquid/lfm-2.5-1.2b-instruct:free"

    # Интервал между дайджестами (часы)
    DEFAULT_DIGEST_INTERVAL_HOURS: int = 5

    # Постов с каждого канала
    POSTS_PER_CHANNEL: int = 25

    # Максимум новостей в дайджесте
    MAX_NEWS_IN_DIGEST: int = 25

    # Язык дайджеста (ru / en)
    DIGEST_LANGUAGE: str = "ru"

    # SQLite файл
    DB_PATH: str = "bot_data.db"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
