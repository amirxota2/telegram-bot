import html
import logging
from datetime import datetime

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
    unfollow_game,
)
from game_service import GameService


logging.basicConfig(
    format=(
        "%(asctime)s - "
        "%(name)s - "
        "%(levelname)s - "
        "%(message)s"
    ),
    level=logging.INFO,
)

logger = logging.getLogger(
    __name__
)


game_service = None
game_agent = GameAgent()


# =========================================================
# GENRES
# =========================================================

GENRES = {
    "4": "⚔️ اکشن",
    "31": "🗺️ ماجراجویی",
    "12": "🧙 RPG",
    "15": "♟️ استراتژی",
    "13": "🏗️ شبیه‌سازی",
    "14": "⚽ ورزشی",
    "10": "🏎️ مسابقه‌ای",
    "5": "🔫 شوتر",
    "6": "🥊 فایتینگ",
    "9": "🧩 پازل",
    "8": "🕹️ پلتفرمر",
    "32": "🎨 ایندی",
    "33": "🕹️ آرکید",
}


# =========================================================
# PLATFORMS
# =========================================================

PLATFORMS = {
    "6": "💻 PC",
    "167": "🎮 PS5",
    "48": "🎮 PS4",
    "9": "🎮 PS3",
    "169": "🎮 Xbox Series",
    "49": "🎮 Xbox One",
    "12": "🎮 Xbox 360",
    "130": "🎮 Nintendo Switch",
    "3": "🐧 Linux",
    "14": "🍎 macOS",
    "34": "📱 Android",
    "39": "📱 iOS",
}


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    save_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "🎮 کشف بازی‌ها",
                callback_data="discover",
            ),
            InlineKeyboardButton(
                "🔥 محبوب‌ترین‌ها",
                callback_data="popular",
            ),
        ],
        [
            InlineKeyboardButton(
                "📅 انتخاب سال",
                callback_data="years",
            ),
            InlineKeyboardButton(
                "🎯 انتخاب ژانر",
                callback_data="genres",
            ),
        ],
        [
            InlineKeyboardButton(
                "💻 انتخاب پلتفرم",
                callback_data="platforms",
            ),
            InlineKeyboardButton(
                "🚀 بازی‌های آینده",
                callback_data="upcoming",
            ),
        ],
        [
            InlineKeyboardButton(
                "❤️ علاقه‌مندی‌ها",
                callback_data="favorites",
            ),
        ],
    ]

    text = (
        "🎮 <b>Game Discovery Agent</b>\n\n"
        "بازی موردنظرت رو پیدا کن.\n\n"
        "می‌تونی بر اساس سال، ژانر یا "
        "پلتفرم بازی‌ها رو فیلتر کنی و "
        "بعد اطلاعات کامل بازی، کاور و "
        "لینک فروشگاه‌ها رو ببینی."
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# =========================================================
# MAIN MENU
# =========================================================

def main_menu():

    keyboard = [
        [
            InlineKeyboardButton(
                "🎮 کشف بازی‌ها",
                callback_data="discover",
            ),
            InlineKeyboardButton(
                "🔥 محبوب‌ترین‌ها",
                callback_data="popular",
            ),
        ],
        [
            InlineKeyboardButton(
                "📅 سال",
                callback_data="years",
            ),
            InlineKeyboardButton(
                "🎯 ژانر",
                callback_data="genres",
            ),
        ],
        [
            InlineKeyboardButton(
                "💻 پلتفرم",
                callback_data="platforms",
            ),
            InlineKeyboardButton(
                "🚀 آینده",
                callback_data="upcoming",
            ),
        ],
        [
            InlineKeyboardButton(
                "❤️ علاقه‌مندی‌ها",
                callback_data="favorites",
            ),
        ],
    ]

    return InlineKeyboardMarkup(
        keyboard
    )


# =========================================================
# DISCOVER
# =========================================================

async def show_discover(
    query,
):

    keyboard = [
        [
            InlineKeyboardButton(
                "📅 بر اساس سال",
                callback_data="years",
            )
        ],
        [
            InlineKeyboardButton(
                "🎯 بر اساس ژانر",
                callback_data="genres",
            )
        ],
        [
            InlineKeyboardButton(
                "💻 بر اساس پلتفرم",
                callback_data="platforms",
            )
        ],
    ]

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ بازگشت",
                callback_data="home",
            )
        ]
    )

    await query.edit_message_text(
        "🎮 <b>کشف بازی</b>\n\n"
        "روش جستجو رو انتخاب کن:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# =========================================================
# YEARS
# =========================================================

async def show_years(
    query,
):

    current_year = datetime.now().year

    keyboard = []

    years = list(
        range(
            current_year,
            2009,
            -1,
        )
    )

    row = []

    for year in years:

        row.append(
            InlineKeyboardButton(
                str(year),
                callback_data=f"year:{year}",
            )
        )

        if len(row) == 3:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ بازگشت",
                callback_data="discover",
            )
        ]
    )

    await query.edit_message_text(
        "📅 <b>سال بازی را انتخاب کن:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# =========================================================
# GENRES
# =========================================================

async def show_genres(
    query,
):

    keyboard = []

    items = list(
        GENRES.items()
    )

    row = []

    for genre_id, name in items:

        row.append(
            InlineKeyboardButton(
                name,
                callback_data=(
                    f"genre:{genre_id}"
                ),
            )
        )

        if len(row) == 2:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ بازگشت",
                callback_data="discover",
            )
        ]
    )

    await query.edit_message_text(
        "🎯 <b>ژانر بازی:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# =========================================================
# PLATFORMS
# =========================================================

async def show_platforms(
    query,
):

    keyboard = []

    items = list(
        PLATFORMS.items()
    )

    row = []

    for platform_id, name in items:

        row.append(
            InlineKeyboardButton(
                name,
                callback_data=(
                    f"platform:{platform_id}"
                ),
            )
        )

        if len(row) == 2:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ بازگشت",
                callback_data="discover",
            )
        ]
    )

    await query.edit_message_text(
        "💻 <b>پلتفرم را انتخاب کن:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# =========================================================
# LIST GAMES
# =========================================================

async def show_games(
    query,
    games,
    title: str,
    page: int = 1,
    source: str = "popular",
):

    if not games:

        await query.edit_message_text(
            "❌ بازی‌ای پیدا نشد.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ بازگشت",
                            callback_data="discover",
                        )
                    ]
                ]
            ),
        )

        return

    keyboard = []

    for game in games:

        game_id = game.get(
            "id"
        )

        name = game.get(
            "name",
            "Unknown",
        )

        keyboard.append(
            [
                InlineKeyboardButton(
                    f"🎮 {name[:45]}",
                    callback_data=(
                        f"game:{game_id}"
                    ),
                )
            ]
        )

    navigation = []

    if page > 1:
        navigation.append(
            InlineKeyboardButton(
                "⬅️ قبلی",
                callback_data=(
                    f"page:{source}:{page - 1}"
                ),
            )
        )

    if len(games) == 10:
        navigation.append(
            InlineKeyboardButton(
                "بعدی ➡️",
                callback_data=(
                    f"page:{source}:{page + 1}"
                ),
            )
        )

    if navigation:
        keyboard.append(navigation)

    keyboard.append(
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="home",
            )
        ]
    )

    await query.edit_message_text(
        title,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# =========================================================
# GAME DETAILS
# =========================================================

async def show_game_details(
    query,
    game_id: int,
):

    try:

        game = game_service.get_game_details(
            game_id
        )

        if not game:

            await query.edit_message_text(
                "❌ اطلاعات بازی پیدا نشد."
            )

            return

        name = html.escape(
            game.get(
                "name",
                "Unknown",
            )
        )

        summary = (
            game.get(
                "summary"
            )
            or game.get(
                "storyline"
            )
            or "توضیحی ثبت نشده است."
        )

        summary = html.escape(
            summary
        )

        genres = game_service.get_genres(
            game
        )

        platforms = game_service.get_platforms(
            game
        )

        developers = game_service.get_developers(
            game
        )

        publishers = game_service.get_publishers(
            game
        )

        rating = game.get(
            "rating"
        )

        aggregated_rating = game.get(
            "aggregated_rating"
        )

        release_timestamp = game.get(
            "first_release_date"
        )

        release_date = "نامشخص"

        if release_timestamp:

            release_date = datetime.fromtimestamp(
                release_timestamp
            ).strftime(
                "%Y-%m-%d"
            )

        genres_text = (
            "، ".join(genres)
            if genres
            else "نامشخص"
        )

        platforms_text = (
            "، ".join(platforms)
            if platforms
            else "نامشخص"
        )

        developers_text = (
            "، ".join(developers)
            if developers
            else "نامشخص"
        )

        publishers_text = (
            "، ".join(publishers)
            if publishers
            else "نامشخص"
        )

        intro = game_agent.describe_game(
            title=game.get(
                "name",
                "Unknown",
            ),
            genre=genres_text,
            description=game.get(
                "summary"
            )
            or game.get(
                "storyline"
            )
            or "",
            platforms=platforms,
        )

        intro = html.escape(
            intro
        )

        favorite = is_favorite(
            query.from_user.id,
            game_id,
        )

        favorite_text = (
            "💔 حذف از علاقه‌مندی‌ها"
            if favorite
            else "❤️ افزودن به علاقه‌مندی‌ها"
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    favorite_text,
                    callback_data=(
                        f"favorite:{game_id}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "🔔 اعلان انتشار",
                    callback_data=(
                        f"follow:{game_id}"
                    ),
                )
            ],
        ]

        store_links = (
            game_service.get_store_links(
                game
            )
        )

        for store_name, url in store_links[:5]:

            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"🔗 {store_name}",
                        url=url,
                    )
                ]
            )

        official = (
            game_service.get_official_website(
                game
            )
        )

        if official:

            keyboard.append(
                [
                    InlineKeyboardButton(
                        "🌐 وب‌سایت رسمی",
                        url=official,
                    )
                ]
            )

        keyboard.append(
            [
                InlineKeyboardButton(
                    "⬅️ بازگشت",
                    callback_data="discover",
                ),
                InlineKeyboardButton(
                    "🏠 خانه",
                    callback_data="home",
                ),
            ]
        )

        rating_text = (
            f"{rating:.1f}"
            if isinstance(
                rating,
                (int, float),
            )
            else "N/A"
        )

        critic_text = (
            f"{aggregated_rating:.1f}"
            if isinstance(
                aggregated_rating,
                (int, float),
            )
            else "N/A"
        )

        text = (
            f"🎮 <b>{name}</b>\n\n"
            f"⭐ امتیاز کاربران: "
            f"<b>{rating_text}</b>\n"
            f"🏆 امتیاز منتقدان: "
            f"<b>{critic_text}</b>\n"
            f"📅 انتشار: "
            f"<b>{release_date}</b>\n"
            f"🎯 ژانر: "
            f"{html.escape(genres_text)}\n"
            f"💻 پلتفرم: "
            f"{html.escape(platforms_text)}\n\n"
            f"🧠 <b>معرفی بازی</b>\n"
            f"{intro}\n\n"
            f"📖 <b>توضیحات</b>\n"
            f"{summary[:2500]}\n\n"
            f"👨‍💻 سازنده: "
            f"{html.escape(developers_text)}\n"
            f"🏢 ناشر: "
            f"{html.escape(publishers_text)}"
        )

        cover_url = (
            game_service.get_cover_url(
                game
            )
        )

        if cover_url:

            try:

                await query.message.reply_photo(
                    photo=cover_url,
                    caption=text[:1024],
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(
                        keyboard
                    ),
                )

                return

            except Exception as error:

                logger.warning(
                    "Cover send failed: %s",
                    error,
                )

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )

    except Exception as error:

        logger.exception(
            "Game details error"
        )

        await query.edit_message_text(
            "❌ هنگام دریافت اطلاعات بازی "
            "خطایی رخ داد.\n\n"
            f"<code>{html.escape(str(error))}</code>",
            parse_mode=ParseMode.HTML,
        )


# =========================================================
# FAVORITES
# =========================================================

async def show_favorites(
    query,
):

    rows = get_favorites(
        query.from_user.id
    )

    if not rows:

        await query.edit_message_text(
            "❤️ هنوز بازی‌ای به "
            "علاقه‌مندی‌ها اضافه نکردی.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🎮 کشف بازی",
                            callback_data="discover",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🏠 خانه",
                            callback_data="home",
                        )
                    ],
                ]
            ),
        )

        return

    keyboard = []

    for row in rows:

        keyboard.append(
            [
                InlineKeyboardButton(
                    f"❤️ {row['game_name'][:45]}",
                    callback_data=(
                        f"game:{row['game_id']}"
                    ),
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "🏠 خانه",
                callback_data="home",
            )
        ]
    )

    await query.edit_message_text(
        "❤️ <b>علاقه‌مندی‌های شما</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# =========================================================
# CALLBACK
# =========================================================

async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    data = query.data

    try:

        # -------------------------
        # HOME
        # -------------------------

        if data == "home":

            await query.edit_message_text(
                "🎮 <b>Game Discovery Agent</b>\n\n"
                "چه کاری می‌خوای انجام بدی؟",
                parse_mode=ParseMode.HTML,
                reply_markup=main_menu(),
            )

            return

        # -------------------------
        # DISCOVER
        # -------------------------

        if data == "discover":

            await show_discover(
                query
            )

            return

        # -------------------------
        # YEARS
        # -------------------------

        if data == "years":

            await show_years(
                query
            )

            return

        # -------------------------
        # GENRES
        # -------------------------

        if data == "genres":

            await show_genres(
                query
            )

            return

        # -------------------------
        # PLATFORMS
        # -------------------------

        if data == "platforms":

            await show_platforms(
                query
            )

            return

        # -------------------------
        # POPULAR
        # -------------------------

        if data == "popular":

            games = (
                game_service.get_popular_games(
                    page=1,
                    page_size=10,
                )
            )

            await show_games(
                query,
                games,
                "🔥 <b>محبوب‌ترین بازی‌ها</b>",
                source="popular",
            )

            return

        # -------------------------
        # UPCOMING
        # -------------------------

        if data == "upcoming":

            games = (
                game_service.get_upcoming_games(
                    page=1,
                    page_size=10,
                )
            )

            await show_games(
                query,
                games,
                "🚀 <b>بازی‌های آینده</b>",
                source="upcoming",
            )

            return

        # -------------------------
        # FAVORITES
        # -------------------------

        if data == "favorites":

            await show_favorites(
                query
            )

            return

        # -------------------------
        # YEAR
        # -------------------------

        if data.startswith(
            "year:"
        ):

            year = int(
                data.split(
                    ":",
                    1,
                )[1]
            )

            games = (
                game_service.get_games_by_year(
                    year=year,
                    page=1,
                    page_size=10,
                )
            )

            context.user_data[
                "last_source"
            ] = f"year:{year}"

            await show_games(
                query,
                games,
                (
                    f"📅 <b>بازی‌های "
                    f"{year}</b>"
                ),
                source=f"year:{year}",
            )

            return

        # -------------------------
        # GENRE
        # -------------------------

        if data.startswith(
            "genre:"
        ):

            genre_id = int(
                data.split(
                    ":",
                    1,
                )[1]
            )

            genre_name = GENRES.get(
                str(genre_id),
                "ژانر",
            )

            games = (
                game_service.get_games_by_genre(
                    genre_id=genre_id,
                    page=1,
                    page_size=10,
                )
            )

            await show_games(
                query,
                games,
                f"🎯 <b>{genre_name}</b>",
                source=f"genre:{genre_id}",
            )

            return

        # -------------------------
        # PLATFORM
        # -------------------------

        if data.startswith(
            "platform:"
        ):

            platform_id = int(
                data.split(
                    ":",
                    1,
                )[1]
            )

            platform_name = PLATFORMS.get(
                str(platform_id),
                "پلتفرم",
            )

            games = (
                game_service.get_games_by_platform(
                    platform_id=platform_id,
                    page=1,
                    page_size=10,
                )
            )

            await show_games(
                query,
                games,
                f"💻 <b>{platform_name}</b>",
                source=f"platform:{platform_id}",
            )

            return

        # -------------------------
        # GAME
        # -------------------------

        if data.startswith(
            "game:"
        ):

            game_id = int(
                data.split(
                    ":",
                    1,
                )[1]
            )

            await show_game_details(
                query,
                game_id,
            )

            return

        # -------------------------
        # FAVORITE
        # -------------------------

        if data.startswith(
            "favorite:"
        ):

            game_id = int(
                data.split(
                    ":",
                    1,
                )[1]
            )

            game = (
                game_service.get_game_details(
                    game_id
                )
            )

            if not game:
                return

            game_name = game.get(
                "name",
                "Unknown",
            )

            if is_favorite(
                query.from_user.id,
                game_id,
            ):

                remove_favorite(
                    query.from_user.id,
                    game_id,
                )

                await query.answer(
                    "💔 از علاقه‌مندی‌ها حذف شد.",
                    show_alert=False,
                )

            else:

                add_favorite(
                    query.from_user.id,
                    game_id,
                    game_name,
                )

                await query.answer(
                    "❤️ به علاقه‌مندی‌ها اضافه شد.",
                    show_alert=False,
                )

            return

        # -------------------------
        # FOLLOW
        # -------------------------

        if data.startswith(
            "follow:"
        ):

            game_id = int(
                data.split(
                    ":",
                    1,
                )[1]
            )

            game = (
                game_service.get_game_details(
                    game_id
                )
            )

            if not game:
                return

            release_timestamp = game.get(
                "first_release_date"
            )

            release_date = None

            if release_timestamp:

                release_date = datetime.fromtimestamp(
                    release_timestamp
                ).strftime(
                    "%Y-%m-%d"
                )

            follow_game(
                query.from_user.id,
                game_id,
                game.get(
                    "name",
                    "Unknown",
                ),
                release_date,
            )

            await query.answer(
                "🔔 اعلان این بازی فعال شد.",
                show_alert=True,
            )

            return

        # -------------------------
        # PAGINATION
        # -------------------------

        if data.startswith(
            "page:"
        ):

            parts = data.split(
                ":"
            )

            source = parts[1]
            page = int(
                parts[2]
            )

            games = []

            if source == "popular":

                games = (
                    game_service.get_popular_games(
                        page=page,
                        page_size=10,
                    )
                )

                title = (
                    "🔥 <b>محبوب‌ترین بازی‌ها</b>"
                )

            elif source == "upcoming":

                games = (
                    game_service.get_upcoming_games(
                        page=page,
                        page_size=10,
                    )
                )

                title = (
                    "🚀 <b>بازی‌های آینده</b>"
                )

            elif source.startswith(
                "year:"
            ):

                year = int(
                    source.split(
                        ":"
                    )[1]
                )

                games = (
                    game_service.get_games_by_year(
                        year=year,
                        page=page,
                        page_size=10,
                    )
                )

                title = (
                    f"📅 <b>بازی‌های "
                    f"{year}</b>"
                )

            elif source.startswith(
                "genre:"
            ):

                genre_id = int(
                    source.split(
                        ":"
                    )[1]
                )

                games = (
                    game_service.get_games_by_genre(
                        genre_id=genre_id,
                        page=page,
                        page_size=10,
                    )
                )

                title = (
                    f"🎯 <b>"
                    f"{GENRES.get(str(genre_id), 'ژانر')}"
                    f"</b>"
                )

            elif source.startswith(
                "platform:"
            ):

                platform_id = int(
                    source.split(
                        ":"
                    )[1]
                )

                games = (
                    game_service.get_games_by_platform(
                        platform_id=platform_id,
                        page=page,
                        page_size=10,
                    )
                )

                title = (
                    f"💻 <b>"
                    f"{PLATFORMS.get(str(platform_id), 'پلتفرم')}"
                    f"</b>"
                )

            else:

                return

            await show_games(
                query,
                games,
                title,
                page=page,
                source=source,
            )

            return

    except Exception as error:

        logger.exception(
            "Callback error"
        )

        try:

            await query.edit_message_text(
                "❌ خطایی رخ داد.\n\n"
                f"<code>{html.escape(str(error))}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=main_menu(),
            )

        except Exception:
            pass


# =========================================================
# ERROR
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.exception(
        "Unhandled exception",
        exc_info=context.error,
    )


# =========================================================
# MAIN
# =========================================================

def main():

    global game_service

    if not TELEGRAM_BOT_TOKEN:

        raise ValueError(
            "TELEGRAM_BOT_TOKEN تنظیم نشده است."
        )

    init_database()

    game_service = GameService()

    application = (
        Application.builder()
        .token(
            TELEGRAM_BOT_TOKEN
        )
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "🎮 Game Discovery Agent is running..."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()