import logging
from datetime import datetime, timezone

import requests

from .bace import GameProvider


logger = logging.getLogger(__name__)


class FreeToGameProvider(GameProvider):

    BASE_URL = "https://www.freetogame.com/api"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "GameRadarBot/1.0",
                "Accept": "application/json",
            }
        )

    # =========================================================
    # REQUEST
    # =========================================================

    def _request(self, endpoint: str, params: dict | None = None):

        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"

        try:
            response = self.session.get(
                url,
                params=params,
                timeout=20,
            )

            response.raise_for_status()

            return response.json()

        except requests.RequestException as exc:
            logger.error("FreeToGame API error: %s", exc)
            return None

        except ValueError as exc:
            logger.error("Invalid JSON response: %s", exc)
            return None

    # =========================================================
    # NORMALIZE GAME
    # =========================================================

    @staticmethod
    def _release_timestamp(release_date):

        if not release_date:
            return None

        try:
            dt = datetime.strptime(
                release_date,
                "%Y-%m-%d",
            ).replace(tzinfo=timezone.utc)

            return int(dt.timestamp())

        except (ValueError, TypeError):
            return None

    @staticmethod
    def _platform_name(platform):

        if not platform:
            return "نامشخص"

        platform = platform.lower()

        if "pc" in platform:
            return "PC"

        if "browser" in platform:
            return "Browser"

        return platform

    def _normalize_game(self, game: dict):

        if not game:
            return None

        developer = game.get("developer")
        publisher = game.get("publisher")

        involved_companies = []

        if developer:
            involved_companies.append(
                {
                    "developer": True,
                    "publisher": False,
                    "company": {
                        "name": developer,
                    },
                }
            )

        if publisher and publisher != developer:
            involved_companies.append(
                {
                    "developer": False,
                    "publisher": True,
                    "company": {
                        "name": publisher,
                    },
                }
            )

        screenshots = []

        for screenshot in game.get("screenshots", []) or []:

            image = screenshot.get("image")

            if image:
                screenshots.append(image)

        genre = game.get("genre")

        genres = []

        if genre:
            genres.append(
                {
                    "id": genre.lower(),
                    "name": genre,
                }
            )

        platform = self._platform_name(
            game.get("platform")
        )

        platforms = [
            {
                "id": platform.lower(),
                "name": platform,
            }
        ]

        game_url = game.get("game_url")

        profile_url = game.get(
            "freetogame_profile_url"
        )

        external_games = []

        if game_url:
            external_games.append(
                {
                    "url": game_url,
                    "external_game_source": {
                        "name": "Game Page",
                    },
                }
            )

        if profile_url:
            external_games.append(
                {
                    "url": profile_url,
                    "external_game_source": {
                        "name": "FreeToGame",
                    },
                }
            )

        return {
            "id": game.get("id"),
            "name": game.get("title") or "Unknown Game",

            "summary": (
                game.get("short_description")
                or "توضیحی برای این بازی ثبت نشده است."
            ),

            "storyline": "",

            "first_release_date": self._release_timestamp(
                game.get("release_date")
            ),

            "release_date": game.get("release_date"),

            "rating": None,
            "aggregated_rating": None,

            "genres": genres,
            "platforms": platforms,

            "involved_companies": involved_companies,

            "websites": (
                [{"url": game_url}]
                if game_url
                else []
            ),

            "external_games": external_games,

            "cover_url": game.get("thumbnail"),

            "screenshot_urls": screenshots,

            "developer": developer,
            "publisher": publisher,

            "game_url": game_url,
            "freetogame_profile_url": profile_url,

            "original_data": game,
        }

    # =========================================================
    # GET ALL GAMES
    # =========================================================

    def _get_all_games(
        self,
        platform: str | None = None,
        genre: str | None = None,
        sort_by: str | None = None,
    ):

        params = {}

        if platform and platform != "all":
            params["platform"] = platform

        if genre:
            params["category"] = genre

        if sort_by:
            params["sort-by"] = sort_by

        data = self._request(
            "games",
            params=params,
        )

        if not isinstance(data, list):
            return []

        return [
            normalized
            for game in data
            if (normalized := self._normalize_game(game))
        ]

    # =========================================================
    # GET GAMES
    # =========================================================

    def get_games(
        self,
        page: int = 1,
        page_size: int = 10,
        year: int | None = None,
        genre: str | None = None,
        platform: str | None = None,
        sort_by: str | None = None,
    ):

        games = self._get_all_games(
            platform=platform,
            genre=genre,
            sort_by=sort_by,
        )

        # -------------------------
        # YEAR FILTER
        # -------------------------

        if year:

            filtered = []

            for game in games:

                release_date = game.get(
                    "release_date"
                )

                if not release_date:
                    continue

                try:
                    release_year = int(
                        release_date[:4]
                    )

                except (ValueError, TypeError):
                    continue

                if release_year == int(year):
                    filtered.append(game)

            games = filtered

        # -------------------------
        # PAGINATION
        # -------------------------

        start = (page - 1) * page_size
        end = start + page_size

        return games[start:end]

    # =========================================================
    # SEARCH
    # =========================================================

    def search_games(
        self,
        query: str,
        page: int = 1,
        page_size: int = 10,
    ):

        query = (query or "").strip().lower()

        if not query:
            return []

        games = self._get_all_games()

        results = []

        for game in games:

            title = (
                game.get("name")
                or ""
            ).lower()

            summary = (
                game.get("summary")
                or ""
            ).lower()

            if (
                query in title
                or query in summary
            ):
                results.append(game)

        start = (page - 1) * page_size
        end = start + page_size

        return results[start:end]

    # =========================================================
    # DETAILS
    # =========================================================

    def get_game_details(
        self,
        game_id: int,
    ):

        data = self._request(
            "game",
            params={
                "id": game_id,
            },
        )

        if not isinstance(data, dict):
            return None

        return self._normalize_game(data)

    # =========================================================
    # POPULAR
    # =========================================================

    def get_popular_games(
        self,
        page: int = 1,
        page_size: int = 10,
    ):

        return self.get_games(
            page=page,
            page_size=page_size,
            sort_by="popularity",
        )

    # =========================================================
    # YEAR
    # =========================================================

    def get_games_by_year(
        self,
        year: int,
        page: int = 1,
        page_size: int = 10,
    ):

        return self.get_games(
            page=page,
            page_size=page_size,
            year=year,
        )

    # =========================================================
    # GENRE
    # =========================================================

    def get_games_by_genre(
        self,
        genre: str,
        page: int = 1,
        page_size: int = 10,
    ):

        return self.get_games(
            page=page,
            page_size=page_size,
            genre=genre,
        )

    # =========================================================
    # PLATFORM
    # =========================================================

    def get_games_by_platform(
        self,
        platform: str,
        page: int = 1,
        page_size: int = 10,
    ):

        return self.get_games(
            page=page,
            page_size=page_size,
            platform=platform,
        )

    # =========================================================
    # UPCOMING
    # =========================================================

    def get_upcoming_games(
        self,
        page: int = 1,
        page_size: int = 10,
    ):

        # FreeToGame API اطلاعات قابل اتکایی
        # برای بازی‌های آینده ارائه نمی‌کند.
        return []