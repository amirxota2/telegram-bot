from parvit.bace import GameProvider
from parvit.freetogame import FreeToGameProvider


class GameService:

    def __init__(
        self,
        provider: GameProvider | None = None,
    ):
        self.provider = (
            provider
            or FreeToGameProvider()
        )

    # =========================================================
    # GAMES
    # =========================================================

    def get_games(
        self,
        page: int = 1,
        page_size: int = 10,
        **kwargs,
    ):
        return self.provider.get_games(
            page=page,
            page_size=page_size,
            **kwargs,
        )

    # =========================================================
    # SEARCH
    # =========================================================

    def search_games(
        self,
        query: str,
        page: int = 1,
        page_size: int = 10,
    ):
        return self.provider.search_games(
            query=query,
            page=page,
            page_size=page_size,
        )

    # =========================================================
    # DETAILS
    # =========================================================

    def get_game_details(
        self,
        game_id: int,
    ):
        return self.provider.get_game_details(
            game_id
        )

    # =========================================================
    # POPULAR
    # =========================================================

    def get_popular_games(
        self,
        page: int = 1,
        page_size: int = 10,
    ):
        return self.provider.get_popular_games(
            page=page,
            page_size=page_size,
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
        return self.provider.get_games_by_year(
            year=year,
            page=page,
            page_size=page_size,
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
        return self.provider.get_games_by_genre(
            genre=genre,
            page=page,
            page_size=page_size,
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
        return self.provider.get_games_by_platform(
            platform=platform,
            page=page,
            page_size=page_size,
        )

    # =========================================================
    # UPCOMING
    # =========================================================

    def get_upcoming_games(
        self,
        page: int = 1,
        page_size: int = 10,
    ):
        return self.provider.get_upcoming_games(
            page=page,
            page_size=page_size,
        )

    # =========================================================
    # HELPERS
    # =========================================================

    @staticmethod
    def get_cover_url(
        game,
        size="cover_big",
    ):
        return game.get("cover_url")

    @staticmethod
    def get_screenshot_urls(
        game,
        size="screenshot_big",
    ):
        return game.get(
            "screenshot_urls",
            [],
        )

    @staticmethod
    def get_genres(game):

        return [
            genre.get("name")
            for genre in game.get(
                "genres",
                [],
            )
            if genre.get("name")
        ]

    @staticmethod
    def get_platforms(game):

        return [
            platform.get("name")
            for platform in game.get(
                "platforms",
                [],
            )
            if platform.get("name")
        ]

    @staticmethod
    def get_developers(game):

        return [
            company.get("company", {}).get(
                "name"
            )
            for company in game.get(
                "involved_companies",
                [],
            )
            if company.get("developer")
            and company.get(
                "company",
                {},
            ).get("name")
        ]

    @staticmethod
    def get_publishers(game):

        return [
            company.get("company", {}).get(
                "name"
            )
            for company in game.get(
                "involved_companies",
                [],
            )
            if company.get("publisher")
            and company.get(
                "company",
                {},
            ).get("name")
        ]

    @staticmethod
    def get_official_website(game):

        websites = game.get(
            "websites",
            [],
        )

        if websites:
            return websites[0].get("url")

        return None

    @staticmethod
    def get_store_links(game):

        result = []

        for item in game.get(
            "external_games",
            [],
        ):

            url = item.get("url")

            if not url:
                continue

            source = (
                item.get(
                    "external_game_source"
                )
                or {}
            )

            result.append(
                (
                    source.get("name")
                    or "Link",
                    url,
                )
            )

        return result