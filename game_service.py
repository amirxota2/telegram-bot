import time
from datetime import datetime, timezone
from typing import Any
 
import requests
 
from config import REQUEST_TIMEOUT
 
# FreeToGame: بدون کلید و بدون ثبت‌نام
FREETOGAME_BASE_URL = "https://www.freetogame.com/api"
CACHE_SECONDS = 3600
 
# آیدی ژانرهای bot.py -> دسته‌بندی FreeToGame
# (ژانرهایی که اینجا نیستن، مثل پازل و شبیه‌سازی، نتیجه‌ی خالی می‌دن)
GENRE_MAP = {
    4: "action",        # اکشن
    31: "open-world",   # ماجراجویی
    12: "mmorpg",       # RPG
    15: "strategy",     # استراتژی
    13: "sandbox",      # شبیه‌سازی
    14: "sports",       # ورزشی
    10: "racing",       # مسابقه‌ای
    5: "shooter",       # شوتر
    6: "fighting",      # فایتینگ
    8: "side-scroller", # پلتفرمر
    32: "pixel",        # ایندی
    33: "2d",           # آرکید
}
 
# FreeToGame فقط بازی‌های PC و مرورگر داره
PLATFORM_MAP = {
    6: "pc",
}
 
 
class GameService:
 
    def __init__(self):
 
        self.session = requests.Session()
        self._cache: dict = {}
 
    # =========================================================
    # RAW REQUEST (با کش یک‌ساعته)
    # =========================================================
 
    def _request(
        self,
        path: str,
        params: dict | None = None,
    ) -> Any:
 
        key = (
            path,
            tuple(sorted((params or {}).items())),
        )
 
        now = time.time()
        cached = self._cache.get(key)
 
        if cached and now - cached[0] < CACHE_SECONDS:
            return cached[1]
 
        response = self.session.get(
            f"{FREETOGAME_BASE_URL}/{path.lstrip('/')}",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
 
        response.raise_for_status()
 
        data = response.json()
 
        self._cache[key] = (now, data)
 
        return data
 
    # =========================================================
    # NORMALIZE (خروجی FreeToGame -> همون فرمت قبلی)
    # =========================================================
 
    @staticmethod
    def _normalize(raw: dict) -> dict:
 
        timestamp = None
        released = raw.get("release_date")
 
        if released:
            try:
                timestamp = int(
                    datetime.strptime(
                        released,
                        "%Y-%m-%d",
                    )
                    .replace(tzinfo=timezone.utc)
                    .timestamp()
                )
            except ValueError:
                timestamp = None
 
        companies = []
 
        if raw.get("developer"):
            companies.append(
                {
                    "developer": True,
                    "publisher": False,
                    "company": {"name": raw["developer"]},
                }
            )
 
        if raw.get("publisher"):
            companies.append(
                {
                    "developer": False,
                    "publisher": True,
                    "company": {"name": raw["publisher"]},
                }
            )
 
        links = []
 
        if raw.get("game_url"):
            links.append(
                {
                    "url": raw["game_url"],
                    "external_game_source": {
                        "name": "بازی کن (رایگان)"
                    },
                }
            )
 
        if raw.get("freetogame_profile_url"):
            links.append(
                {
                    "url": raw["freetogame_profile_url"],
                    "external_game_source": {
                        "name": "FreeToGame"
                    },
                }
            )
 
        screenshots = [
            item.get("image")
            for item in raw.get("screenshots") or []
            if item.get("image")
        ]
 
        return {
            "id": raw.get("id"),
            "name": raw.get("title"),
            "summary": (
                raw.get("description")
                or raw.get("short_description")
                or ""
            ),
            "storyline": None,
            "first_release_date": timestamp,
            "rating": None,
            "aggregated_rating": None,
            "genres": (
                [{"name": raw["genre"]}]
                if raw.get("genre")
                else []
            ),
            "platforms": (
                [{"name": raw["platform"]}]
                if raw.get("platform")
                else []
            ),
            "cover_url": raw.get("thumbnail"),
            "screenshot_urls": screenshots,
            "involved_companies": companies,
            "websites": [],
            "external_games": links,
        }
 
    # =========================================================
    # GAMES
    # =========================================================
 
    def get_games(
        self,
        page: int = 1,
        page_size: int = 10,
        year: int | None = None,
        genre_id: int | None = None,
        platform_id: int | None = None,
        sort_by: str = "popularity",
        upcoming: bool = False,
    ):
 
        params: dict[str, str] = {"sort-by": sort_by}
 
        if genre_id:
            category = GENRE_MAP.get(int(genre_id))
 
            if not category:
                return []
 
            params["category"] = category
 
        if platform_id:
            platform = PLATFORM_MAP.get(int(platform_id))
 
            if not platform:
                return []
 
            params["platform"] = platform
 
        data = self._request("games", params)
 
        if not isinstance(data, list):
            return []
 
        games = [self._normalize(item) for item in data]
 
        if year:
            games = [
                g
                for g in games
                if g["first_release_date"]
                and datetime.fromtimestamp(
                    g["first_release_date"],
                    tz=timezone.utc,
                ).year
                == int(year)
            ]
 
        if upcoming:
            now = time.time()
 
            games = [
                g
                for g in games
                if g["first_release_date"]
                and g["first_release_date"] >= now
            ]
 
            games.sort(key=lambda g: g["first_release_date"])
 
        start = (page - 1) * page_size
 
        return games[start:start + page_size]
 
    # =========================================================
    # SEARCH
    # =========================================================
 
    def search_games(
        self,
        query_text: str,
        page: int = 1,
        page_size: int = 10,
    ):
 
        data = self._request("games")
 
        if not isinstance(data, list):
            return []
 
        needle = query_text.strip().lower()
 
        games = [
            self._normalize(item)
            for item in data
            if needle in (item.get("title") or "").lower()
        ]
 
        start = (page - 1) * page_size
 
        return games[start:start + page_size]
 
    # =========================================================
    # GAME DETAILS
    # =========================================================
 
    def get_game_details(
        self,
        game_id: int,
    ):
 
        try:
            raw = self._request(
                "game",
                {"id": str(game_id)},
            )
        except requests.HTTPError as error:
            if (
                error.response is not None
                and error.response.status_code == 404
            ):
                return None
            raise
 
        if not isinstance(raw, dict) or not raw.get("id"):
            return None
 
        return self._normalize(raw)
 
    # =========================================================
    # POPULAR / YEAR / GENRE / PLATFORM / UPCOMING
    # =========================================================
 
    def get_popular_games(
        self,
        page: int = 1,
        page_size: int = 10,
    ):
 
        return self.get_games(
            page=page,
            page_size=page_size,
        )
 
    def get_games_by_year(
        self,
        year: int,
        page: int = 1,
        page_size: int = 10,
        genre_id: int | None = None,
        platform_id: int | None = None,
    ):
 
        return self.get_games(
            page=page,
            page_size=page_size,
            year=year,
            genre_id=genre_id,
            platform_id=platform_id,
        )
 
    def get_games_by_genre(
        self,
        genre_id: int,
        page: int = 1,
        page_size: int = 10,
        year: int | None = None,
        platform_id: int | None = None,
    ):
 
        return self.get_games(
            page=page,
            page_size=page_size,
            year=year,
            genre_id=genre_id,
            platform_id=platform_id,
        )
 
    def get_games_by_platform(
        self,
        platform_id: int,
        page: int = 1,
        page_size: int = 10,
        year: int | None = None,
        genre_id: int | None = None,
    ):
 
        return self.get_games(
            page=page,
            page_size=page_size,
            year=year,
            genre_id=genre_id,
            platform_id=platform_id,
        )
 
    def get_upcoming_games(
        self,
        page: int = 1,
        page_size: int = 10,
    ):
 
        return self.get_games(
            page=page,
            page_size=page_size,
            sort_by="release-date",
            upcoming=True,
        )
 
    # =========================================================
    # HELPERS (همون نام‌های قبلی)
    # =========================================================
 
    @staticmethod
    def get_cover_url(
        game: dict,
        size: str = "cover_big",
    ) -> str | None:
 
        return game.get("cover_url") or None
 
    @staticmethod
    def get_screenshot_urls(
        game: dict,
        size: str = "screenshot_big",
    ) -> list[str]:
 
        return game.get("screenshot_urls", [])
 
    @staticmethod
    def get_genres(game: dict) -> list[str]:
 
        return [
            g["name"]
            for g in game.get("genres", [])
            if g.get("name")
        ]
 
    @staticmethod
    def get_platforms(game: dict) -> list[str]:
 
        return [
            p["name"]
            for p in game.get("platforms", [])
            if p.get("name")
        ]
 
    @staticmethod
    def get_developers(game: dict) -> list[str]:
 
        return [
            c["company"]["name"]
            for c in game.get("involved_companies", [])
            if c.get("developer")
            and c.get("company", {}).get("name")
        ]
 
    @staticmethod
    def get_publishers(game: dict) -> list[str]:
 
        return [
            c["company"]["name"]
            for c in game.get("involved_companies", [])
            if c.get("publisher")
            and c.get("company", {}).get("name")
        ]
 
    @staticmethod
    def get_official_website(game: dict) -> str | None:
 
        for website in game.get("websites", []):
            if website.get("url"):
                return website["url"]
 
        return None
 
    @staticmethod
    def get_store_links(game: dict):
 
        result = []
 
        for item in game.get("external_games", []):
            url = item.get("url")
 
            if not url:
                continue
 
            source = item.get("external_game_source") or {}
 
            result.append(
                (
                    source.get("name") or "Link",
                    url,
                )
            )
 
        return result