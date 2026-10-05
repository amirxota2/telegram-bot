import re
import time

import requests


GAMELEGEND_BASE_URL = "https://www.gamelegend.com/api/v1"
STEAMSPY_BASE_URL = "https://steamspy.com/api.php"

REQUEST_TIMEOUT = 15

# کش محبوب‌ترین بازی‌های Steam
_steam_cache = {
    "owned": {
        "data": [],
        "time": 0,
    },
    "recent": {
        "data": [],
        "time": 0,
    },
}

CACHE_SECONDS = 60 * 60 * 24


def normalize_title(title: str) -> str:
    """
    برای مقایسه نام بازی‌ها.
    """
    if not title:
        return ""

    title = title.lower().strip()

    title = re.sub(
        r"[^a-z0-9\u0600-\u06ff]+",
        " ",
        title,
    )

    title = re.sub(
        r"\s+",
        " ",
        title,
    )

    return title.strip()


def get_gamelegend_games(
    query: str,
    limit: int = 24,
):
    """
    جستجوی بازی در GameLegend.
    """
    response = requests.get(
        f"{GAMELEGEND_BASE_URL}/games",
        params={
            "q": query,
            "limit": limit,
        },
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    return data.get("games", [])


def get_game_details(slug: str):
    """
    گرفتن اطلاعات کامل یک بازی.
    """
    response = requests.get(
        f"{GAMELEGEND_BASE_URL}/games/{slug}",
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    return data.get("game")


def get_steam_top_owned():
    """
    محبوب‌ترین بازی‌ها از نظر estimated owners در Steam Spy.
    """
    now = time.time()

    cached = _steam_cache["owned"]

    if (
        cached["data"]
        and now - cached["time"] < CACHE_SECONDS
    ):
        return cached["data"]

    response = requests.get(
        STEAMSPY_BASE_URL,
        params={
            "request": "top100owned",
        },
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict):
        games = list(data.values())
    elif isinstance(data, list):
        games = data
    else:
        games = []

    cached["data"] = games
    cached["time"] = now

    return games


def get_steam_top_recent():
    """
    محبوب‌ترین بازی‌ها از نظر بازیکن در دو هفته اخیر.
    """
    now = time.time()

    cached = _steam_cache["recent"]

    if (
        cached["data"]
        and now - cached["time"] < CACHE_SECONDS
    ):
        return cached["data"]

    response = requests.get(
        STEAMSPY_BASE_URL,
        params={
            "request": "top100in2weeks",
        },
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict):
        games = list(data.values())
    elif isinstance(data, list):
        games = data
    else:
        games = []

    cached["data"] = games
    cached["time"] = now

    return games


def parse_owner_range(value):
    """
    Steam Spy معمولاً owners را به شکل بازه برمی‌گرداند.
    مثلاً:
        20000 .. 50000
    یا:
        0 .. 20000

    برای مرتب‌سازی، وسط بازه را محاسبه می‌کنیم.
    """

    if value is None:
        return 0

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value)

    numbers = re.findall(
        r"[\d,]+",
        text,
    )

    if not numbers:
        return 0

    values = [
        int(number.replace(",", ""))
        for number in numbers
    ]

    if len(values) == 1:
        return float(values[0])

    return (values[0] + values[1]) / 2


def popularity_score(game):
    """
    از estimated owners به عنوان شاخص محبوبیت استفاده می‌کنیم.
    """
    return parse_owner_range(
        game.get("owners")
    )


def get_popularity_database():
    """
    دو منبع محبوبیت را می‌گیریم و با هم ترکیب می‌کنیم.
    """
    owned = get_steam_top_owned()
    recent = get_steam_top_recent()

    popularity = {}

    for game in owned:
        name = normalize_title(
            game.get("name", "")
        )

        if not name:
            continue

        popularity[name] = {
            "owners": parse_owner_range(
                game.get("owners")
            ),
            "recent_players": 0,
        }

    for game in recent:
        name = normalize_title(
            game.get("name", "")
        )

        if not name:
            continue

        if name not in popularity:
            popularity[name] = {
                "owners": 0,
                "recent_players": 0,
            }

        popularity[name]["recent_players"] = (
            game.get("ccu", 0) or 0
        )

    return popularity


def add_popularity_to_games(games):
    """
    فقط بازی‌های Windows را نگه می‌دارد
    و محبوبیت تقریبی Steam را به آن‌ها اضافه می‌کند.
    """

    popularity = get_popularity_database()

    result = []

    for game in games:

        platforms = game.get(
            "platforms",
            [],
        )

        # فقط PC / Windows
        if "Windows" not in platforms:
            continue

        title = game.get(
            "title",
            "",
        )

        normalized = normalize_title(
            title
        )

        pop = popularity.get(
            normalized,
            {
                "owners": 0,
                "recent_players": 0,
            },
        )

        game_copy = dict(game)

        game_copy["_popularity"] = pop

        result.append(game_copy)

    # اول بازی‌هایی که Steam owners بیشتری دارند
    result.sort(
        key=lambda game: (
            game["_popularity"]["owners"],
            game["_popularity"]["recent_players"],
        ),
        reverse=True,
    )

    return result


def search_games(
    query: str,
    limit: int = 24,
):
    """
    جستجوی بازی:
    1. GameLegend
    2. حذف Android/iOS و بازی‌های غیر-Windows
    3. مرتب‌سازی بر اساس محبوبیت تقریبی Steam
    """

    games = get_gamelegend_games(
        query=query,
        limit=limit,
    )

    return add_popularity_to_games(
        games
    )


def choose_best_match(
    games,
    query: str,
):
    """
    بهترین تطبیق با اسم واردشده.
    """

    if not games:
        return None

    query_normalized = normalize_title(
        query
    )

    # exact match
    for game in games:
        title = normalize_title(
            game.get("title", "")
        )

        if title == query_normalized:
            return game

    # اسم واردشده داخل عنوان باشد
    for game in games:
        title = normalize_title(
            game.get("title", "")
        )

        if (
            query_normalized in title
            or title in query_normalized
        ):
            return game

    # در نهایت اولین نتیجه
    return games[0]