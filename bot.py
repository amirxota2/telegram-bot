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

from config import (
    TELEGRAM_BOT_TOKEN,
)

from database import (
    add_favorite,
    follow_game,
    get_favorites,
    init_database,
    is_favorite,
    mark_notified,
    remove_favorite,
    save_user,
    unfollow_game,
    get_followed_games,
)

from game_service import GameService

from agent import GameAgent

from tools import (
    clean_text,
    get_developer_names,
    get_genre_names,
    get_platform_names,
    get_publisher_names,
    get_store_links,
    truncate,
)


# =========================================================
# Global services
# =========================================================

game_service = None
game_agent = GameAgent()


# =========================================================
# Sessions
# =========================================================

sessions = {}


# =========================================================
# Genres
# =========================================================

GENRES = {
    "action": "اکشن",
    "adventure": "ماجراجویی",
    "rpg": "نقش‌آفرینی",
    "strategy": "استراتژی",
    "simulation": "شبیه‌سازی",
    "sports": "ورزشی",
    "racing": "مسابقه‌ای",
    "shooter": "شوتر",
    "horror": "ترسناک",
    "puzzle": "پازل",
    "fighting": "مبارزه‌ای",
    "platformer": "پلتفرمر",
    "indie": "ایندی",
    "arcade": "آرکید",
    "casual": "کژوال",
    "family": "خانوادگی",
    "board-games": "بازی‌های رومیزی",
    "educational": "آموزشی",
    "massively-multiplayer": "آنلاین / MMO",
}


# =========================================================
# Platforms
# =========================================================

PLATFORMS = {
    4: "PC",
    187: "PS5",
    18: "PS4",
    16: "PS3",
    186: "Xbox Series",
    1: "Xbox One",
    14: "Xbox 360",
    7: "Nintendo Switch",
    6: "Linux",
    5: "macOS",
    21: "Android",
    3: "iOS",
}


# =========================================================
# Start
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
        ],
        [
            InlineKeyboardButton(
                "🔥 بازی‌های محبوب",
                callback_data="popular",
            ),
            InlineKeyboardButton(
                "📅 بازی‌های ۲۰۲۶",
                callback_data="year:2026",
            ),
        ],
        [
            InlineKeyboardButton(
                "🎯 انتخاب ژانر",
                callback_data="genres",
            ),
            InlineKeyboardButton(
                "💻 انتخاب پلتفرم",
                callback_data="platforms",
            ),
        ],
        [
            InlineKeyboardButton(
                "❤️ علاقه‌مندی‌ها",
                callback_data="favorites",
            ),
        ],
    ]

    text = """
🎮 <b>Game Discovery Agent</b>

به ربات کشف بازی خوش آمدی.

اینجا می‌توانی بازی‌ها را بر اساس:

🎯 ژانر
📅 سال انتشار
💻 پلتفرم
⭐ امتیاز
🔥 محبوبیت

پیدا کنی.

بعد از انتخاب هر بازی می‌توانی اطلاعات کامل،
لینک فروشگاه رسمی، علاقه‌مندی و اعلان انتشار
را ببینی.
"""

    if update.message:

        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )


# =========================================================
# Discover
# =========================================================

async def show_discover(
    query,
):

    keyboard = [
        [
            InlineKeyboardButton(
                "📅 انتخاب سال",
                callback_data="years",
            ),
        ],
        [
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
        ],
        [
            InlineKeyboardButton(
                "🔥 محبوب‌ترین‌ها",
                callback_data="popular",
            ),
        ],
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="home",
            ),
        ],
    ]

    await query.edit_message_text(
        "🎮 <b>کشف بازی</b>\n\n"
        "چطور می‌خواهی بازی پیدا کنی؟",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# =========================================================
# Years
# =========================================================

async def show_years(
    query,
):

    keyboard = []

    current_year = datetime.now().year

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
                "⬅️ برگشت",
                callback_data="discover",
            )
        ]
    )

    await query.edit_message_text(
        "📅 <b>سال انتشار را انتخاب کن:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# =========================================================
# Genres
# =========================================================

async def show_genres(
    query,
):

    keyboard = []

    row = []

    for slug, name in GENRES.items():

        row.append(
            InlineKeyboardButton(
                name,
                callback_data=f"genre:{slug}",
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
                "⬅️ برگشت",
                callback_data="discover",
            )
        ]
    )

    await query.edit_message_text(
        "🎯 <b>ژانر بازی را انتخاب کن:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# =========================================================
# Platforms
# =========================================================

async def show_platforms(
    query,
):

    keyboard = []

    row = []

    for platform_id, name in PLATFORMS.items():

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
                "⬅️ برگشت",
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
# Fetch games
# =========================================================

async def fetch_and_show_games(
    query,
    *,
    title: str,
    year: int | None = None,
    genre: str | None = None,
    platform: int | None = None,
    popular: bool = False,
    page: int = 1,
):

    await query.edit_message_text(
        "⏳ در حال دریافت بازی‌ها..."
    )

    try:

        if popular:

            data = game_service.get_popular_games(
                page=page,
                page_size=8,
            )

        elif year:

            data = game_service.get_games_by_year(
                year=year,
                page=page,
                page_size=8,
                genres=genre,
                platforms=(
                    str(platform)
                    if platform
                    else None
                ),
            )

        elif genre:

            data = game_service.get_games_by_genre(
                genre=genre,
                page=page,
                page_size=8,
                year=year,
            )

        elif platform:

            data = game_service.get_games_by_platform(
                platform_id=platform,
                page=page,
                page_size=8,
                year=year,
            )

        else:

            data = game_service.get_games(
                page=page,
                page_size=8,
            )

    except Exception as error:

        print(
            "RAWG ERROR:",
            error,
        )

        await query.edit_message_text(
            "❌ دریافت اطلاعات بازی‌ها انجام نشد.\n\n"
            "لطفاً چند لحظه بعد دوباره امتحان کن."
        )

        return

    games = data.get(
        "results",
        [],
    )

    if not games:

        await query.edit_message_text(
            "❌ بازی‌ای با این فیلتر پیدا نشد."
        )

        return

    sessions[
        query.from_user.id
    ] = {
        "games": games,
        "page": page,
        "year": year,
        "genre": genre,
        "platform": platform,
        "popular": popular,
        "title": title,
    }

    keyboard = []

    for game in games:

        game_id = game.get(
            "id"
        )

        name = game.get(
            "name",
            "Unknown",
        )

        rating = game.get(
            "rating"
        )

        if rating:

            button_text = (
                f"🎮 {name} ⭐ {rating}"
            )

        else:

            button_text = (
                f"🎮 {name}"
            )

        keyboard.append(
            [
                InlineKeyboardButton(
                    button_text[:60],
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
                callback_data="page:prev",
            )
        )

    if data.get("next"):

        navigation.append(
            InlineKeyboardButton(
                "بعدی ➡️",
                callback_data="page:next",
            )
        )

    if navigation:

        keyboard.append(
            navigation
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "🎮 فیلتر جدید",
                callback_data="discover",
            ),
            InlineKeyboardButton(
                "🏠 خانه",
                callback_data="home",
            ),
        ]
    )

    await query.edit_message_text(
        f"🎮 <b>{title}</b>\n\n"
        f"صفحه {page}\n"
        f"تعداد نتایج: {len(games)}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# =========================================================
# Game details
# =========================================================

async def show_game_details(
    query,
    game_id: int,
):

    await query.edit_message_text(
        "⏳ در حال دریافت اطلاعات کامل بازی..."
    )

    try:

        game = game_service.get_game_details(
            game_id
        )

    except Exception as error:

        print(
            "GAME DETAILS ERROR:",
            error,
        )

        await query.edit_message_text(
            "❌ اطلاعات بازی دریافت نشد."
        )

        return

    title = game.get(
        "name",
        "Unknown",
    )

    released = game.get(
        "released"
    ) or "نامشخص"

    rating = game.get(
        "rating"
    )

    metacritic = game.get(
        "metacritic"
    )

    genres = get_genre_names(
        game
    )

    platforms = get_platform_names(
        game
    )

    developers = get_developer_names(
        game
    )

    publishers = get_publisher_names(
        game
    )

    description = clean_text(
        game.get(
            "description_raw"
        )
    )

    if not description:

        description = (
            "توضیحی برای این بازی ثبت نشده است."
        )

    # معرفی با AI
    ai_description = game_agent.describe_game(
        title=title,
        genre=(
            "، ".join(genres)
            if genres
            else "نامشخص"
        ),
        description=description,
        platforms=platforms,
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

    stores = get_store_links(
        game
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

    if stores:

        for store_name, url in stores[:6]:

            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"🔗 {store_name}",
                        url=url,
                    )
                ]
            )

    website = game.get(
        "website"
    )

    if website:

        keyboard.append(
            [
                InlineKeyboardButton(
                    "🌐 سایت رسمی",
                    url=website,
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ برگشت",
                callback_data="back_games",
            ),
            InlineKeyboardButton(
                "🏠 خانه",
                callback_data="home",
            ),
        ]
    )

    rating_text = (
        str(rating)
        if rating is not None
        else "نامشخص"
    )

    metacritic_text = (
        str(metacritic)
        if metacritic is not None
        else "نامشخص"
    )

    genre_text = (
        "، ".join(genres)
        if genres
        else "نامشخص"
    )

    platform_text = (
        "، ".join(platforms)
        if platforms
        else "نامشخص"
    )

    developer_text = (
        "، ".join(developers)
        if developers
        else "نامشخص"
    )

    publisher_text = (
        "، ".join(publishers)
        if publishers
        else "نامشخص"
    )

    text = (
        f"🎮 <b>{title}</b>\n\n"

        f"⭐ امتیاز: <b>{rating_text}</b>\n"
        f"📊 Metacritic: <b>{metacritic_text}</b>\n"
        f"📅 انتشار: <b>{released}</b>\n\n"

        f"🎯 <b>ژانرها</b>\n"
        f"{genre_text}\n\n"

        f"💻 <b>پلتفرم‌ها</b>\n"
        f"{platform_text}\n\n"

        f"🏢 <b>سازنده</b>\n"
        f"{developer_text}\n\n"

        f"🏷 <b>ناشر</b>\n"
        f"{publisher_text}\n\n"

        f"📝 <b>معرفی</b>\n"
        f"{truncate(ai_description, 1200)}"
    )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
        disable_web_page_preview=False,
    )


# =========================================================
# Favorites
# =========================================================

async def show_favorites(
    query,
):

    favorites = get_favorites(
        query.from_user.id
    )

    if not favorites:

        keyboard = [
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

        await query.edit_message_text(
            "❤️ هنوز هیچ بازی‌ای به علاقه‌مندی‌ها اضافه نکرده‌ای.",
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )

        return

    keyboard = []

    for game in favorites:

        keyboard.append(
            [
                InlineKeyboardButton(
                    f"❤️ {game['game_name']}",
                    callback_data=(
                        f"game:{game['game_id']}"
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
        "❤️ <b>بازی‌های موردعلاقه</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# =========================================================
# Callback Handler
# =========================================================

async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    data = query.data

    user_id = query.from_user.id

    # -----------------------------
    # Home
    # -----------------------------

    if data == "home":

        await start_from_query(
            query
        )

        return

    # -----------------------------
    # Discover
    # -----------------------------

    if data == "discover":

        await show_discover(
            query
        )

        return

    # -----------------------------
    # Years
    # -----------------------------

    if data == "years":

        await show_years(
            query
        )

        return

    # -----------------------------
    # Genres
    # -----------------------------

    if data == "genres":

        await show_genres(
            query
        )

        return

    # -----------------------------
    # Platforms
    # -----------------------------

    if data == "platforms":

        await show_platforms(
            query
        )

        return

    # -----------------------------
    # Popular
    # -----------------------------

    if data == "popular":

        await fetch_and_show_games(
            query,
            title="🔥 بازی‌های محبوب",
            popular=True,
        )

        return

    # -----------------------------
    # Year
    # -----------------------------

    if data.startswith(
        "year:"
    ):

        year = int(
            data.split(":")[1]
        )

        await fetch_and_show_games(
            query,
            title=f"📅 بازی‌های {year}",
            year=year,
        )

        return

    # -----------------------------
    # Genre
    # -----------------------------

    if data.startswith(
        "genre:"
    ):

        genre = data.split(
            ":",
            1,
        )[1]

        genre_name = GENRES.get(
            genre,
            genre,
        )

        await fetch_and_show_games(
            query,
            title=(
                f"🎯 بازی‌های {genre_name}"
            ),
            genre=genre,
        )

        return

    # -----------------------------
    # Platform
    # -----------------------------

    if data.startswith(
        "platform:"
    ):

        platform_id = int(
            data.split(":")[1]
        )

        platform_name = PLATFORMS.get(
            platform_id,
            "Platform",
        )

        await fetch_and_show_games(
            query,
            title=(
                f"💻 بازی‌های {platform_name}"
            ),
            platform=platform_id,
        )

        return

    # -----------------------------
    # Game
    # -----------------------------

    if data.startswith(
        "game:"
    ):

        game_id = int(
            data.split(":")[1]
        )

        await show_game_details(
            query,
            game_id,
        )

        return

    # -----------------------------
    # Favorite
    # -----------------------------

    if data.startswith(
        "favorite:"
    ):

        game_id = int(
            data.split(":")[1]
        )

        try:

            game = game_service.get_game_details(
                game_id
            )

            game_name = game.get(
                "name",
                "Unknown",
            )

        except Exception:

            game_name = "Unknown"

        if is_favorite(
            user_id,
            game_id,
        ):

            remove_favorite(
                user_id,
                game_id,
            )

        else:

            add_favorite(
                user_id,
                game_id,
                game_name,
            )

        await show_game_details(
            query,
            game_id,
        )

        return

    # -----------------------------
    # Follow
    # -----------------------------

    if data.startswith(
        "follow:"
    ):

        game_id = int(
            data.split(":")[1]
        )

        try:

            game = game_service.get_game_details(
                game_id
            )

            game_name = game.get(
                "name",
                "Unknown",
            )

            release_date = game.get(
                "released"
            )

        except Exception:

            game_name = "Unknown"
            release_date = None

        follow_game(
            telegram_id=user_id,
            game_id=game_id,
            game_name=game_name,
            release_date=release_date,
        )

        await query.answer(
            "🔔 اعلان این بازی فعال شد.",
            show_alert=True,
        )

        return

    # -----------------------------
    # Favorites
    # -----------------------------

    if data == "favorites":

        await show_favorites(
            query
        )

        return

    # -----------------------------
    # Pagination
    # -----------------------------

    if data in (
        "page:next",
        "page:prev",
    ):

        session = sessions.get(
            user_id
        )

        if not session:

            await query.edit_message_text(
                "❌ اطلاعات صفحه قبلی منقضی شده است.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🎮 کشف بازی",
                                callback_data="discover",
                            )
                        ]
                    ]
                ),
            )

            return

        page = session["page"]

        if data == "page:next":

            page += 1

        else:

            page = max(
                1,
                page - 1,
            )

        await fetch_and_show_games(
            query,
            title=session["title"],
            year=session["year"],
            genre=session["genre"],
            platform=session["platform"],
            popular=session["popular"],
            page=page,
        )

        return

    # -----------------------------
    # Back to games
    # -----------------------------

    if data == "back_games":

        session = sessions.get(
            user_id
        )

        if not session:

            await show_discover(
                query
            )

            return

        await fetch_and_show_games(
            query,
            title=session["title"],
            year=session["year"],
            genre=session["genre"],
            platform=session["platform"],
            popular=session["popular"],
            page=session["page"],
        )

        return


# =========================================================
# Start from callback
# =========================================================

async def start_from_query(
    query,
):

    keyboard = [
        [
            InlineKeyboardButton(
                "🎮 کشف بازی‌ها",
                callback_data="discover",
            )
        ],
        [
            InlineKeyboardButton(
                "🔥 محبوب‌ترین‌ها",
                callback_data="popular",
            ),
            InlineKeyboardButton(
                "📅 بازی‌های ۲۰۲۶",
                callback_data="year:2026",
            ),
        ],
        [
            InlineKeyboardButton(
                "🎯 انتخاب ژانر",
                callback_data="genres",
            ),
            InlineKeyboardButton(
                "💻 انتخاب پلتفرم",
                callback_data="platforms",
            ),
        ],
        [
            InlineKeyboardButton(
                "❤️ علاقه‌مندی‌ها",
                callback_data="favorites",
            )
        ],
    ]

    await query.edit_message_text(
        "🎮 <b>Game Discovery Agent</b>\n\n"
        "یک گزینه را انتخاب کن:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# =========================================================
# Notification checker
# =========================================================

async def check_release_notifications(
    context: ContextTypes.DEFAULT_TYPE,
):

    today = datetime.now().date()

    rows = get_followed_games()

    for row in rows:

        release_date = row["release_date"]

        if not release_date:
            continue

        try:

            release = datetime.strptime(
                release_date,
                "%Y-%m-%d",
            ).date()

        except ValueError:

            continue

        if release > today:
            continue

        try:

            await context.bot.send_message(
                chat_id=row["telegram_id"],
                text=(
                    "🔔 <b>بازی منتشر شد!</b>\n\n"
                    f"🎮 <b>{row['game_name']}</b>\n\n"
                    f"📅 تاریخ انتشار: "
                    f"{release_date}"
                ),
                parse_mode=ParseMode.HTML,
            )

            mark_notified(
                row["id"]
            )

        except Exception as error:

            print(
                "NOTIFICATION ERROR:",
                error,
            )


# =========================================================
# Error Handler
# =========================================================

async def error_handler(
    update,
    context,
):

    print(
        "BOT ERROR:",
        context.error,
    )


# =========================================================
# Main
# =========================================================

def main():

    global game_service

    if not TELEGRAM_BOT_TOKEN:

        raise ValueError(
            "TELEGRAM_BOT_TOKEN تنظیم نشده است."
        )

    game_service = GameService()

    init_database()

    application = (
        Application
        .builder()
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
        CallbackQueryHandler(
            callback_handler
        )
    )

    application.add_error_handler(
        error_handler
    )

    # هر 6 ساعت وضعیت اعلان‌ها را بررسی می‌کند.
    if application.job_queue:

        application.job_queue.run_repeating(
            check_release_notifications,
            interval=21600,
            first=30,
        )

    print(
        "🤖 Game Discovery Agent is running..."
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()