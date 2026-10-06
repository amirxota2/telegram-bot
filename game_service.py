from datetime import datetime, timezone
from typing import Any

import requests

from config import (
    IGDB_BASE_URL,
    REQUEST_TIMEOUT,
    TWITCH_CLIENT_ID,
    TWITCH_CLIENT_SECRET,
    TWITCH_TOKEN_URL,
)


class GameService:

    def __init__(self):

        if not TWITCH_CLIENT_ID:
            raise ValueError(
                "TWITCH_CLIENT_ID تنظیم نشده است."
            )

        if not TWITCH_CLIENT_SECRET:
            raise ValueError(
                "TWITCH_CLIENT_SECRET تنظیم نشده است."
            )

        self.client_id = TWITCH_CLIENT_ID
        self.client_secret = TWITCH_CLIENT_SECRET

        self.access_token = None
        self.token_expires_at = 0

    # =========================================================
    # AUTHENTICATION
    # =========================================================

    def _get_access_token(self):

        now = datetime.now(
            timezone.utc
        ).timestamp()

        if (
            self.access_token
            and now < self.token_expires_at - 60
        ):
            return self.access_token

        response = requests.post(
            TWITCH_TOKEN_URL,
            params={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()

        self.access_token = data["access_token"]

        expires_in = int(
            data.get(
                "expires_in",
                3600,
            )
        )

        self.token_expires_at = (
            now + expires_in
        )

        return self.access_token

    # =========================================================
    # RAW REQUEST
    # =========================================================

    def _request(
        self,
        endpoint: str,
        query: str,
    ) -> list[dict[str, Any]]:

        token = self._get_access_token()

        headers = {
            "Client-ID": self.client_id,
            "Authorization": (
                f"Bearer {token}"
            ),
            "Accept": "application/json",
        }

        url = (
            f"{IGDB_BASE_URL}"
            f"/{endpoint.lstrip('/')}"
        )

        response = requests.post(
            url,
            headers=headers,
            data=query,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        return response.json()

    # =========================================================
    # GAME FIELDS
    # =========================================================

    GAME_FIELDS = """
        id,
        name,
        slug,
        summary,
        storyline,
        first_release_date,
        rating,
        rating_count,
        aggregated_rating,
        aggregated_rating_count,
        total_rating,
        total_rating_count,
        genres.name,
        platforms.id,
        platforms.name,
        platforms.abbreviation,
        cover.image_id,
        screenshots.image_id,
        artworks.image_id,
        involved_companies.company.name,
        involved_companies.developer,
        involved_companies.publisher,
        websites.url,
        websites.type,
        websites.trusted,
        external_games.name,
        external_games.url,
        external_games.external_game_source.name
    """

    # =========================================================
    # HELPERS
    # =========================================================

    @staticmethod
    def _timestamp_for_year_start(
        year: int,
    ) -> int:

        return int(
            datetime(
                year,
                1,
                1,
                tzinfo=timezone.utc,
            ).timestamp()
        )

    @staticmethod
    def _timestamp_for_year_end(
        year: int,
    ) -> int:

        return int(
            datetime(
                year,
                12,
                31,
                23,
                59,
                59,
                tzinfo=timezone.utc,
            ).timestamp()
        )

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
        ordering: str = "rating desc",
    ):

        offset = (
            (page - 1)
            * page_size
        )

        conditions = []

        if year:
            start = (
                self._timestamp_for_year_start(
                    year
                )
            )

            end = (
                self._timestamp_for_year_end(
                    year
                )
            )

            conditions.append(
                f"first_release_date >= {start}"
            )

            conditions.append(
                f"first_release_date <= {end}"
            )

        if genre_id:
            conditions.append(
                f"genres = {genre_id}"
            )

        if platform_id:
            conditions.append(
                f"platforms = {platform_id}"
            )

        where_clause = ""

        if conditions:
            where_clause = (
                "where "
                + " & ".join(conditions)
                + ";"
            )

        query = f"""
            fields {self.GAME_FIELDS};
            {where_clause}
            sort {ordering};
            limit {page_size};
            offset {offset};
        """

        return self._request(
            "games",
            query,
        )

    # =========================================================
    # SEARCH
    # =========================================================

    def search_games(
        self,
        query_text: str,
        page: int = 1,
        page_size: int = 10,
    ):

        offset = (
            (page - 1)
            * page_size
        )

        safe_query = (
            query_text
            .replace(
                '"',
                '\\"',
            )
        )

        query = f"""
            search "{safe_query}";
            fields {self.GAME_FIELDS};
            limit {page_size};
            offset {offset};
        """

        return self._request(
            "games",
            query,
        )

    # =========================================================
    # GAME DETAILS
    # =========================================================

    def get_game_details(
        self,
        game_id: int,
    ):

        query = f"""
            fields {self.GAME_FIELDS};
            where id = {game_id};
        """

        games = self._request(
            "games",
            query,
        )

        if not games:
            return None

        return games[0]

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
            ordering="rating desc",
        )

    # =========================================================
    # BY YEAR
    # =========================================================

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
            ordering="rating desc",
        )

    # =========================================================
    # BY GENRE
    # =========================================================

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
            ordering="rating desc",
        )

    # =========================================================
    # BY PLATFORM
    # =========================================================

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
            ordering="rating desc",
        )

    # =========================================================
    # UPCOMING
    # =========================================================

    def get_upcoming_games(
        self,
        page: int = 1,
        page_size: int = 10,
    ):

        now = int(
            datetime.now(
                timezone.utc
            ).timestamp()
        )

        offset = (
            (page - 1)
            * page_size
        )

        query = f"""
            fields {self.GAME_FIELDS};
            where first_release_date >= {now};
            sort first_release_date asc;
            limit {page_size};
            offset {offset};
        """

        return self._request(
            "games",
            query,
        )

    # =========================================================
    # COVER URL
    # =========================================================

    @staticmethod
    def get_cover_url(
        game: dict,
        size: str = "cover_big",
    ) -> str | None:

        cover = game.get(
            "cover"
        )

        if not cover:
            return None

        image_id = cover.get(
            "image_id"
        )

        if not image_id:
            return None

        return (
            "https://images.igdb.com/"
            "igdb/image/upload/"
            f"t_{size}/"
            f"{image_id}.jpg"
        )

    # =========================================================
    # SCREENSHOT URLS
    # =========================================================

    @staticmethod
    def get_screenshot_urls(
        game: dict,
        size: str = "screenshot_big",
    ) -> list[str]:

        result = []

        for screenshot in game.get(
            "screenshots",
            [],
        ):

            image_id = screenshot.get(
                "image_id"
            )

            if image_id:
                result.append(
                    "https://images.igdb.com/"
                    "igdb/image/upload/"
                    f"t_{size}/"
                    f"{image_id}.jpg"
                )

        return result

    # =========================================================
    # GENRES
    # =========================================================

    @staticmethod
    def get_genres(
        game: dict,
    ) -> list[str]:

        result = []

        for genre in game.get(
            "genres",
            [],
        ):

            name = genre.get(
                "name"
            )

            if name:
                result.append(name)

        return result

    # =========================================================
    # PLATFORMS
    # =========================================================

    @staticmethod
    def get_platforms(
        game: dict,
    ) -> list[str]:

        result = []

        for platform in game.get(
            "platforms",
            [],
        ):

            name = platform.get(
                "name"
            )

            if name:
                result.append(name)

        return result

    # =========================================================
    # DEVELOPERS
    # =========================================================

    @staticmethod
    def get_developers(
        game: dict,
    ) -> list[str]:

        result = []

        for company in game.get(
            "involved_companies",
            [],
        ):

            if company.get(
                "developer"
            ):

                data = company.get(
                    "company",
                    {}
                )

                name = data.get(
                    "name"
                )

                if name:
                    result.append(name)

        return result

    # =========================================================
    # PUBLISHERS
    # =========================================================

    @staticmethod
    def get_publishers(
        game: dict,
    ) -> list[str]:

        result = []

        for company in game.get(
            "involved_companies",
            [],
        ):

            if company.get(
                "publisher"
            ):

                data = company.get(
                    "company",
                    {}
                )

                name = data.get(
                    "name"
                )

                if name:
                    result.append(name)

        return result

    # =========================================================
    # WEBSITE
    # =========================================================

    @staticmethod
    def get_official_website(
        game: dict,
    ) -> str | None:

        for website in game.get(
            "websites",
            [],
        ):

            if (
                website.get("type") == 1
                or website.get("trusted") is True
            ):
                url = website.get(
                    "url"
                )

                if url:
                    return url

        return None

    # =========================================================
    # STORE LINKS
    # =========================================================

    @staticmethod
    def get_store_links(
        game: dict,
    ):

        result = []

        for item in game.get(
            "external_games",
            [],
        ):

            name = item.get(
                "name"
            )

            url = item.get(
                "url"
            )

            source = item.get(
                "external_game_source",
                {}
            )

            source_name = source.get(
                "name"
            )

            if not source_name:
                source_name = name

            if url:

                result.append(
                    (
                        source_name
                        or "Store",
                        url,
                    )
                )

        return result