from datetime import datetime

import requests

from config import (
    RAWG_API_KEY,
    RAWG_BASE_URL,
    REQUEST_TIMEOUT,
)


class GameService:

    def __init__(self):

        if not RAWG_API_KEY:
            raise ValueError(
                "RAWG_API_KEY تنظیم نشده است."
            )

        self.api_key = RAWG_API_KEY
        self.base_url = RAWG_BASE_URL

    # ==================================================
    # Request
    # ==================================================

    def _request(
        self,
        endpoint: str,
        params: dict | None = None,
    ):

        if params is None:
            params = {}

        params["key"] = self.api_key

        url = (
            f"{self.base_url}"
            f"/{endpoint.lstrip('/')}"
        )

        response = requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        return response.json()

    # ==================================================
    # Games
    # ==================================================

    def get_games(
        self,
        page: int = 1,
        page_size: int = 10,
        dates: str | None = None,
        genres: str | None = None,
        platforms: str | None = None,
        ordering: str = "-rating",
    ):

        params = {
            "page": page,
            "page_size": page_size,
            "ordering": ordering,
        }

        if dates:
            params["dates"] = dates

        if genres:
            params["genres"] = genres

        if platforms:
            params["platforms"] = platforms

        return self._request(
            "games",
            params,
        )

    # ==================================================
    # Game details
    # ==================================================

    def get_game_details(
        self,
        game_id: int,
    ):

        return self._request(
            f"games/{game_id}"
        )

    # ==================================================
    # Search
    # ==================================================

    def search_games(
        self,
        query: str,
        page: int = 1,
        page_size: int = 10,
    ):

        return self._request(
            "games",
            {
                "search": query,
                "page": page,
                "page_size": page_size,
                "ordering": "-rating",
            },
        )

    # ==================================================
    # Year
    # ==================================================

    def get_games_by_year(
        self,
        year: int,
        page: int = 1,
        page_size: int = 10,
        genres: str | None = None,
        platforms: str | None = None,
    ):

        dates = (
            f"{year}-01-01,"
            f"{year}-12-31"
        )

        return self.get_games(
            page=page,
            page_size=page_size,
            dates=dates,
            genres=genres,
            platforms=platforms,
            ordering="-rating",
        )

    # ==================================================
    # Popular
    # ==================================================

    def get_popular_games(
        self,
        page: int = 1,
        page_size: int = 10,
    ):

        return self.get_games(
            page=page,
            page_size=page_size,
            ordering="-rating",
        )

    # ==================================================
    # Upcoming
    # ==================================================

    def get_upcoming_games(
        self,
        page: int = 1,
        page_size: int = 10,
    ):

        today = datetime.now().strftime(
            "%Y-%m-%d"
        )

        end_year = datetime.now().year + 3

        dates = (
            f"{today},"
            f"{end_year}-12-31"
        )

        return self.get_games(
            page=page,
            page_size=page_size,
            dates=dates,
            ordering="released",
        )

    # ==================================================
    # Genre
    # ==================================================

    def get_games_by_genre(
        self,
        genre: str,
        page: int = 1,
        page_size: int = 10,
        year: int | None = None,
    ):

        dates = None

        if year:
            dates = (
                f"{year}-01-01,"
                f"{year}-12-31"
            )

        return self.get_games(
            page=page,
            page_size=page_size,
            dates=dates,
            genres=genre,
            ordering="-rating",
        )

    # ==================================================
    # Platform
    # ==================================================

    def get_games_by_platform(
        self,
        platform_id: int,
        page: int = 1,
        page_size: int = 10,
        year: int | None = None,
    ):

        dates = None

        if year:
            dates = (
                f"{year}-01-01,"
                f"{year}-12-31"
            )

        return self.get_games(
            page=page,
            page_size=page_size,
            dates=dates,
            platforms=str(platform_id),
            ordering="-rating",
        )