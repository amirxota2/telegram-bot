
import os
from datetime import datetime, timedelta, timezone
from typing import Any
 
import requests
 
from config import REQUEST_TIMEOUT
 
RAWG_BASE_URL = "https://api.rawg.io/api"
RAWG_API_KEY = os.getenv("RAWG_API_KEY", "")
 
# آیدی‌هایی که توی bot.py هست -> آیدی معادل در RAWG
GENRE_MAP = {
    4: 4,      # اکشن
    31: 3,     # ماجراجویی
    12: 5,     # RPG
    15: 10,    # استراتژی
    13: 14,    # شبیه‌سازی
    14: 15,    # ورزشی
    10: 1,     # مسابقه‌ای
    5: 2,      # شوتر
    6: 6,      # فایتینگ
    9: 7,      # پازل
    8: 83,     # پلتفرمر
    32: 51,    # ایندی
    33: 11,    # آرکید
}
 
PLATFORM_MAP = {
    6: 4,      # PC
    167: 187,  # PS5
    48: 18,    # PS4
    9: 16,     # PS3
    169: 186,  # Xbox Series
    49: 1,     # Xbox One
    12: 14,    # Xbox 360
    130: 7,    # Nintendo Switch
    3: 6,      # Linux
    14: 5,     # macOS
    34: 21,    # Android
    39: 3,     # iOS
}
 
 
class GameService:
 
    def __init__(self):
 
        if not RAWG_API_KEY:
            raise ValueError(
                "RAWG_API_KEY تنظیم نشده است."
            )
 
        self.session = requests.Session()
 
    # =========================================================
    # RAW REQUEST
    # =========================================================
 
    def _request(
        self,
        path: str,
        params: dict | None = None,
    ) -> Any:
 
        query = {"key": RAWG_API_KEY}
        query.update(params or {})
 
        response = self.session.get(
            f"{RAWG_BASE_URL}/{path.lstrip('/')}",
            params=query,
            timeout=REQUEST_TIMEOUT,
        )
 
        response.raise_for_status()
 
        return response.json()
 
    # =========================================================
    # NORMALIZE (خروجی RAWG -> همون فرمت قبلی)
    # =========================================================
 
    @staticmethod
    def _normalize(raw: dict) -> dict:
 
        timestamp = None
        released = raw.get("released")
 
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
 
        rating = raw.get("rating") or 0
 
        companies = []
 
        for item in raw.get("developers") or []:
            companies.append(
                {
                    "developer": True,
                    "publisher": False,
                    "company": {"name": item.get("name")},
                }
            )
 
        for item in raw.get("publishers") or []:
            companies.append(
                {
                    "developer": False,
                    "publisher": True,
                    "company": {"name": item.get("name")},
                }
            )
 
        websites = []
 
        if raw.get("website"):
            websites.append(
                {
                    "url": raw["website"],
                    "type": 1,
                    "trusted": True,
                }
            )
 
        platforms = []
 
        for item in raw.get("platforms") or []:
            platform = item.get("platform") or {}
            platforms.append(
                {
                    "id": platform.get("id"),
                    "name": platform.get("name"),
                }
            )
 
        return {
            "id": raw.get("id"),
            "name": raw.get("name"),
            "summary": raw.get("description_raw") or "",
            "storyline": None,
            "first_release_date": timestamp,
            "rating": rating * 20 if rating else None,
            "aggregated_rating": raw.get("metacritic"),
            "genres": [
                {"name": g.get("name")}
                for g in raw.get("genres") or []
            ],
            "platforms": platforms,
            "cover_url": raw.get("background_image"),
            "involved_companies": companies,
            "websites": websites,
            "external_games": [],
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
        ordering: str = "-added",
        dates: str | None = None,
    ):
 
        params: dict[str, Any] = {
            "page": page,
            "page_size": page_size,
            "ordering": ordering,
            "exclude_additions": "true",
        }
 
        if year:
            params["dates"] = f"{year}-01-01,{year}-12-31"
 
        if dates:
            params["dates"] = dates
 
        if genre_id:
            params["genres"] = GENRE_MAP.get(
                int(genre_id),
                genre_id,
            )
 
        if platform_id:
            params["platforms"] = PLATFORM_MAP.get(
                int(platform_id),
                platform_id,
            )
 
        data = self._request("games", params)
 
        return [
            self._normalize(item)
            for item in data.get("results", [])
        ]
 
    # =========================================================
    # SEARCH
    # =========================================================
 
    def search_games(
        self,
        query_text: str,
        page: int = 1,
        page_size: int = 10,
    ):
 
        data = self._request(
            "games",
            {
                "search": query_text,
                "page": page,
                "page_size": page_size,
                "exclude_additions": "true",
            },
        )
 
        return [
            self._normalize(item)
            for item in data.get("results", [])
        ]
 
    # =========================================================
    # GAME DETAILS
    # =========================================================
 
    def get_game_details(
        self,
        game_id: int,
    ):
 
        try:
            raw = self._request(f"games/{game_id}")
        except requests.HTTPError as error:
            if (
                error.response is not None
                and error.response.status_code == 404
            ):
                return None
            raise
 
        game = self._normalize(raw)
 
        # لینک فروشگاه‌ها
        store_names = {}
 
        for item in raw.get("stores") or []:
            store = item.get("store") or {}
            if store.get("id"):
                store_names[store["id"]] = store.get("name")
 
        try:
            stores = self._request(
                f"games/{game_id}/stores"
            ).get("results", [])
        except Exception:
            stores = []
 
        game["external_games"] = [
            {
                "name": store_names.get(item.get("store_id")),
                "url": item.get("url"),
                "external_game_source": {
                    "name": store_names.get(
                        item.get("store_id")
                    )
                },
            }
            for item in stores
            if item.get("url")
        ]
 
        return game
 
    # =========================================================
    # POPULAR / YEAR / GENRE / PLATFORM
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
 
    # =========================================================
    # UPCOMING
    # =========================================================
 
    def get_upcoming_games(
        self,
        page: int = 1,
        page_size: int = 10,
    ):
 
        today = datetime.now(timezone.utc).date()
        end = today + timedelta(days=365)
 
        return self.get_games(
            page=page,
            page_size=page_size,
            ordering="released",
            dates=f"{today.isoformat()},{end.isoformat()}",
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
 
        return []
 
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
                    source.get("name")
                    or item.get("name")
                    or "Store",
                    url,
                )
            )
 
        return result