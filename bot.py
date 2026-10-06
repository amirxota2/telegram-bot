from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from config import TELEGRAM_BOT_TOKEN
from database import init_database

from tools import (
    search_games,
    choose_best_match,
    get_game_details,
)

from agent import GameAgent


# =========================================================
# Agent
# =========================================================

agent = GameAgent()


# =========================================================
# User Sessions
# =========================================================

user_sessions = {}


# =========================================================
# Game Categories
# =========================================================

# ID کوتاه برای callback_data
# نام فارسی برای نمایش به کاربر

GAME_CATEGORIES = [
    ("action", "⚔️ اکشن"),
    ("adventure", "🗺️ ماجراجویی"),
    ("rpg", "🧙 نقش‌آفرینی"),
    ("strategy", "♟️ استراتژی"),
    ("simulation", "🏗️ شبیه‌سازی"),
    ("sports", "⚽ ورزشی"),
    ("racing", "🏎️ مسابقه‌ای"),
    ("shooter", "🔫 تیراندازی"),
    ("horror", "👻 ترسناک"),
    ("puzzle", "🧩 معمایی"),
    ("fighting", "🥊 مبارزه‌ای"),
    ("platformer", "🎮 پلتفرمر"),
    ("survival", "🧟 بقا"),
    ("roguelike", "🎲 روگ‌لایک"),
    ("mmo", "🌐 MMO"),
    ("casual", "☕ کژوال"),
]


# تعداد دسته‌ها در هر صفحه
CATEGORIES_PER_PAGE = 6


# =========================================================
# Category Helper
# =========================================================

def get_total_pages():
    return (
        len(GAME_CATEGORIES)
        + CATEGORIES_PER_PAGE
        - 1
    ) // CATEGORIES_PER_PAGE


def get_category_page(page: int):
    start = page * CATEGORIES_PER_PAGE

    end = start + CATEGORIES_PER_PAGE

    return GAME_CATEGORIES[start:end]


# =========================================================
# Category Keyboard
# =========================================================

def category_keyboard(page: int = 0):

    total_pages = get_total_pages()

    # محدود کردن صفحه
    if page < 0:
        page = 0

    if page >= total_pages:
        page = total_pages - 1

    categories = get_category_page(page)

    keyboard = []

    # دو ستون
    for i in range(
        0,
        len(categories),
        2,
    ):

        row = []

        for category_id, category_name in categories[
            i:i + 2
        ]:

            row.append(
                InlineKeyboardButton(
                    category_name,
                    callback_data=f"genre:{category_id}",
                )
            )

        keyboard.append(row)

    # Navigation
    navigation = []

    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                "⬅️ قبلی",
                callback_data=f"catpage:{page - 1}",
            )
        )

    navigation.append(
        InlineKeyboardButton(
            f"📄 {page + 1}/{total_pages}",
            callback_data="catpage:current",
        )
    )

    if page < total_pages - 1:
        navigation.append(
            InlineKeyboardButton(
                "بعدی ➡️",
                callback_data=f"catpage:{page + 1}",
            )
        )

    keyboard.append(navigation)

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# Game Action Keyboard
# =========================================================

def game_action_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎮 انتخاب بازی دیگر",
                callback_data="action:new_game",
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 تغییر دسته",
                callback_data="action:categories",
            )
        ],
    ])


# =========================================================
# Category Name From ID
# =========================================================

def get_category_name(category_id: str):

    for item_id, item_name in GAME_CATEGORIES:

        if item_id == category_id:
            return item_name

    return category_id


# =========================================================
# /start
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = update.effective_user.id

    user_sessions[user_id] = {
        "step": "choose_genre",
        "genre": None,
    }

    await update.message.reply_text(
        "🎮 خوش اومدی!\n\n"
        "اول مشخص کن دنبال چه نوع بازی‌ای هستی:\n\n"
        "💻 فقط بازی‌های کامپیوتری (Windows) "
        "بررسی می‌شن.\n\n"
        "یک دسته رو انتخاب کن:",
        reply_markup=category_keyboard(0),
    )


# =========================================================
# Category Pagination
# =========================================================

async def category_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    # دکمه شماره صفحه فعلی
    if query.data == "catpage:current":
        return

    page_text = query.data.replace(
        "catpage:",
        "",
    )

    try:
        page = int(page_text)

    except ValueError:
        return

    await query.edit_message_text(
        "🎮 نوع بازی موردنظرت رو انتخاب کن:\n\n"
        "💻 فقط بازی‌های Windows بررسی می‌شن.\n"
        f"📄 صفحه {page + 1} از {get_total_pages()}",
        reply_markup=category_keyboard(page),
    )


# =========================================================
# Category Selected
# =========================================================

async def category_selected(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    category_id = query.data.replace(
        "genre:",
        "",
    )

    genre = get_category_name(category_id)

    user_sessions[user_id] = {
        "step": "enter_game",
        "genre": genre,
        "genre_id": category_id,
    }

    await query.edit_message_text(
        f"✅ دسته انتخاب شد:\n\n"
        f"{genre}\n\n"
        " پیشنهادی  بازی های 2026 🎮\n\n"
        "• Civilization VI\n"
        "• The Witcher 3\n"
        "• Elden Ring"
    )


# =========================================================
# Back To Categories
# =========================================================

async def back_to_categories(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    user_sessions[user_id] = {
        "step": "choose_genre",
        "genre": None,
    }

    await query.edit_message_text(
        "🎮 نوع بازی موردنظرت رو انتخاب کن:\n\n"
        "💻 فقط بازی‌های Windows بررسی می‌شن.\n\n"
        f"📄 صفحه 1 از {get_total_pages()}",
        reply_markup=category_keyboard(0),
    )


# =========================================================
# Choose Another Game
# =========================================================

async def choose_another_game(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    session = user_sessions.get(user_id)

    if not session:

        user_sessions[user_id] = {
            "step": "choose_genre",
            "genre": None,
        }

        await query.edit_message_text(
            "🎮 اول یک دسته بازی انتخاب کن:",
            reply_markup=category_keyboard(0),
        )

        return

    genre = session.get("genre")

    user_sessions[user_id] = {
        "step": "enter_game",
        "genre": genre,
        "genre_id": session.get(
            "genre_id"
        ),
    }

    await query.edit_message_text(
        f"🎮 دسته فعلی:\n"
        f"{genre}\n\n"
        "اسم بازی بعدی رو بفرست:"
    )


# =========================================================
# Handle Game Name
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = update.effective_user.id

    message = update.message.text.strip()

    # =====================================================
    # User Search Log
    # =====================================================

    username = update.effective_user.username or "بدون username"
    first_name = update.effective_user.first_name or "بدون نام"

    print(
        f"🔎 SEARCH | "
        f"user={first_name} | "
        f"username=@{username} | "
        f"id={user_id} | "
        f"query={message}",
        flush=True,
    )

    # =====================================================
    # Session
    # =====================================================

    session = user_sessions.get(
        user_id
    )

    # کاربر هنوز /start نزده
    if not session:

        await update.message.reply_text(
            "اول /start رو بزن تا شروع کنیم."
        )

        return

    # هنوز دسته انتخاب نشده
    if session["step"] != "enter_game":

        await update.message.reply_text(
            "اول یک دسته بازی انتخاب کن."
        )

        return

    genre = session["genre"]

    searching_message = (
        await update.message.reply_text(
            "🔎 دارم بین بازی‌های PC می‌گردم..."
        )
    )

    try:

        # =================================================
        # Search
        # =================================================

        games = search_games(
            message,
            limit=24,
        )

        if not games:

            await searching_message.edit_text(
                "❌ بازی مناسبی برای PC پیدا نکردم.\n\n"
                "اسم بازی رو دقیق‌تر بفرست."
            )

            return

        # =================================================
        # Best Match
        # =================================================

        game = choose_best_match(
            games,
            message,
        )

        if not game:

            await searching_message.edit_text(
                "❌ بازی پیدا نشد."
            )

            return

        title = game.get(
            "title",
            message,
        )

        slug = game.get(
            "slug"
        )

        if not slug:

            await searching_message.edit_text(
                "❌ شناسه بازی پیدا نشد."
            )

            return

        # =================================================
        # Full Details
        # =================================================

        details = get_game_details(
            slug
        )

        if not details:
            details = game

        description = details.get(
            "description",
            game.get(
                "description",
                "",
            ),
        )

        platforms = details.get(
            "platforms",
            game.get(
                "platforms",
                [],
            ),
        )

        cover_url = (
            details.get(
                "coverImageUrl"
            )
            or game.get(
                "coverImageUrl"
            )
        )

        game_url = (
            details.get(
                "url"
            )
            or game.get(
                "url"
            )
        )

        popularity = game.get(
            "_popularity",
            {},
        )

        owners = popularity.get(
            "owners",
            0,
        )

        # =================================================
        # Qwen Introduction
        # =================================================

        introduction = (
            agent.describe_game(
                title=title,
                genre=genre,
                description=description,
                platforms=platforms,
            )
        )

        # حذف پیام در حال جستجو
        await searching_message.delete()

        # =================================================
        # Message 1
        # =================================================

        popularity_text = ""

        if owners > 0:

            popularity_text = (
                "\n\n🔥 این بازی در بین "
                "بازی‌های محبوب Steam قرار دارد."
            )

        await update.message.reply_text(
            f"🎮 {title}\n\n"
            f"{introduction}"
            f"{popularity_text}",
            reply_markup=game_action_keyboard(),
        )

        # =================================================
        # Message 2 - Image + Link
        # =================================================

        if cover_url:

            caption = (
                f"🖼️ {title}"
            )

            if game_url:

                caption += (
                    f"\n\n🔗 لینک بازی:\n"
                    f"{game_url}"
                )

            await update.message.reply_photo(
                photo=cover_url,
                caption=caption,
            )

        elif game_url:

            await update.message.reply_text(
                f"🔗 لینک بازی:\n"
                f"{game_url}"
            )

        # حفظ دسته فعلی
        user_sessions[user_id] = {
            "step": "enter_game",
            "genre": genre,
            "genre_id": session.get(
                "genre_id"
            ),
        }

    except Exception as error:

        print(
            f"Game error: {error}",
            flush=True,
        )

        await update.message.reply_text(
            "❌ هنگام دریافت اطلاعات بازی "
            "مشکلی پیش آمد."
        )


# =========================================================
# Main
# =========================================================

def main():

    if not TELEGRAM_BOT_TOKEN:

        raise ValueError(
            "TELEGRAM_BOT_TOKEN "
            "در فایل .env تنظیم نشده است."
        )

    init_database()

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    # /start
    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    # صفحه‌بندی دسته‌ها
    app.add_handler(
        CallbackQueryHandler(
            category_page,
            pattern=r"^catpage:",
        )
    )

    # انتخاب دسته
    app.add_handler(
        CallbackQueryHandler(
            category_selected,
            pattern=r"^genre:",
        )
    )

    # برگشت به دسته‌ها
    app.add_handler(
        CallbackQueryHandler(
            back_to_categories,
            pattern=r"^action:categories$",
        )
    )

    # انتخاب بازی دیگر
    app.add_handler(
        CallbackQueryHandler(
            choose_another_game,
            pattern=r"^action:new_game$",
        )
    )

    # پیام‌های متنی
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    print(
        "🤖 Game Agent Bot is running...",
        flush=True,
    )

    app.run_polling()


if __name__ == "__main__":
    main()