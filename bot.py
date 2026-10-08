
import logging
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
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


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


game_service = GameService()
game_agent = GameAgent()
PAGE_SIZE = 5


# ------------------------------------------------------------------
# UI helpers
# ------------------------------------------------------------------

def main_menu():
    keyboard = [
        [
            InlineKeyboardButton("🔎 جستجوی بازی", callback_data="search"),
            InlineKeyboardButton("🔥 محبوب‌ها", callback_data="popular"),
        ],
        [
            InlineKeyboardButton("🎮 کشف بازی", callback_data="discover"),
            InlineKeyboardButton("📅 بازی‌های آینده", callback_data="upcoming"),
        ],
        [
            InlineKeyboardButton("📆 بر اساس سال", callback_data="years"),
            InlineKeyboardButton("💻 بر اساس پلتفرم", callback_data="platforms"),
        ],
        [
            InlineKeyboardButton("❤️ علاقه‌مندی‌ها", callback_data="favorites"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def _safe(value, fallback="نامشخص"):
    value = str(value or "").strip()
    return escape_html(value) if value else fallback


def _game_button_text(name: str) -> str:
    clean = str(name or "بازی")
    return f"🎮 {clean[:40]}"


async def _send_error(message, text="❌ خطایی رخ داد."):
    try:
        await message.reply_text(text)
    except Exception:
        logger.exception("Could not send error message")


# ------------------------------------------------------------------
# Start / search
# ------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    database.add_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    text = (
        f"🎮 <b>GameRadarBot</b>\n\n"
        f"سلام {_safe(user.first_name, 'گیمر')} 👋\n\n"
        "برای پیدا کردن بازی، اطلاعات بازی و دنبال‌کردن انتشار آن آماده‌ام.\n\n"
        "از منوی زیر شروع کن:"
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


async def start_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data["waiting_for_search"] = True

    await query.message.reply_text(
        "🔎 نام بازی را بفرست.\n\n"
        "مثلاً:\n"
        "<code>GTA</code>\n"
        "<code>Minecraft</code>\n"
        "<code>Counter Strike</code>",
        parse_mode=ParseMode.HTML,
    )


async def handle_search_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("waiting_for_search"):
        return

    context.user_data["waiting_for_search"] = False

    search_text = (update.message.text or "").strip()

    if not search_text:
        await update.message.reply_text(
            "❌ عبارت جستجو نمی‌تواند خالی باشد."
        )
        return

    await update.message.reply_text(
        "🔎 در حال جستجو در پایگاه‌داده..."
    )

    try:
        games = game_service.search_games(
            search_text,
            page_size=100,
        )

        await send_game_list(
            update.message,
            context,
            games,
            title=f"🔎 نتایج جستجو برای: {search_text}",
        )

    except Exception:
        logger.exception("Search error")
        await _send_error(
            update.message,
            "❌ هنگام جستجو خطایی رخ داد.",
        )


# ------------------------------------------------------------------
# Lists
# ------------------------------------------------------------------

async def show_popular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        games = game_service.get_popular_games(page_size=100)

        await send_game_list(
            query.message,
            context,
            games,
            "🔥 بازی‌های محبوب",
        )

    except Exception:
        logger.exception("Popular games error")
        await _send_error(
            query.message,
            "❌ دریافت بازی‌های محبوب با خطا مواجه شد.",
        )


async def show_discover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        games = game_service.get_games(page_size=100)

        await send_game_list(
            query.message,
            context,
            games,
            "🎮 بازی‌های پیشنهادی",
        )

    except Exception:
        logger.exception("Discover error")
        await _send_error(
            query.message,
            "❌ دریافت بازی‌ها با خطا مواجه شد.",
        )


async def show_upcoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        games = game_service.get_upcoming_games(page_size=100)

        if not games:
            await query.message.reply_text(
                "📅 در حال حاضر بازی آینده‌ای در پایگاه‌داده پیدا نشد."
            )
            return

        await send_game_list(
            query.message,
            context,
            games,
            "📅 بازی‌های آینده",
        )

    except Exception:
        logger.exception("Upcoming error")
        await _send_error(
            query.message,
            "❌ دریافت بازی‌های آینده با خطا مواجه شد.",
        )


async def show_years(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    years = game_service.get_available_years()

    if not years:
        await query.message.reply_text(
            "📆 هنوز سالی در پایگاه‌داده ثبت نشده است."
        )
        return

    keyboard = []

    for i in range(0, len(years), 3):
        keyboard.append(
            [
                InlineKeyboardButton(
                    str(year),
                    callback_data=f"year:{year}",
                )
                for year in years[i:i + 3]
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ بازگشت",
                callback_data="back",
            )
        ]
    )

    await query.message.reply_text(
        "📆 سال انتشار را انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_year_games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    year = int(query.data.split(":", 1)[1])

    try:
        games = game_service.get_games_by_year(
            year,
            page_size=100,
        )

        await send_game_list(
            query.message,
            context,
            games,
            f"📆 بازی‌های سال {year}",
        )

    except Exception:
        logger.exception("Year filter error")
        await _send_error(
            query.message,
            "❌ دریافت بازی‌ها با خطا مواجه شد.",
        )


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
    return PLATFORM_LABELS.get(
        platform,
        f"💻 {platform}",
    )


async def show_platforms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    platforms = game_service.get_available_platforms()

    if not platforms:
        await query.message.reply_text(
            "💻 هنوز پلتفرمی در پایگاه‌داده ثبت نشده است."
        )
        return

    keyboard = []

    for i in range(0, len(platforms), 2):
        keyboard.append(
            [
                InlineKeyboardButton(
                    platform_label(platform),
                    callback_data=f"platform:{platform}",
                )
                for platform in platforms[i:i + 2]
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ بازگشت",
                callback_data="back",
            )
        ]
    )

    await query.message.reply_text(
        "💻 پلتفرم را انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_platform_games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    platform = query.data.split(":", 1)[1]

    try:
        games = game_service.get_games_by_platform(
            platform,
            page_size=100,
        )

        await send_game_list(
            query.message,
            context,
            games,
            platform_label(platform),
        )

    except Exception:
        logger.exception("Platform filter error")
        await _send_error(
            query.message,
            "❌ دریافت بازی‌ها با خطا مواجه شد.",
        )


async def send_game_list(
    message,
    context,
    games,
    title="🎮 بازی‌ها",
    page=0,
):
    games = games or []

    if page == 0:
        context.user_data["last_list_ids"] = [
            int(game["id"])
            for game in games
            if game.get("id") is not None
        ]

        context.user_data["last_list_title"] = title

    all_ids = context.user_data.get(
        "last_list_ids",
        [],
    )

    if not all_ids:
        await message.reply_text(
            f"{title}\n\n❌ بازی‌ای پیدا نشد."
        )
        return

    start = page * PAGE_SIZE
    ids = all_ids[start:start + PAGE_SIZE]

    if not ids:
        await message.reply_text(
            "❌ این صفحه وجود ندارد."
        )
        return

    page_games = [
        game_service.get_game_details(game_id)
        for game_id in ids
    ]

    page_games = [
        game for game in page_games
        if game
    ]

    text = (
        f"<b>{escape_html(title)}</b>\n\n"
    )

    keyboard = []

    for game in page_games:
        name = str(
            game.get("name") or "Unknown"
        )

        text += (
            f"🎮 <b>{escape_html(name)}</b>\n"
        )

        release_date = game.get("release_date")

        if release_date:
            text += (
                f"📅 {_safe(release_date)}\n"
            )

        rating = game.get("rating")

        if rating is not None:
            text += (
                f"⭐ {_safe(rating)}\n"
            )

        text += "\n"

        keyboard.append(
            [
                InlineKeyboardButton(
                    _game_button_text(name),
                    callback_data=f"game:{int(game['id'])}",
                )
            ]
        )

    page_count = (
        len(all_ids) + PAGE_SIZE - 1
    ) // PAGE_SIZE

    navigation = []

    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                "⬅️ قبلی",
                callback_data=f"list:{page - 1}",
            )
        )

    if start + PAGE_SIZE < len(all_ids):
        navigation.append(
            InlineKeyboardButton(
                "➡️ بعدی",
                callback_data=f"list:{page + 1}",
            )
        )

    if navigation:
        keyboard.append(navigation)

    keyboard.append(
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="back",
            )
        ]
    )

    text += (
        f"صفحه {page + 1} از {page_count}"
    )

    await message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_list_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    page = int(
        query.data.split(":", 1)[1]
    )

    title = context.user_data.get(
        "last_list_title",
        "🎮 بازی‌ها",
    )

    await send_game_list(
        query.message,
        context,
        [],
        title=title,
        page=page,
    )


# ------------------------------------------------------------------
# Game details / actions
# ------------------------------------------------------------------

async def show_game_details(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    game_id = query.data.split(":", 1)[1]

    game = game_service.get_game_details(
        game_id
    )

    if not game:
        await query.message.reply_text(
            "❌ اطلاعات بازی پیدا نشد."
        )
        return

    await send_game_details(
        query.message,
        game,
        query.from_user.id,
    )


async def send_game_details(
    message,
    game,
    telegram_id,
):
    game_id = int(game["id"])

    name = game.get("name") or "Unknown"

    summary = (
        game.get("description")
        or game.get("summary")
        or "توضیحی برای این بازی ثبت نشده است."
    )

    summary = truncate(
        summary,
        500,
    )

    release_date = (
        game.get("release_date")
        or "نامشخص"
    )

    rating = game.get("rating")

    rating_text = (
        str(rating)
        if rating is not None
        else "نامشخص"
    )

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
        f"🎭 <b>ژانر:</b> "
        f"{escape_html('، '.join(genres)) if genres else 'نامشخص'}\n"
        f"💻 <b>پلتفرم:</b> "
        f"{escape_html('، '.join(platforms)) if platforms else 'نامشخص'}\n"
        f"👨‍💻 <b>سازنده:</b> {_safe(developer)}\n"
        f"🏢 <b>ناشر:</b> {_safe(publisher)}"
    )

    favorite = database.is_favorite(
        telegram_id,
        game_id,
    )

    following = database.is_following(
        telegram_id,
        game_id,
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "💔 حذف از علاقه‌مندی‌ها"
                if favorite
                else "❤️ افزودن به علاقه‌مندی‌ها",
                callback_data=(
                    f"favorite_remove:{game_id}"
                    if favorite
                    else f"favorite_add:{game_id}"
                ),
            )
        ],
        [
            InlineKeyboardButton(
                "🔕 لغو دنبال‌کردن"
                if following
                else "🔔 دنبال‌کردن انتشار",
                callback_data=(
                    f"follow_remove:{game_id}"
                    if following
                    else f"follow_add:{game_id}"
                ),
            )
        ],
        [
            InlineKeyboardButton(
                "🤖 توضیح با هوش مصنوعی",
                callback_data=f"ai:{game_id}",
            )
        ],
    ]

    if game_url:
        keyboard.insert(
            2,
            [
                InlineKeyboardButton(
                    "🔗 صفحه بازی در GameUP",
                    url=game_url,
                )
            ],
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="back",
            )
        ]
    )

    markup = InlineKeyboardMarkup(keyboard)

    photo_caption = truncate(
        text.replace("<b>", "")
        .replace("</b>", ""),
        950,
    )

    if cover_url:
        try:
            await message.reply_photo(
                photo=cover_url,
                caption=photo_caption,
                reply_markup=markup,
            )
            return

        except Exception as exc:
            logger.warning(
                "Could not send game cover: %s",
                exc,
            )

    await message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


async def refresh_game_details(
    query,
    game,
):
    try:
        await query.message.delete()
    except Exception:
        pass

    await send_game_details(
        query.message,
        game,
        query.from_user.id,
    )


async def add_favorite(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    del context

    query = update.callback_query
    await query.answer(
        "❤️ به علاقه‌مندی‌ها اضافه شد."
    )

    game_id = query.data.split(":", 1)[1]

    game = game_service.get_game_details(
        game_id
    )

    if not game:
        return

    database.add_favorite(
        query.from_user.id,
        int(game["id"]),
        game.get("name"),
    )

    await refresh_game_details(
        query,
        game,
    )


async def remove_favorite(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    del context

    query = update.callback_query
    await query.answer(
        "💔 از علاقه‌مندی‌ها حذف شد."
    )

    game_id = int(
        query.data.split(":", 1)[1]
    )

    database.remove_favorite(
        query.from_user.id,
        game_id,
    )

    game = game_service.get_game_details(
        game_id
    )

    if game:
        await refresh_game_details(
            query,
            game,
        )


async def add_follow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    del context

    query = update.callback_query
    await query.answer(
        "🔔 بازی دنبال شد."
    )

    game_id = int(
        query.data.split(":", 1)[1]
    )

    game = game_service.get_game_details(
        game_id
    )

    if not game:
        return

    database.follow_game(
        query.from_user.id,
        game_id,
        game_name=game.get("name"),
        release_date=game.get("release_date"),
    )

    await refresh_game_details(
        query,
        game,
    )


async def remove_follow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    del context

    query = update.callback_query
    await query.answer(
        "🔕 دنبال‌کردن لغو شد."
    )

    game_id = int(
        query.data.split(":", 1)[1]
    )

    database.unfollow_game(
        query.from_user.id,
        game_id,
    )

    game = game_service.get_game_details(
        game_id
    )

    if game:
        await refresh_game_details(
            query,
            game,
        )


async def show_favorites(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    favorites = database.get_favorites(
        query.from_user.id
    )

    if not favorites:
        await query.message.reply_text(
            "❤️ هنوز هیچ بازی‌ای به علاقه‌مندی‌ها اضافه نکرده‌ای."
        )
        return

    keyboard = [
        [
            InlineKeyboardButton(
                _game_button_text(
                    game.get("name", "بازی")
                ),
                callback_data=f"game:{int(game['id'])}",
            )
        ]
        for game in favorites
    ]

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ بازگشت",
                callback_data="back",
            )
        ]
    )

    await query.message.reply_text(
        "❤️ <b>بازی‌های مورد علاقه</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def ai_description(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    del context

    query = update.callback_query

    await query.answer(
        "🤖 در حال تولید توضیحات..."
    )

    game_id = query.data.split(":", 1)[1]

    game = game_service.get_game_details(
        game_id
    )

    if not game:
        await query.message.reply_text(
            "❌ بازی پیدا نشد."
        )
        return

    try:
        description = game_agent.describe_game(
            title=game.get("name", "Unknown"),
            genre=game_service.get_genres(game),
            description=(
                game.get("description")
                or game.get("summary")
                or ""
            ),
            platforms=game_service.get_platforms(game),
        )

    except Exception:
        logger.exception(
            "AI description error"
        )

        await _send_error(
            query.message,
            "❌ تولید توضیح با هوش مصنوعی انجام نشد.",
        )

        return

    await query.message.reply_text(
        "🤖 <b>معرفی هوشمند بازی</b>\n\n"
        + escape_html(description),
        parse_mode=ParseMode.HTML,
    )


# ------------------------------------------------------------------
# Back / callbacks
# ------------------------------------------------------------------

async def back_to_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    await query.message.reply_text(
        "🏠 منوی اصلی:",
        reply_markup=main_menu(),
    )


async def callback_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    data = query.data or ""

    if data == "search":
        return await start_search(update, context)

    if data == "popular":
        return await show_popular(update, context)

    if data == "discover":
        return await show_discover(update, context)

    if data == "upcoming":
        return await show_upcoming(update, context)

    if data == "years":
        return await show_years(update, context)

    if data == "platforms":
        return await show_platforms(update, context)

    if data == "favorites":
        return await show_favorites(update, context)

    if data.startswith("year:"):
        return await show_year_games(update, context)

    if data.startswith("platform:"):
        return await show_platform_games(update, context)

    if data.startswith("game:"):
        return await show_game_details(update, context)

    if data.startswith("list:"):
        return await show_list_page(update, context)

    if data.startswith("favorite_add:"):
        return await add_favorite(update, context)

    if data.startswith("favorite_remove:"):
        return await remove_favorite(update, context)

    if data.startswith("follow_add:"):
        return await add_follow(update, context)

    if data.startswith("follow_remove:"):
        return await remove_follow(update, context)

    if data.startswith("ai:"):
        return await ai_description(update, context)

    if data == "back":
        return await back_to_menu(update, context)

    await query.answer()


# ------------------------------------------------------------------
# Notifications
# ------------------------------------------------------------------

async def check_release_notifications(
    context: ContextTypes.DEFAULT_TYPE,
):
    followed_games = database.get_followed_games()

    if not followed_games:
        return

    today = datetime.now(
        timezone.utc
    ).date()

    for item in followed_games:
        if item.get("notified"):
            continue

        release_value = item.get("release_date")

        if not release_value:
            continue

        release_date = None
        value = str(release_value)

        for candidate in (
            value[:10],
            value.split("T", 1)[0],
            value.split(" ", 1)[0],
        ):
            for fmt in (
                "%Y-%m-%d",
                "%Y/%m/%d",
                "%Y.%m.%d",
            ):
                try:
                    release_date = datetime.strptime(
                        candidate,
                        fmt,
                    ).date()
                    break
                except ValueError:
                    pass

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

            database.mark_notified(
                item["id"]
            )

        except Exception:
            logger.exception(
                "Notification error for %s",
                item.get("game_name"),
            )


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    logger.exception(
        "Unhandled exception:",
        exc_info=context.error,
    )


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    from config import TELEGRAM_BOT_TOKEN

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not configured."
        )

    database.init_db()

    # --------------------------------------------------------------
    # Database diagnostic logs
    # --------------------------------------------------------------
    print(f"📁 Database path: {DB_PATH}")
    print(f"🎮 Games in database: {count_games()}")

    logger.info(
        "📁 Database path: %s",
        DB_PATH,
    )

    logger.info(
        "🎮 Games in database: %s",
        count_games(),
    )

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_search_message,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            callback_router,
        )
    )

    application.add_error_handler(
        error_handler
    )

    if application.job_queue:
        application.job_queue.run_repeating(
            check_release_notifications,
            interval=60 * 60,
            first=30,
        )

    logger.info(
        "🤖 GameRadarBot is running..."
    )

    logger.info(
        "Database: %s games",
        game_service.count_games(),
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
