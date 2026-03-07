"""
config.py — настройки из переменных окружения
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Telegram Bot Token (получить у @BotFather)
    BOT_TOKEN: str

    # OpenRouter API Key
    # https://openrouter.ai/keys
    OPENROUTER_API_KEY: str

    # Модель на OpenRouter (можно менять без изменения кода)
    # Примеры: "anthropic/claude-3.5-sonnet", "google/gemini-flash-1.5",
    #          "meta-llama/llama-3.1-70b-instruct", "openai/gpt-4o-mini"
    OPENROUTER_MODEL: str = "anthropic/claude-3.5-sonnet"

    # Telethon — для чтения публичных каналов
    # Получить на https://my.telegram.org/apps
    TELEGRAM_API_ID: int
    TELEGRAM_API_HASH: str
    TELEGRAM_SESSION_STRING: str = ""  # Заполняется после авторизации

    # Сколько часов между дайджестами (по умолчанию)
    DEFAULT_DIGEST_INTERVAL_HOURS: int = 4

    # Сколько последних постов брать с каждого канала
    POSTS_PER_CHANNEL: int = 20

    # Максимум новостей в дайджесте
    MAX_NEWS_IN_DIGEST: int = 10

    # Язык дайджеста (ru / en)
    DIGEST_LANGUAGE: str = "ru"

    # SQLite файл
    DB_PATH: str = "bot_data.db"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
