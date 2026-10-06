import os

from dotenv import load_dotenv

load_dotenv()


# =========================
# Telegram
# =========================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    "",
).strip()


# =========================
# IGDB / Twitch
# =========================

TWITCH_CLIENT_ID = os.getenv(
    "TWITCH_CLIENT_ID",
    "",
).strip()

TWITCH_CLIENT_SECRET = os.getenv(
    "TWITCH_CLIENT_SECRET",
    "",
).strip()

IGDB_BASE_URL = "https://api.igdb.com/v4"

TWITCH_TOKEN_URL = (
    "https://id.twitch.tv/oauth2/token"
)


# =========================
# Qwen / OpenRouter
# =========================

QWEN_API_KEY = os.getenv(
    "QWEN_API_KEY",
    "",
).strip()

QWEN_BASE_URL = os.getenv(
    "QWEN_BASE_URL",
    "https://openrouter.ai/api/v1",
).strip()

QWEN_MODEL = os.getenv(
    "QWEN_MODEL",
    "openrouter/free",
).strip()


# =========================
# Database
# =========================

DATABASE_PATH = os.getenv(
    "DATABASE_PATH",
    "data/games.db",
).strip()


# =========================
# HTTP
# =========================

REQUEST_TIMEOUT = int(
    os.getenv(
        "REQUEST_TIMEOUT",
        "20",
    )
)