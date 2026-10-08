# parvit/bace.py

import html
import logging

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from agent import GameAgent
from config import TELEGRAM_BOT_TOKEN

from database import (
    add_favorite,
    follow_game,
    get_favorites,
    init_database,
    is_favorite,
    remove_favorite,
    save_user,
)

from services.gameservir import GameService


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# GLOBALS
# =========================================================

game_service = None
game_agent = GameAgent()


# =========================================================
# GENRES
# =========================================================

GENRES = {
    "mmorpg": "🧙 MMORPG",
    "shooter": "🔫 شوتر",
    "strategy": "♟️ استراتژی",
    "moba": "⚔️ MOBA",
    "racing": "🏎️ مسابقه‌ای",
    "sports": "⚽ ورزشی",
    "social": "💬 اجتماعی",
    "sandbox": "🏗️ Sandbox",
    "open-world": "🌍 جهان‌باز",
    "survival": "🧟 بقا",
    "fighting": "🥊 فایتینگ",
    "card": "🃏 کارتی",
    "battle-royale": "🏆 Battle Royale",
    "anime": "🎌 انیمه",
    "fantasy": "🧙 فانتزی",
    "sci-fi": "🚀 علمی‌تخیلی",
    "horror": "👻 ترسناک",
    "pixel": "👾 پیکسلی",
    "zombie": "🧟 زامبی",
    "military": "🪖 نظامی",
    "tower-defense": "🗼 Tower Defense",
    "turn-based": "♟️ نوبتی",
    "2d": "🎨 دوبعدی",
    "3d": "🧊 سه‌بعدی",
    "first-person": "🔫 اول‌شخص",
    "third-person": "🎮 سوم‌شخص",
}


# =========================================================
# PLATFORMS
# =========================================================

PLATFORMS = {
    "pc": "💻 PC",
    "browser": "🌐 Browser",
}


# =========================================================
# MAIN MENU
# =========================================================

def main_menu():
    keyboard = [
        [
            InlineKeyboardButton("🔎 جستجوی بازی", callback_data="search"),
            InlineKeyboardButton("🔥 محبوب‌ترین‌ها", callback_data="popular"),
        ],
        [
            InlineKeyboardButton("🎮 کشف بازی", callback_data="discover"),
            InlineKeyboardButton("📅 بر اساس سال", callback_data="years"),
        ],
        [
            InlineKeyboardButton("🎭 ژانرها", callback_data="genres"),
            InlineKeyboardButton("💻 پلتفرم‌ها", callback_data="platforms"),
        ],
        [
            InlineKeyboardButton("❤️ علاقه‌مندی‌ها", callback_data="favorites"),
            InlineKeyboardButton("🚀 بازی‌های آینده", callback_data="upcoming"),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if user:
        try:
            save_user(
                user.id,
                user.username,
                user.first_name,
            )
        except Exception:
            logger.exception("Could not save user")

    text = (
        "🎮 <b>GameRadarBot</b>\n\n"
        "سلام 👋\n"
        "من دستیار کشف بازی هستم.\n\n"
        "با من می‌تونی:\n"
        "🔎 بازی جستجو کنی\n"
        "🔥 بازی‌های محبوب رو ببینی\n"
        "🎭 بر اساس ژانر پیدا کنی\n"
        "📅 بر اساس سال جستجو کنی\n"
        "❤️ بازی‌ها رو ذخیره کنی\n"
        "🔔 بازی‌ها رو دنبال کنی\n\n"
        "👇 یکی از گزینه‌ها رو انتخاب کن:"
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


# =========================================================
# SEARCH PROMPT
# =========================================================

async def search_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.callback_query.edit_message_text(
        "🔎 <b>جستجوی بازی</b>\n\n"
        "اسم بازی رو برام بفرست.\n\n"
        "مثلاً:\n"
        "<code>Counter Strike</code>\n"
        "<code>Fortnite</code>\n"
        "<code>Warframe</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🏠 منوی اصلی",
                    callback_data="home",
                )
            ]
        ]),
    )

    context.user_data["waiting_for_search"] = True


# =========================================================
# SEARCH MESSAGE
# =========================================================

async def search_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    text = update.message.text.strip()

    if not text:
        return

    if not context.user_data.get("waiting_for_search"):
        return

    if len(text) < 2:

        await update.message.reply_text(
            "❌ عبارت جستجو خیلی کوتاهه.\n"
            "حداقل ۲ حرف وارد کن."
        )

        return

    context.user_data["waiting_for_search"] = False
    context.user_data["search_query"] = text

    await update.message.reply_text(
        "🔎 در حال جستجوی بازی‌ها..."
    )

    try:

        games = game_service.search_games(
            text,
            page=1,
            page_size=10,
        )

        await send_search_results(
            update,
            games,
            text,
        )

    except Exception as e:

        logger.exception("Search error")

        await update.message.reply_text(
            "❌ هنگام جستجو خطایی رخ داد.\n\n"
            f"<code>{html.escape(str(e))}</code>",
            parse_mode=ParseMode.HTML,
        )


# =========================================================
# SEARCH RESULTS
# =========================================================

async def send_search_results(
    update: Update,
    games,
    search_text,
):

    if not games:

        await update.message.reply_text(
            "😕 بازی‌ای با این نام پیدا نکردم.\n\n"
            "اسم بازی رو کمی متفاوت امتحان کن.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔎 جستجوی جدید",
                        callback_data="search",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🏠 منوی اصلی",
                        callback_data="home",
                    )
                ],
            ]),
        )

        return

    buttons = []

    for game in games:

        game_id = game.get("id")

        name = (
            game.get("name")
            or game.get("title")
            or "Unknown"
        )

        buttons.append([
            InlineKeyboardButton(
                f"🎮 {str(name)[:55]}",
                callback_data=f"game:{game_id}",
            )
        ])

    # Next page
    if len(games) >= 10:

        buttons.append([
            InlineKeyboardButton(
                "بعدی ➡️",
                callback_data="page:search:2",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔎 جستجوی جدید",
            callback_data="search",
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            "🏠 منوی اصلی",
            callback_data="home",
        )
    ])

    await update.message.reply_text(
        f"🔎 <b>نتایج جستجو برای:</b>\n"
        f"<code>{html.escape(search_text)}</code>\n\n"
        "برای مشاهده جزئیات روی بازی کلیک کن:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# =========================================================
# YEARS
# =========================================================

async def show_years(update: Update):

    buttons = []

    for year in range(2026, 2009, -1):

        buttons.append([
            InlineKeyboardButton(
                f"📅 {year}",
                callback_data=f"year:{year}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🏠 منوی اصلی",
            callback_data="home",
        )
    ])

    await update.callback_query.edit_message_text(
        "📅 <b>انتخاب سال</b>\n\n"
        "سال موردنظر رو انتخاب کن:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# =========================================================
# GENRES
# =========================================================

async def show_genres(update: Update):

    buttons = []

    items = list(GENRES.items())

    for i in range(0, len(items), 2):

        row = []

        for key, title in items[i:i + 2]:

            row.append(
                InlineKeyboardButton(
                    title,
                    callback_data=f"genre:{key}",
                )
            )

        buttons.append(row)

    buttons.append([
        InlineKeyboardButton(
            "🏠 منوی اصلی",
            callback_data="home",
        )
    ])

    await update.callback_query.edit_message_text(
        "🎭 <b>ژانر بازی</b>\n\n"
        "ژانر موردنظر رو انتخاب کن:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# =========================================================
# PLATFORMS
# =========================================================

async def show_platforms(update: Update):

    buttons = []

    for key, title in PLATFORMS.items():

        buttons.append([
            InlineKeyboardButton(
                title,
                callback_data=f"platform:{key}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🏠 منوی اصلی",
            callback_data="home",
        )
    ])

    await update.callback_query.edit_message_text(
        "💻 <b>پلتفرم</b>\n\n"
        "پلتفرم موردنظر رو انتخاب کن:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# =========================================================
# DISCOVER
# =========================================================

async def show_discover(update: Update):

    buttons = [
        [
            InlineKeyboardButton(
                "🔥 محبوب",
                callback_data="popular",
            )
        ],
        [
            InlineKeyboardButton(
                "🎭 بر اساس ژانر",
                callback_data="genres",
            )
        ],
        [
            InlineKeyboardButton(
                "📅 بر اساس سال",
                callback_data="years",
            )
        ],
        [
            InlineKeyboardButton(
                "💻 بر اساس پلتفرم",
                callback_data="platforms",
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="home",
            )
        ],
    ]

    await update.callback_query.edit_message_text(
        "🎮 <b>کشف بازی</b>\n\n"
        "چطور می‌خوای بازی پیدا کنی؟",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# =========================================================
# SHOW GAMES
# =========================================================

async def show_games(
    query,
    games,
    title,
    page=1,
    source="popular",
):

    if not games:

        await query.edit_message_text(
            "😕 بازی‌ای پیدا نشد.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🏠 منوی اصلی",
                        callback_data="home",
                    )
                ]
            ]),
        )

        return

    buttons = []

    for game in games:

        game_id = game.get("id")

        name = (
            game.get("name")
            or game.get("title")
            or "Unknown"
        )

        buttons.append([
            InlineKeyboardButton(
                f"🎮 {str(name)[:55]}",
                callback_data=f"game:{game_id}",
            )
        ])

    # Pagination

    pagination = []

    if page > 1:

        pagination.append(
            InlineKeyboardButton(
                "⬅️ قبلی",
                callback_data=f"page:{source}:{page - 1}",
            )
        )

    if len(games) >= 10:

        pagination.append(
            InlineKeyboardButton(
                "بعدی ➡️",
                callback_data=f"page:{source}:{page + 1}",
            )
        )

    if pagination:
        buttons.append(pagination)

    buttons.append([
        InlineKeyboardButton(
            "🏠 منوی اصلی",
            callback_data="home",
        )
    ])

    await query.edit_message_text(
        f"{title}\n\n"
        f"📄 صفحه {page}\n\n"
        "برای مشاهده جزئیات روی بازی کلیک کن:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# =========================================================
# GAME DETAILS
# =========================================================

async def show_game_details(
    query,
    game_id,
):

    try:

        game = game_service.get_game_details(game_id)

    except Exception:

        logger.exception("Game details error")

        await query.edit_message_text(
            "❌ دریافت اطلاعات بازی با خطا مواجه شد.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🏠 منوی اصلی",
                        callback_data="home",
                    )
                ]
            ]),
        )

        return

    if not game:

        await query.edit_message_text(
            "❌ اطلاعات بازی پیدا نشد.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🏠 منوی اصلی",
                        callback_data="home",
                    )
                ]
            ]),
        )

        return

    name = (
        game.get("name")
        or game.get("title")
        or "Unknown"
    )

    description = (
        game.get("short_description")
        or game.get("description")
        or "توضیحی برای این بازی ثبت نشده است."
    )

    release_date = (
        game.get("release_date")
        or "نامشخص"
    )

    genre = (
        game.get("genre")
        or game.get("genres")
        or "نامشخص"
    )

    platform = (
        game.get("platform")
        or game.get("platforms")
        or "نامشخص"
    )

    developer = (
        game.get("developer")
        or game.get("developers")
        or "نامشخص"
    )

    publisher = (
        game.get("publisher")
        or game.get("publishers")
        or "نامشخص"
    )

    game_url = game.get("game_url")

    profile_url = game.get(
        "freetogame_profile_url"
    )

    # =====================================================
    # AI DESCRIPTION
    # =====================================================

    ai_description = ""

    try:

        ai_description = game_agent.describe_game(
            game
        )

        if ai_description:
            ai_description = str(ai_description)

    except Exception:

        logger.exception(
            "AI description error"
        )

    # =====================================================
    # TEXT
    # =====================================================

    text = (
        f"🎮 <b>{html.escape(str(name))}</b>\n\n"
    )

    if ai_description:

        text += (
            f"🤖 <b>معرفی هوشمند:</b>\n"
            f"{html.escape(ai_description)}\n\n"
        )

    text += (
        f"📝 <b>توضیحات:</b>\n"
        f"{html.escape(str(description))}\n\n"
        f"📅 <b>تاریخ انتشار:</b> "
        f"{html.escape(str(release_date))}\n\n"
        f"🎭 <b>ژانر:</b> "
        f"{html.escape(str(genre))}\n\n"
        f"💻 <b>پلتفرم:</b> "
        f"{html.escape(str(platform))}\n\n"
        f"👨‍💻 <b>سازنده:</b> "
        f"{html.escape(str(developer))}\n\n"
        f"🏢 <b>ناشر:</b> "
        f"{html.escape(str(publisher))}\n"
    )

    # =====================================================
    # FAVORITE STATUS
    # =====================================================

    try:

        favorite = is_favorite(
            query.from_user.id,
            game_id,
        )

    except Exception:

        favorite = False

    favorite_text = (
        "💔 حذف از علاقه‌مندی‌ها"
        if favorite
        else
        "❤️ افزودن به علاقه‌مندی‌ها"
    )

    favorite_action = (
        f"favorite:remove:{game_id}"
        if favorite
        else
        f"favorite:add:{game_id}"
    )

    buttons = [
        [
            InlineKeyboardButton(
                favorite_text,
                callback_data=favorite_action,
            )
        ],
        [
            InlineKeyboardButton(
                "🔔 دنبال کردن بازی",
                callback_data=f"follow:{game_id}",
            )
        ],
    ]

    if game_url:

        buttons.append([
            InlineKeyboardButton(
                "🎮 صفحه بازی",
                url=game_url,
            )
        ])

    if profile_url:

        buttons.append([
            InlineKeyboardButton(
                "🌐 اطلاعات بیشتر",
                url=profile_url,
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🏠 منوی اصلی",
            callback_data="home",
        )
    ])

    reply_markup = InlineKeyboardMarkup(buttons)

    # =====================================================
    # IMAGE
    # =====================================================

    thumbnail = (
        game.get("thumbnail")
        or game.get("cover")
        or game.get("image")
    )

    if thumbnail:

        try:

            await query.message.reply_photo(
                photo=thumbnail,
                caption=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )

            await query.edit_message_text(
                "🎮 اطلاعات بازی در پیام جدید ارسال شد."
            )

            return

        except Exception:

            logger.exception(
                "Could not send game image"
            )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
    )


# =========================================================
# FAVORITES
# =========================================================

async def show_favorites(query):

    user_id = query.from_user.id

    try:

        games = get_favorites(user_id)

    except Exception:

        logger.exception(
            "Could not get favorites"
        )

        await query.edit_message_text(
            "❌ دریافت علاقه‌مندی‌ها با خطا مواجه شد.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🏠 منوی اصلی",
                        callback_data="home",
                    )
                ]
            ]),
        )

        return

    if not games:

        await query.edit_message_text(
            "❤️ <b>علاقه‌مندی‌ها</b>\n\n"
            "هنوز هیچ بازی‌ای ذخیره نکردی.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🎮 کشف بازی",
                        callback_data="discover",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🏠 منوی اصلی",
                        callback_data="home",
                    )
                ]
            ]),
        )

        return

    buttons = []

    for game in games:

        if isinstance(game, dict):

            game_id = game.get("id")

            name = (
                game.get("name")
                or game.get("title")
                or "Unknown"
            )

        else:

            game_id = game

            name = f"Game {game_id}"

        buttons.append([
            InlineKeyboardButton(
                f"❤️ {str(name)[:55]}",
                callback_data=f"game:{game_id}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🏠 منوی اصلی",
            callback_data="home",
        )
    ])

    await query.edit_message_text(
        "❤️ <b>بازی‌های مورد علاقه</b>\n\n"
        "یکی از بازی‌ها رو انتخاب کن:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# =========================================================
# CALLBACK HANDLER
# =========================================================

async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    data = query.data or ""

    # =====================================================
    # HOME
    # =====================================================

    if data == "home":

        context.user_data["waiting_for_search"] = False

        await query.edit_message_text(
            "🎮 <b>GameRadarBot</b>\n\n"
            "چه کاری می‌خوای انجام بدی؟",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )

        return

    # =====================================================
    # SEARCH
    # =====================================================

    if data == "search":

        await search_prompt(
            update,
            context,
        )

        return

    # =====================================================
    # DISCOVER
    # =====================================================

    if data == "discover":

        await show_discover(update)

        return

    # =====================================================
    # YEARS
    # =====================================================

    if data == "years":

        await show_years(update)

        return

    # =====================================================
    # GENRES
    # =====================================================

    if data == "genres":

        await show_genres(update)

        return

    # =====================================================
    # PLATFORMS
    # =====================================================

    if data == "platforms":

        await show_platforms(update)

        return

    # =====================================================
    # POPULAR
    # =====================================================

    if data == "popular":

        try:

            games = game_service.get_popular_games(
                page=1,
                page_size=10,
            )

            await show_games(
                query,
                games,
                "🔥 محبوب‌ترین بازی‌ها",
                page=1,
                source="popular",
            )

        except Exception:

            logger.exception(
                "Popular games error"
            )

            await query.edit_message_text(
                "❌ دریافت بازی‌های محبوب با خطا مواجه شد.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "🏠 منوی اصلی",
                            callback_data="home",
                        )
                    ]
                ]),
            )

        return

    # =====================================================
    # UPCOMING
    # =====================================================

    if data == "upcoming":

        try:

            games = game_service.get_upcoming_games(
                page=1,
                page_size=10,
            )

            if not games:

                await query.edit_message_text(
                    "🚀 <b>بازی‌های آینده</b>\n\n"
                    "منبع فعلی FreeToGame اطلاعات قابل‌اعتمادی "
                    "برای بازی‌های منتشرنشده ارائه نمی‌دهد.\n\n"
                    "بعداً می‌تونیم یک منبع جدا برای "
                    "Upcoming Games اضافه کنیم.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton(
                                "🏠 منوی اصلی",
                                callback_data="home",
                            )
                        ]
                    ]),
                )

                return

            await show_games(
                query,
                games,
                "🚀 بازی‌های آینده",
                page=1,
                source="upcoming",
            )

        except Exception:

            logger.exception(
                "Upcoming games error"
            )

            await query.edit_message_text(
                "❌ دریافت بازی‌های آینده با خطا مواجه شد.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "🏠 منوی اصلی",
                            callback_data="home",
                        )
                    ]
                ]),
            )

        return

    # =====================================================
    # FAVORITES
    # =====================================================

    if data == "favorites":

        await show_favorites(query)

        return

    # =====================================================
    # YEAR
    # =====================================================

    if data.startswith("year:"):

        try:

            year = int(
                data.split(":", 1)[1]
            )

        except ValueError:

            await query.edit_message_text(
                "❌ سال نامعتبر است.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "🏠 منوی اصلی",
                            callback_data="home",
                        )
                    ]
                ]),
            )

            return

        try:

            games = game_service.get_games_by_year(
                year,
                page=1,
                page_size=10,
            )

            await show_games(
                query,
                games,
                f"📅 بازی‌های سال {year}",
                page=1,
                source=f"year:{year}",
            )

        except Exception:

            logger.exception(
                "Year games error"
            )

            await query.edit_message_text(
                "❌ دریافت بازی‌های این سال با خطا مواجه شد.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "🏠 منوی اصلی",
                            callback_data="home",
                        )
                    ]
                ]),
            )

        return

    # =====================================================
    # GENRE
    # =====================================================

    if data.startswith("genre:"):

        genre = data.split(":", 1)[1]

        try:

            games = game_service.get_games_by_genre(
                genre,
                page=1,
                page_size=10,
            )

            title = GENRES.get(
                genre,
                genre,
            )

            await show_games(
                query,
                games,
                f"🎭 {title}",
                page=1,
                source=f"genre:{genre}",
            )

        except Exception:

            logger.exception(
                "Genre games error"
            )

            await query.edit_message_text(
                "❌ دریافت بازی‌های این ژانر با خطا مواجه شد.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "🏠 منوی اصلی",
                            callback_data="home",
                        )
                    ]
                ]),
            )

        return

    # =====================================================
    # PLATFORM
    # =====================================================

    if data.startswith("platform:"):

        platform = data.split(":", 1)[1]

        try:

            games = game_service.get_games_by_platform(
                platform,
                page=1,
                page_size=10,
            )

            title = PLATFORMS.get(
                platform,
                platform,
            )

            await show_games(
                query,
                games,
                f"💻 {title}",
                page=1,
                source=f"platform:{platform}",
            )

        except Exception:

            logger.exception(
                "Platform games error"
            )

            await query.edit_message_text(
                "❌ دریافت بازی‌های این پلتفرم با خطا مواجه شد.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "🏠 منوی اصلی",
                            callback_data="home",
                        )
                    ]
                ]),
            )

        return

    # =====================================================
    # GAME DETAILS
    # =====================================================

    if data.startswith("game:"):

        game_id = data.split(":", 1)[1]

        await show_game_details(
            query,
            game_id,
        )

        return

    # =====================================================
    # FAVORITE ADD
    # =====================================================

    if data.startswith("favorite:add:"):

        game_id = data.split(":", 2)[2]

        try:

            add_favorite(
                query.from_user.id,
                game_id,
            )

            await query.answer(
                "❤️ بازی به علاقه‌مندی‌ها اضافه شد."
            )

        except Exception:

            logger.exception(
                "Add favorite error"
            )

            await query.answer(
                "❌ ذخیره بازی انجام نشد.",
                show_alert=True,
            )

        return

    # =====================================================
    # FAVORITE REMOVE
    # =====================================================

    if data.startswith("favorite:remove:"):

        game_id = data.split(":", 2)[2]

        try:

            remove_favorite(
                query.from_user.id,
                game_id,
            )

            await query.answer(
                "💔 از علاقه‌مندی‌ها حذف شد."
            )

        except Exception:

            logger.exception(
                "Remove favorite error"
            )

            await query.answer(
                "❌ حذف بازی انجام نشد.",
                show_alert=True,
            )

        return

    # =====================================================
    # FOLLOW
    # =====================================================

    if data.startswith("follow:"):

        game_id = data.split(":", 1)[1]

        try:

            follow_game(
                query.from_user.id,
                game_id,
            )

            await query.answer(
                "🔔 اعلان بازی فعال شد."
            )

        except Exception:

            logger.exception(
                "Follow game error"
            )

            await query.answer(
                "❌ فعال‌سازی اعلان انجام نشد.",
                show_alert=True,
            )

        return

    # =====================================================
    # PAGINATION
    # =====================================================

    if data.startswith("page:"):

        parts = data.split(":")

        if len(parts) < 3:
            return

        try:

            page = int(parts[-1])

        except ValueError:

            return

        source = ":".join(parts[1:-1])

        games = []
        title = "🎮 بازی‌ها"

        # -------------------------------------------------
        # POPULAR
        # -------------------------------------------------

        if source == "popular":

            games = game_service.get_popular_games(
                page=page,
                page_size=10,
            )

            title = "🔥 محبوب‌ترین بازی‌ها"

        # -------------------------------------------------
        # YEAR
        # -------------------------------------------------

        elif source.startswith("year:"):

            try:

                year = int(
                    source.split(":", 1)[1]
                )

            except ValueError:

                await query.edit_message_text(
                    "❌ سال نامعتبر است."
                )

                return

            games = game_service.get_games_by_year(
                year,
                page=page,
                page_size=10,
            )

            title = f"📅 بازی‌های سال {year}"

        # -------------------------------------------------
        # GENRE
        # -------------------------------------------------

        elif source.startswith("genre:"):

            genre = source.split(
                ":",
                1,
            )[1]

            games = game_service.get_games_by_genre(
                genre,
                page=page,
                page_size=10,
            )

            title = (
                f"🎭 "
                f"{GENRES.get(genre, genre)}"
            )

        # -------------------------------------------------
        # PLATFORM
        # -------------------------------------------------

        elif source.startswith("platform:"):

            platform = source.split(
                ":",
                1,
            )[1]

            games = game_service.get_games_by_platform(
                platform,
                page=page,
                page_size=10,
            )

            title = (
                f"💻 "
                f"{PLATFORMS.get(platform, platform)}"
            )

        # -------------------------------------------------
        # SEARCH
        # -------------------------------------------------

        elif source == "search":

            search_text = context.user_data.get(
                "search_query",
                "",
            )

            if not search_text:

                await query.edit_message_text(
                    "❌ عبارت جستجو پیدا نشد.",
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton(
                                "🔎 جستجوی جدید",
                                callback_data="search",
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "🏠 خانه",
                                callback_data="home",
                            )
                        ],
                    ]),
                )

                return

            games = game_service.search_games(
                search_text,
                page=page,
                page_size=10,
            )

            title = (
                f"🔎 نتایج جستجو: "
                f"{html.escape(search_text)}"
            )

        # -------------------------------------------------
        # UPCOMING
        # -------------------------------------------------

        elif source == "upcoming":

            games = game_service.get_upcoming_games(
                page=page,
                page_size=10,
            )

            title = "🚀 بازی‌های آینده"

        # -------------------------------------------------
        # INVALID SOURCE
        # -------------------------------------------------

        else:

            await query.edit_message_text(
                "❌ نوع صفحه نامعتبر است.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "🏠 منوی اصلی",
                            callback_data="home",
                        )
                    ]
                ]),
            )

            return

        await show_games(
            query,
            games,
            title,
            page=page,
            source=source,
        )

        return

    # =====================================================
    # UNKNOWN CALLBACK
    # =====================================================

    await query.edit_message_text(
        "❌ دستور ناشناخته است.",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🏠 منوی اصلی",
                    callback_data="home",
                )
            ]
        ]),
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.error(
        "Exception while handling update:",
        exc_info=context.error,
    )


# =========================================================
# MAIN
# =========================================================

def main():

    global game_service

    # -----------------------------------------------------
    # CHECK TOKEN
    # -----------------------------------------------------

    if not TELEGRAM_BOT_TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN در فایل .env تنظیم نشده است."
        )

    # -----------------------------------------------------
    # DATABASE
    # -----------------------------------------------------

    try:

        init_database()

    except Exception:

        logger.exception(
            "Database initialization failed"
        )

        raise

    # -----------------------------------------------------
    # GAME SERVICE
    # -----------------------------------------------------

    game_service = GameService()

    # -----------------------------------------------------
    # TELEGRAM APPLICATION
    # -----------------------------------------------------

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    # -----------------------------------------------------
    # COMMANDS
    # -----------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    # -----------------------------------------------------
    # CALLBACKS
    # -----------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            callback_handler,
        )
    )

    # -----------------------------------------------------
    # SEARCH TEXT
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            search_handler,
        )
    )

    # -----------------------------------------------------
    # ERROR
    # -----------------------------------------------------

    application.add_error_handler(
        error_handler
    )

    # -----------------------------------------------------
    # START
    # -----------------------------------------------------

    logger.info(
        "🤖 GameRadarBot is running..."
    )

    application.run_polling(
        drop_pending_updates=True,
    )


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    main()