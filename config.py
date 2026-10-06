import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

QWEN_API_KEY = os.getenv("QWEN_API_KEY")

QWEN_BASE_URL = os.getenv(
    "QWEN_BASE_URL",
    "https://openrouter.ai/api/v1",
)

QWEN_MODEL = os.getenv(
    "QWEN_MODEL",
    "openrouter/free",
)

DATABASE_PATH = "/tmp/games.db"