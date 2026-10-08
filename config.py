import os

from dotenv import load_dotenv

load_dotenv()


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

# Optional AI provider. The bot works without these values.
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "").strip()
QWEN_BASE_URL = os.getenv(
    "QWEN_BASE_URL",
    "https://openrouter.ai/api/v1",
).strip()
QWEN_MODEL = os.getenv(
    "QWEN_MODEL",
    "openrouter/free",
).strip()

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/games.db").strip()
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
