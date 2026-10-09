
import asyncio
import logging
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import database
from agent import GameAgent
from game_service import GameService
from tools import escape_html, truncate
from database import DB_PATH, count_games


# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

game_service = GameService()
game_agent = GameAgent()

PAGE_SIZE = 5

# Force users to join this public channel before using the bot.
FORCE_SUBSCRIPTION_CHANNEL = "@Apex_App_ir"
FORCE_SUBSCRIPTION_URL = "https://t.me/Apex_App_ir"


# ============================================================
# UI helpers
# ============================================================

def main_menu():
    keyboard = [
        [
            InlineKeyboardButton("🔎 جست‌وجوی بازی", callback_data="search"),
            InlineKeyboardButton("🔥 محبوب‌ها", callback_data="popular"),
        ],
        [
            InlineKeyboardButton("🎲 بازی‌های پیشنهادی", callback_data="discover"),
            InlineKeyboardButton("📅 بازی‌های آینده", callback_data="upcoming"),
        ],
        [
            InlineKeyboardButton("📆 بر اساس سال", callback_data="years"),
            InlineKeyboardButton("💻 بر اساس پلتفرم", callback_data="platforms"),
        ],
        [
            InlineKeyboardButton("🎭 بر اساس ژانر", callback_data="genres"),
            InlineKeyboardButton("❤️ علاقه‌مندی‌ها", callback_data="favorites"),
        ],
        [InlineKeyboardButton("👤 پروفایل من", callback_data="profile")],
    ]
    return InlineKeyboardMarkup(keyboard)



def _safe(value, fallback="نامشخص"):
    value = str(value or "").strip()
    return escape_html(value) if value else fallback


def _game_button_text(name: str) -> str:
    return f"🎮 {str(name or 'بازی')[:40]}"


def _display_genre(value: str) -> str:
    """Normalize Persian genre spelling for display without changing database values."""
    label = str(value or "").strip()
    display_labels = {
        "نقش آفرینی": "نقش‌آفرینی",
        "مخفی کاری": "مخفی‌کاری",
        "شبیه سازی": "شبیه‌سازی",
        "علمی تخیلی": "علمی‌تخیلی",
        "جهان باز": "جهان‌باز",
        "چندنفره آنلاین": "چندنفرهٔ آنلاین",
        "اکشن ماجراجویی": "اکشن ماجراجویی",
    }
    return display_labels.get(label, label)


# Telegram message IDs belonging to the currently displayed bot screen.
# The key is chat_id; messages sent as release notifications are intentionally
# not tracked, because they are notifications rather than screen content.
_UI_MESSAGES_BY_CHAT: dict[int, list[int]] = {}


def _remember_ui_message(message):
    """Remember a bot message so it can be deleted on the next screen change."""
    try:
        chat_id = int(message.chat_id)
        message_id = int(message.message_id)
    except (AttributeError, TypeError, ValueError):
        return

    ids = _UI_MESSAGES_BY_CHAT.setdefault(chat_id, [])
    if message_id not in ids:
        ids.append(message_id)


def _forget_ui_message(message):
    """Forget a UI message that has already been deleted manually."""
    try:
        chat_id = int(message.chat_id)
        message_id = int(message.message_id)
    except (AttributeError, TypeError, ValueError):
        return

    ids = _UI_MESSAGES_BY_CHAT.get(chat_id, [])
    if message_id in ids:
        ids.remove(message_id)
    if not ids:
        _UI_MESSAGES_BY_CHAT.pop(chat_id, None)


async def _clear_screen(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Delete all previously tracked UI messages in a chat."""
    chat_id = int(chat_id)
    message_ids = _UI_MESSAGES_BY_CHAT.pop(chat_id, [])

    for message_id in message_ids:
        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=message_id,
            )
        except TelegramError:
            # A message may already have been deleted or become inaccessible.
            pass
        except Exception:
            logger.debug(
                "Could not clear UI message %s in chat %s",
                message_id,
                chat_id,
                exc_info=True,
            )


async def _send_ui_text(message, context, text, **kwargs):
    """Send and track a bot UI text message without replying to an old message."""
    sent = await context.bot.send_message(
        chat_id=message.chat_id,
        text=text,
        **kwargs,
    )
    _remember_ui_message(sent)
    return sent


async def _send_ui_photo(message, context, photo, **kwargs):
    """Send and track a bot UI photo message."""
    sent = await context.bot.send_photo(
        chat_id=message.chat_id,
        photo=photo,
        **kwargs,
    )
    _remember_ui_message(sent)
    return sent


async def _send_error(message, text="❌ خطایی رخ داد."):
    try:

        sent = await message.get_bot().send_message(
            chat_id=message.chat_id,
            text=text,
        )
        _remember_ui_message(sent)
    except Exception:
        logger.exception("Could not send error message")


async def _check_channel_membership(context, user_id: int) -> bool | None:
    """Return True/False for channel membership, or None if Telegram check failed."""
    try:
        member = await context.bot.get_chat_member(
            chat_id=FORCE_SUBSCRIPTION_CHANNEL,
            user_id=user_id,
        )
        status = str(member.status).casefold()
        return status in {"creator", "administrator", "member"} or (
            status == "restricted" and bool(getattr(member, "is_member", False))
        )
    except TelegramError:
        logger.exception(
            "Could not verify channel membership for user_id=%s; "
            "check that the bot is an administrator of %s",
            user_id,
            FORCE_SUBSCRIPTION_CHANNEL,
        )
        return None


async def _show_subscription_prompt(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    check_unavailable: bool = False,
):
    """Replace the current bot screen with the channel-membership prompt."""
    await _clear_screen(context, message.chat_id)

    if check_unavailable:
        text = (
            "⚠️ <b>بررسی عضویت فعلاً ممکن نیست.</b>\n\n"
            "لطفاً کمی بعد دوباره تلاش کن. اگر این مشکل ادامه داشت، مطمئن شو "
            "ربات در کانال ادمین است و اجازهٔ مشاهدهٔ اعضا را دارد."
        )
    else:
        text = (
            "🔒 <b>برای استفاده از GLADIATOR GAMES ابتدا عضو کانال شو.</b>\n\n"
            "بعد از عضویت، روی دکمهٔ «بررسی عضویت» بزن تا منوی ربات باز شود."
        )

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 عضویت در کانال", url=FORCE_SUBSCRIPTION_URL)],
        [InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_subscription")],
    ])
    await _send_ui_text(
        message,
        context,
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


# ============================================================
# Start / Search
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message

    logger.info(
        "🔥 START RECEIVED | user_id=%s",
        user.id if user else None,
    )

    if not user or not message:
        logger.error("START failed: user or message is missing")
        return

    membership = await _check_channel_membership(context, user.id)
    if membership is not True:
        await _show_subscription_prompt(
            message,
            context,
            check_unavailable=membership is None,
        )
        return

    await _clear_screen(context, message.chat_id)

    # Step 1: Save user
    try:
        database.add_user(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
        )

        logger.info(
            "✅ User saved to database | user_id=%s",
            user.id,
        )

    except Exception:
        logger.exception("❌ DATABASE ERROR in start")

        await _send_error(
            message,
            "❌ هنگام ثبت اطلاعات کاربر خطایی رخ داد. لطفاً دوباره تلاش کنید.",
        )
        return

    # Step 2: Send welcome message
    try:
        text = (
            "🎮 <b>GameRadarBot</b>\n\n"
            f"سلام {_safe(user.first_name, 'گیمر')} 🎮 خوش اومدی!\n\n"
"اینجا می‌تونی بازی‌های جدید رو کشف کنی، محبوب‌ترین‌ها رو بشناسی و از زمان انتشار بازی‌های موردعلاقه‌ات باخبر بشی. 🔥\n\n"
"خب، بریم ببینیم چی بازی کنیم؟ 👀"


        )

        await _send_ui_text(message, context, 
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )

        logger.info(
            "✅ START RESPONSE SENT | user_id=%s",
            user.id,
        )

    except Exception:
        logger.exception("❌ TELEGRAM REPLY ERROR in start")
        raise

    
async def start_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    context.user_data["waiting_for_search"] = True

    await _send_ui_text(
        query.message,
        context,
        "🔎 لطفاً نام بازی موردنظرتان را وارد کنید.\n\n"
        "برای جست‌وجوی دقیق‌تر، نام بازی را به انگلیسی بنویسید. "
        "همچنین می‌توانید بخشی از نام بازی را وارد کنید.\n\n"
        "🎮 منتظر نام بازی شما هستیم.",
        parse_mode=ParseMode.HTML,
    )







async def handle_search_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    user = update.effective_user
    if not message or not message.text or not user:
        return

    membership = await _check_channel_membership(context, user.id)
    if membership is not True:
        await _show_subscription_prompt(
            message,
            context,
            check_unavailable=membership is None,
        )
        return

    # A new search is a new screen: remove the previous list/profile/menu.
    await _clear_screen(context, message.chat_id)

    context.user_data["waiting_for_search"] = False
    search_text = message.text.strip()
    if not search_text:
        await _send_ui_text(message, context, "❌ عبارت جست‌وجو نمی‌تواند خالی باشد.")
        return

    status = await _send_ui_text(message, context, "🔎 در حال جست‌وجوی بازی در پایگاه داده و منابع آنلاین...")
    try:
        games = await asyncio.to_thread(
            game_service.search_games,
            search_text,
            page_size=100,
        )
    except Exception:
        logger.exception("Game search failed")
        await _send_error(message, "❌ جست‌وجو با خطا مواجه شد. لطفاً دوباره تلاش کنید.")
        return

    try:
        await status.delete()
        _forget_ui_message(status)
    except Exception:
        pass

    if games:
        await send_game_list(
            message,
            context,
            games,
            title=f"🔎 نتایج جست‌وجو برای: {search_text}",
            telegram_id=getattr(update.effective_user, "id", None),
        )
        return

    # If this is a general game-related question and an AI key is configured,
    # answer it instead of silently showing an empty list.
    answer = None
    try:
        if getattr(game_agent, "enabled", False) and hasattr(game_agent, "answer_question"):
            answer = await asyncio.to_thread(game_agent.answer_question, search_text)
    except Exception:
        logger.exception("AI game-question fallback failed")

    if answer:
        await _send_ui_text(message, context, "🤖 <b>پاسخ GameRadarBot</b>\n\n" + escape_html(answer), parse_mode=ParseMode.HTML)
    else:
        await _send_ui_text(message, context, 
            "❌ بازی مرتبطی پیدا نشد.\n\n"
            "نام بازی را فارسی یا انگلیسی بنویس؛ همچنین می‌توانید سبک‌هایی مثل «بازی ترسناک»، "
            "«بازی جهان‌باز»، «بازی‌های ۲۰۲۴» یا «بازی شبیه GTA» را جست‌وجو کنید.\n\n"
            "اگر بازی در منابع آنلاین یافت نشود و در پایگاه دادهٔ محلی نیز ثبت نشده باشد، اطلاعات تأییدشده‌ای برای نمایش در دسترس نیست."
        )



# ============================================================
# Game lists
# ============================================================

async def show_popular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        games = await asyncio.to_thread(game_service.get_popular_games, page_size=100)
        await send_game_list(query.message, context, games, "🔥 بازی‌های محبوب", telegram_id=query.from_user.id)
    except Exception:
        logger.exception("Popular games error")
        await _send_error(query.message, "❌ دریافت بازی‌های محبوب با خطا مواجه شد.")



async def show_discover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        games = await asyncio.to_thread(game_service.get_games, page_size=100)
        await send_game_list(query.message, context, games, "🎮 بازی‌های پیشنهادی", telegram_id=query.from_user.id)
    except Exception:
        logger.exception("Discover error")
        await _send_error(query.message, "❌ دریافت بازی‌های پیشنهادی با خطا مواجه شد.")



async def show_upcoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        games = await asyncio.to_thread(game_service.get_upcoming_games, page_size=100)
        if not games:
            await _send_ui_text(query.message, context, "📅 در حال حاضر، بازی آینده‌ای با تاریخ انتشار معتبر در پایگاه داده ثبت نشده است.")
            return
        await send_game_list(query.message, context, games, "📅 بازی‌های آینده", telegram_id=query.from_user.id)
    except Exception:
        logger.exception("Upcoming games error")
        await _send_error(query.message, "❌ دریافت بازی‌های آینده با خطا مواجه شد.")



async def show_years(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    try:
        years = game_service.get_available_years()

        if not years:
            await _send_ui_text(query.message, context, 
                "📆 هنوز سالی در پایگاه داده ثبت نشده است."
            )
            return

        keyboard = [
            [
                InlineKeyboardButton(
                    str(year), callback_data=f"year:{year}"
                )
                for year in years[i:i + 3]
            ]
            for i in range(0, len(years), 3)
        ]

        keyboard.append([
            InlineKeyboardButton("⬅️ بازگشت", callback_data="back")
        ])

        await _send_ui_text(query.message, context, 
            "📆 سال انتشار را انتخاب کن:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    except Exception:
        logger.exception("Years error")
        await _send_error(query.message, "❌ دریافت سال‌ها ناموفق بود.")


PLATFORM_LABELS = {
    "Windows": "🖥️ PC / Windows",
    "Android": "📱 Android",
    "iOS": "🍎 iOS",
    "macOS": "🖥️ macOS",
    "Linux": "🐧 Linux",
    "PlayStation": "🎮 PlayStation",
    "Xbox": "🎮 Xbox",
    "Nintendo": "🕹️ Nintendo",
}


def platform_label(platform: str) -> str:
    return PLATFORM_LABELS.get(platform, f"💻 {platform}")


async def show_genres(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    genres = await asyncio.to_thread(game_service.get_available_genres)
    if not genres:
        # Try to seed the local database from the public catalog first.
        await asyncio.to_thread(game_service.get_games, page_size=30)
        genres = await asyncio.to_thread(game_service.get_available_genres)

    if not genres:
        await _send_ui_text(query.message, context, "🎭 هنوز ژانری در پایگاه داده پیدا نشد. اتصال اینترنت را بررسی کنید و دوباره تلاش کنید.")
        return

    context.user_data["genre_menu_options"] = genres
    keyboard = []
    for index in range(0, len(genres), 2):
        row = [
            InlineKeyboardButton(f"🎭 {_display_genre(genre)}", callback_data=f"genre:{index + offset}")
            for offset, genre in enumerate(genres[index:index + 2])
        ]
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="back")])
    await _send_ui_text(query.message, context, "🎭 سبک بازی را انتخاب کن:", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_genre_games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        index = int((query.data or "").split(":", 1)[1])
        genres = context.user_data.get("genre_menu_options", [])
        genre = genres[index]
    except (ValueError, IndexError, TypeError):
        await _send_ui_text(query.message, context, "این گزینه دیگر معتبر نیست. بخش ژانرها را دوباره باز کنید.")
        return

    try:
        games = await asyncio.to_thread(game_service.get_games_by_genre, genre, page_size=100)
        await send_game_list(
            query.message,
            context,
            games,
            title=f"🎭 بازی‌های ژانر {genre}",
            telegram_id=query.from_user.id,
        )
    except Exception:
        logger.exception("Genre filter failed")
        await _send_error(query.message, "❌ دریافت بازی‌های این ژانر ناموفق بود.")

async def show_platforms(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    try:
        platforms = game_service.get_available_platforms()

        if not platforms:
            await _send_ui_text(query.message, context, 
                "💻 هنوز پلتفرمی در پایگاه داده ثبت نشده است."
            )
            return

        keyboard = [
            [
                InlineKeyboardButton(
                    platform_label(platform),
                    callback_data=f"platform:{platform}",
                )
                for platform in platforms[i:i + 2]
            ]
            for i in range(0, len(platforms), 2)
        ]

        keyboard.append([
            InlineKeyboardButton("⬅️ بازگشت", callback_data="back")
        ])

        await _send_ui_text(query.message, context, 
            "💻 پلتفرم را انتخاب کن:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    except Exception:
        logger.exception("Platforms error")
        await _send_error(query.message, "❌ دریافت پلتفرم‌ها ناموفق بود.")


async def show_year_games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        year = int((query.data or "").split(":", 1)[1])
        games = await asyncio.to_thread(game_service.get_games_by_year, year, page_size=100)
        await send_game_list(query.message, context, games, f"📆 بازی‌های سال {year}", telegram_id=query.from_user.id)
    except (ValueError, IndexError):
        await _send_ui_text(query.message, context, "❌ سال انتخاب‌شده معتبر نیست.")
    except Exception:
        logger.exception("Year filter error")
        await _send_error(query.message, "❌ دریافت بازی‌های این سال با خطا مواجه شد.")



async def show_platform_games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    platform = (query.data or "").split(":", 1)[1]
    try:
        games = await asyncio.to_thread(game_service.get_games_by_platform, platform, page_size=100)
        await send_game_list(query.message, context, games, platform_label(platform), telegram_id=query.from_user.id)
    except Exception:
        logger.exception("Platform filter error")
        await _send_error(query.message, "❌ دریافت بازی‌های این پلتفرم با خطا مواجه شد.")



async def send_game_list(
    message,
    context,
    games,
    title="🎮 بازی‌ها",
    page=0,
    telegram_id=None,
):
    """Send each title in its own photo/detail message, plus pagination."""
    games = games or []

    if page == 0:
        context.user_data["last_list_ids"] = [
            int(game["id"]) for game in games
            if isinstance(game, dict) and game.get("id") is not None
        ]
        context.user_data["last_list_title"] = title

    all_ids = context.user_data.get("last_list_ids", [])
    if not all_ids:
        await _send_ui_text(message, context, f"{title}\n\n❌ بازی‌ای پیدا نشد.")
        return

    page_size = 5
    start_index = page * page_size
    ids = all_ids[start_index:start_index + page_size]
    if not ids:
        await _send_ui_text(message, context, "❌ این صفحه وجود ندارد.")
        return

    page_games = []
    for game_id in ids:
        game = await asyncio.to_thread(game_service.get_game_details, game_id)
        if game:
            page_games.append(game)

    if not page_games:
        await _send_ui_text(message, context, "❌ اطلاعات بازی‌ها پیدا نشد.")
        return

    if telegram_id is None:
        # In a private chat, chat_id equals the Telegram user ID.
        telegram_id = getattr(message, "chat_id", None)

    await _send_ui_text(message, context, 
        f"<b>{escape_html(title)}</b>\n"
        f"تعداد بازی‌های این فهرست: {len(all_ids)}\n"
        "هر بازی در پیام جداگانه با تصویر و مشخصات نمایش داده می‌شود.",
        parse_mode=ParseMode.HTML,
    )

    for game in page_games:
        try:
            await send_game_details(message, game, int(telegram_id or 0), context=context)
        except Exception:
            logger.exception("Could not send game details for %s", game.get("name"))
            await _send_error(message, f"نمایش بازی {escape_html(game.get('name') or '')} ناموفق بود.")

    page_count = (len(all_ids) + page_size - 1) // page_size
    navigation = []
    if page > 0:
        navigation.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"list:{page - 1}"))
    if start_index + page_size < len(all_ids):
        navigation.append(InlineKeyboardButton("➡️ بعدی", callback_data=f"list:{page + 1}"))

    keyboard = []
    if navigation:
        keyboard.append(navigation)
    keyboard.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="back")])
    await _send_ui_text(message, context, 
        f"صفحه {page + 1} از {page_count}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )



async def show_list_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        page = int((query.data or "").split(":", 1)[1])
    except (ValueError, IndexError):
        await _send_ui_text(query.message, context, "❌ شماره صفحه معتبر نیست.")
        return
    title = context.user_data.get("last_list_title", "🎮 بازی‌ها")
    await send_game_list(
        query.message,
        context,
        [],
        title=title,
        page=page,
        telegram_id=query.from_user.id,
    )



# ============================================================
# Game details and actions
# ============================================================

async def show_game_details(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    try:
        game_id = query.data.split(":", 1)[1]
        game = game_service.get_game_details(game_id)

        if not game:
            await _send_ui_text(query.message, context, "❌ اطلاعات بازی پیدا نشد.")
            return

        await send_game_details(query.message, game, query.from_user.id, context=context)

    except Exception:
        logger.exception("Game details error")
        await _send_error(query.message, "❌ دریافت جزئیات بازی ناموفق بود.")


async def send_game_details(
    message,
    game,
    telegram_id,
    context=None,
    edit_existing=False,
):
    game_id = int(game["id"])
    name = game.get("name") or game.get("title") or "بازی نامشخص"
    summary = truncate(
        game.get("description") or game.get("summary") or "برای این بازی توضیحی ثبت نشده است.",
        450,
    )
    release_date = game.get("release_date") or "نامشخص"
    rating = game.get("rating")
    rating_text = str(rating) if rating is not None else "در این منبع موجود نیست"
    genres = game_service.get_genres(game)
    platforms = game_service.get_platforms(game)
    developer = game_service.get_developer(game)
    publisher = game_service.get_publisher(game)
    cover_url = game_service.get_cover_url(game)
    game_url = game_service.get_game_url(game)

    text = (
        f"🎮 <b>{escape_html(name)}</b>\n\n"
        f"📝 {escape_html(summary)}\n\n"
        f"📅 <b>انتشار:</b> {_safe(release_date)}\n"
        f"⭐ <b>امتیاز:</b> {_safe(rating_text)}\n"
        f"🎭 <b>ژانر:</b> {escape_html('، '.join(_display_genre(g) for g in genres)) if genres else 'نامشخص'}\n"
        f"💻 <b>پلتفرم:</b> {escape_html('، '.join(platforms)) if platforms else 'نامشخص'}\n"
        f"👨‍💻 <b>سازنده:</b> {_safe(developer)}\n"
        f"🏢 <b>ناشر:</b> {_safe(publisher)}"
    )

    favorite = database.is_favorite(telegram_id, game_id)
    following = database.is_following(telegram_id, game_id)
    keyboard = [
        [InlineKeyboardButton(
            "💔 حذف از علاقه‌مندی‌ها" if favorite else "❤️ افزودن به علاقه‌مندی‌ها",
            callback_data=f"favorite_remove:{game_id}" if favorite else f"favorite_add:{game_id}",
        )],
        [InlineKeyboardButton(
            "🔕 لغو دنبال‌کردن" if following else "🔔 دنبال‌کردن انتشار",
            callback_data=f"follow_remove:{game_id}" if following else f"follow_add:{game_id}",
        )],
        [InlineKeyboardButton("🤖 توضیح با هوش مصنوعی", callback_data=f"ai:{game_id}")],
    ]
    if game_url:
        source_label = "Steam" if str(game.get("source") or "").casefold() == "steam" else "GameUP"
        keyboard.insert(2, [InlineKeyboardButton(f"🔗 صفحه بازی در {source_label}", url=game_url)])
    keyboard.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="back")])
    markup = InlineKeyboardMarkup(keyboard)

    # Favourite/follow actions update this card in place instead of creating
    # another message in the chat.
    if edit_existing and context is not None:
        try:
            if getattr(message, "photo", None):
                await context.bot.edit_message_caption(
                    chat_id=message.chat_id,
                    message_id=message.message_id,
                    caption=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
            else:
                await context.bot.edit_message_text(
                    chat_id=message.chat_id,
                    message_id=message.message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
            return
        except TelegramError:
            logger.warning(
                "Could not edit game card in place; sending a replacement",
                exc_info=True,
            )

    if cover_url:
        try:
            if context is not None:
                await _send_ui_photo(
                    message,
                    context,
                    photo=cover_url,
                    caption=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
            else:
                sent = await message.reply_photo(
                    photo=cover_url,
                    caption=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
                _remember_ui_message(sent)
            return
        except Exception as exc:
            logger.warning("Could not send game cover for %s: %s", name, exc)

    if context is not None:
        await _send_ui_text(
            message,
            context,
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    else:
        sent = await message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        _remember_ui_message(sent)


async def refresh_game_details(query, game, context):
    await send_game_details(
        query.message,
        game,
        query.from_user.id,
        context=context,
        edit_existing=True,
    )


async def add_favorite(update, context):
    query = update.callback_query
    await query.answer()

    try:
        game_id = int(query.data.split(":", 1)[1])
        game = game_service.get_game_details(game_id)

        if not game:
            await _send_ui_text(query.message, context, "❌ بازی پیدا نشد.")
            return

        database.add_favorite(
            query.from_user.id, game_id, game.get("name")
        )
        await refresh_game_details(query, game, context)

    except Exception:
        logger.exception("Add favorite error")
        await _send_error(query.message, "❌ افزودن علاقه‌مندی ناموفق بود.")


async def remove_favorite(update, context):
    query = update.callback_query
    await query.answer()

    try:
        game_id = int(query.data.split(":", 1)[1])
        database.remove_favorite(query.from_user.id, game_id)

        game = game_service.get_game_details(game_id)
        if game:
            await refresh_game_details(query, game, context)

    except Exception:
        logger.exception("Remove favorite error")
        await _send_error(query.message, "❌ حذف علاقه‌مندی ناموفق بود.")


async def add_follow(update, context):
    query = update.callback_query
    await query.answer()

    try:
        game_id = int(query.data.split(":", 1)[1])
        game = game_service.get_game_details(game_id)

        if not game:
            await _send_ui_text(query.message, context, "❌ بازی پیدا نشد.")
            return

        database.follow_game(
            query.from_user.id,
            game_id,
            game_name=game.get("name"),
            release_date=game.get("release_date"),
        )
        await refresh_game_details(query, game, context)

    except Exception:
        logger.exception("Follow game error")
        await _send_error(query.message, "❌ دنبال‌کردن بازی ناموفق بود.")


async def remove_follow(update, context):
    query = update.callback_query
    await query.answer()

    try:
        game_id = int(query.data.split(":", 1)[1])
        database.unfollow_game(query.from_user.id, game_id)

        game = game_service.get_game_details(game_id)
        if game:
            await refresh_game_details(query, game, context)

    except Exception:
        logger.exception("Unfollow game error")
        await _send_error(query.message, "❌ لغو دنبال‌کردن ناموفق بود.")


async def show_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    favorites = database.get_favorites(query.from_user.id)
    if not favorites:
        await _send_ui_text(query.message, context, "❤️ هنوز هیچ بازی‌ای به علاقه‌مندی‌ها اضافه نکرده‌ای.")
        return
    await send_game_list(
        query.message,
        context,
        favorites,
        title="❤️ بازی‌های موردعلاقه",
        telegram_id=query.from_user.id,
    )



async def ai_description(update, context):
    query = update.callback_query
    await query.answer("🤖 در حال تولید توضیحات...")

    try:
        game_id = int(query.data.split(":", 1)[1])
        game = game_service.get_game_details(game_id)

        if not game:
            await _send_ui_text(query.message, context, "❌ بازی پیدا نشد.")
            return

        description = game_agent.describe_game(
            title=game.get("name", "Unknown"),
            genre=game_service.get_genres(game),
            description=game.get("description") or game.get("summary") or "",
            platforms=game_service.get_platforms(game),
        )

        await _send_ui_text(
            query.message,
            context,
            "🤖 <b>معرفی هوشمند بازی</b>\n\n" + escape_html(description),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 منوی اصلی", callback_data="back")]
            ]),
        )

    except Exception:
        logger.exception("AI description error")
        await _send_error(
            query.message,
            "❌ تولید توضیح با هوش مصنوعی انجام نشد.",
        )


# ============================================================
# Callback routing
# ============================================================

async def back_to_menu(update, context):
    query = update.callback_query
    await query.answer()

    await _send_ui_text(query.message, context, 
        "🏠 منوی اصلی:",
        reply_markup=main_menu(),
    )

    
async def show_profile(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    try:
        await query.answer()
    except TelegramError:
        logger.debug("Profile callback was already answered.")

    user = query.from_user

    try:
        # Save the current Telegram user's information.
        database.add_user(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
        )

        favorites = database.get_favorites(user.id)

        followed = [
            item
            for item in database.get_followed_games()
            if int(item.get("telegram_id", -1)) == user.id
        ]

    except Exception:
        logger.exception("Profile database error")
        await _send_error(
            query.message,
            "❌ دریافت اطلاعات پروفایل ناموفق بود.",
        )
        return

    # Show up to three examples in the profile card.
    favorite_names = "\n".join(
        f"• {escape_html(str(game.get('name') or 'بازی')[:40])}"
        for game in favorites[:3]
    ) or "هنوز بازی‌ای به فهرست علاقه‌مندی‌ها اضافه نشده است."

    followed_names = "\n".join(
        f"• {escape_html(str(item.get('game_name') or 'بازی')[:40])}"
        for item in followed[:3]
    ) or "هنوز بازی‌ای برای پیگیری انتخاب نشده است."

    username = (
        f"@{user.username}"
        if user.username
        else "تنظیم نشده"
    )

    profile_text = (
        "🎮 <b>پروفایل گیمر</b>\n\n"
        f"👤 <b>نام:</b> {escape_html(user.full_name or 'گیمر')}\n"
        f"🔗 <b>نام کاربری:</b> {escape_html(username)}\n\n"
        "━━━━━━━━━━━━━━\n"
        "📊 <b>آمار گیمینگ</b>\n\n"
        f"❤️ <b>بازی‌های موردعلاقه:</b> {len(favorites)}\n"
        f"🔔 <b>بازی‌های دنبال‌شده:</b> {len(followed)}\n\n"
        "❤️ <b>علاقه‌مندی‌های اخیر</b>\n"
        f"{favorite_names}\n\n"
        "🔔 <b>بازی‌های دنبال‌شده</b>\n"
        f"{followed_names}"
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "❤️ همه‌ی علاقه‌مندی‌ها",
                callback_data="favorites",
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="back",
            )
        ],
    ]

    markup = InlineKeyboardMarkup(keyboard)

    # Get the user's current Telegram profile picture.
    photo_file_id = None

    try:
        photos = await context.bot.get_user_profile_photos(
            user_id=user.id,
            limit=1,
        )

        if photos.total_count > 0 and photos.photos:
            photo_file_id = photos.photos[0][-1].file_id

    except TelegramError:
        logger.exception(
            "Could not retrieve Telegram profile photo for user_id=%s",
            user.id,
        )

    # Display the profile picture if available.
    try:
        if photo_file_id:
            await _send_ui_photo(query.message, context, 
                photo=photo_file_id,
                caption=profile_text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
        else:
            await _send_ui_text(query.message, context, 
                profile_text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )

    except TelegramError:
        logger.exception("Could not send profile photo; using text fallback")

        await _send_ui_text(query.message, context, 
            profile_text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )





# ============================================================
# Callback routing
# ============================================================

async def callback_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Route inline keyboard callbacks to the appropriate handler."""
    query = update.callback_query
    if query is None:
        return

    data = (query.data or "").strip()

    # Subscription callbacks must be handled before the general membership gate.
    if data == "check_subscription":
        try:
            await query.answer("در حال بررسی عضویت...")
        except TelegramError:
            pass

        membership = await _check_channel_membership(
            context,
            query.from_user.id,
        )
        if membership is True:
            # start() performs the regular registration and opens the main menu.
            await start(update, context)
        else:
            await _show_subscription_prompt(
                query.message,
                context,
                check_unavailable=membership is None,
            )
        return

    membership = await _check_channel_membership(
        context,
        query.from_user.id,
    )
    if membership is not True:
        try:
            await query.answer(
                "ابتدا عضو کانال شو و سپس عضویتت را بررسی کن.",
                show_alert=True,
            )
        except TelegramError:
            pass
        await _show_subscription_prompt(
            query.message,
            context,
            check_unavailable=membership is None,
        )
        return

    # Navigation changes the screen: remove the whole previous page first.
    # Favourite/follow toggles are deliberately excluded because they edit
    # their existing game card in place.
    navigation_exact = {
        "search", "popular", "discover", "upcoming", "years",
        "platforms", "genres", "favorites", "profile", "back",
    }
    navigation_prefixes = ("year:", "platform:", "genre:", "game:", "list:", "ai:")
    if data in navigation_exact or data.startswith(navigation_prefixes):
        await _clear_screen(context, query.message.chat_id)

    # Exact callback names
    exact_routes = {
        "search": start_search,
        "popular": show_popular,
        "discover": show_discover,
        "upcoming": show_upcoming,
        "years": show_years,
        "platforms": show_platforms,
        "genres": show_genres,
        "favorites": show_favorites,
        "profile": show_profile,
        "back": back_to_menu,
    }

    handler = exact_routes.get(data)
    if handler is not None:
        return await handler(update, context)

    # Callback names that include an argument after a colon
    prefix_routes = (
        ("year:", show_year_games),
        ("platform:", show_platform_games),
        ("genre:", show_genre_games),
        ("game:", show_game_details),
        ("list:", show_list_page),
        ("favorite_add:", add_favorite),
        ("favorite_remove:", remove_favorite),
        ("follow_add:", add_follow),
        ("follow_remove:", remove_follow),
        ("ai:", ai_description),
    )

    for prefix, handler in prefix_routes:
        if data.startswith(prefix):
            return await handler(update, context)

    try:
        await query.answer("این گزینه شناخته نشد.", show_alert=True)
    except TelegramError:
        logger.debug("Could not answer an unknown or expired callback query.")




        
# ============================================================
# Callback routing


# ============================================================
# Release notifications
# ============================================================

async def check_release_notifications(
    context: ContextTypes.DEFAULT_TYPE,
):
    try:
        followed_games = database.get_followed_games()

        if not followed_games:
            return

        today = datetime.now(timezone.utc).date()

        for item in followed_games:
            if item.get("notified"):
                continue

            release_value = item.get("release_date")
            if not release_value:
                continue

            release_date = None
            value = str(release_value)

            candidates = (
                value[:10],
                value.split("T", 1)[0],
                value.split(" ", 1)[0],
            )

            for candidate in candidates:
                for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
                    try:
                        release_date = datetime.strptime(candidate, fmt).date()
                        break
                    except ValueError:
                        continue

                if release_date:
                    break

            if not release_date or release_date > today:
                continue

            try:
                await context.bot.send_message(
                    chat_id=item["telegram_id"],
                    text=(
                        "🎉 <b>بازی منتشر شد!</b>\n\n"
                        f"🎮 <b>{escape_html(item['game_name'])}</b>\n\n"
                        "تاریخ انتشار این بازی فرا رسیده است."
                    ),
                    parse_mode=ParseMode.HTML,
                )

                database.mark_notified(item["id"])

            except Exception:
                logger.exception(
                    "Notification error | game=%s",
                    item.get("game_name"),
                )

    except Exception:
        logger.exception("Release notification job failed")


# ============================================================
# Global error handler
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    error = context.error

    logger.error(
        "❌ UNHANDLED ERROR | update=%r",
        update,
        exc_info=(
            type(error),
            error,
            error.__traceback__,
        ) if error else None,
    )


# ============================================================
# Main
# ============================================================

def main():
    from config import TELEGRAM_BOT_TOKEN

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not configured."
        )

    logger.info("Initializing database...")

    database.init_db()

    logger.info("Database path: %s", DB_PATH)
    logger.info("Games in database: %s", count_games())

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    # Register handlers
    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_search_message,
        )
    )

    application.add_handler(
        CallbackQueryHandler(callback_router)
    )

    application.add_error_handler(error_handler)

    if application.job_queue:
        application.job_queue.run_repeating(
            check_release_notifications,
            interval=60 * 60,
            first=30,
        )
        logger.info("Release notification job scheduled")
    else:
        logger.warning(
            "JobQueue unavailable; release notifications are disabled"
        )

    logger.info("🤖 GameRadarBot is starting polling...")

    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
    )


if __name__ == "__main__":
    main()