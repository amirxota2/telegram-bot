import database


class GameService:
    """DB-first service used by the Telegram bot.

    No external scraping/API request happens while a user is interacting with
    the bot. GameUP is used by sync_games.py to populate this database.
    """

    def get_games(self, page: int = 1, page_size: int = 50, **kwargs):
        del kwargs
        return database.get_games(page=page, limit=page_size)

    def search_games(self, query: str, page: int = 1, page_size: int = 50):
        # Search currently returns one capped result set; page slicing is kept
        # here for compatibility with the old service API.
        all_results = database.search_games(query, limit=100)
        start = max(page - 1, 0) * page_size
        return all_results[start : start + page_size]

    def get_game_details(self, game_id):
        try:
            return database.get_game(int(game_id))
        except (TypeError, ValueError):
            return database.get_game_by_external_id(str(game_id))

    def get_popular_games(self, page: int = 1, page_size: int = 50):
        all_results = database.get_popular_games(limit=100)
        start = max(page - 1, 0) * page_size
        return all_results[start : start + page_size]

    def get_games_by_year(self, year: int, page: int = 1, page_size: int = 50):
        all_results = database.get_games_by_year(year, limit=100)
        start = max(page - 1, 0) * page_size
        return all_results[start : start + page_size]

    def get_games_by_genre(self, genre: str, page: int = 1, page_size: int = 50):
        all_results = database.get_games_by_genre(genre, limit=100)
        start = max(page - 1, 0) * page_size
        return all_results[start : start + page_size]

    def get_games_by_platform(self, platform: str, page: int = 1, page_size: int = 50):
        all_results = database.get_games_by_platform(platform, limit=100)
        start = max(page - 1, 0) * page_size
        return all_results[start : start + page_size]

    def get_upcoming_games(self, page: int = 1, page_size: int = 50):
        all_results = database.get_upcoming_games(limit=100)
        start = max(page - 1, 0) * page_size
        return all_results[start : start + page_size]

    @staticmethod
    def get_cover_url(game: dict, size: str = "cover_big") -> str | None:
        del size
        return game.get("cover_url") or game.get("thumbnail") or None

    @staticmethod
    def get_screenshot_urls(game: dict, size: str = "screenshot_big") -> list[str]:
        del size
        value = game.get("screenshot_urls") or []
        return value if isinstance(value, list) else []

    @staticmethod
    def get_genres(game: dict) -> list[str]:
        values = game.get("genres") or game.get("genre") or []
        result = []
        for item in values:
            if isinstance(item, str):
                name = item
            elif isinstance(item, dict):
                name = item.get("name") or ""
            else:
                name = str(item)
            if name and name not in result:
                result.append(name)
        return result

    @staticmethod
    def get_platforms(game: dict) -> list[str]:
        values = game.get("platforms") or game.get("platform") or []
        result = []
        for item in values:
            if isinstance(item, str):
                name = item
            elif isinstance(item, dict):
                name = item.get("name") or item.get("platform", {}).get("name") or ""
            else:
                name = str(item)
            if name and name not in result:
                result.append(name)
        return result

    @staticmethod
    def get_developers(game: dict) -> list[str]:
        if game.get("developer"):
            return [str(game["developer"])]
        result = []
        for item in game.get("involved_companies") or []:
            if item.get("developer"):
                company = item.get("company") or {}
                if company.get("name"):
                    result.append(company["name"])
        return result

    @staticmethod
    def get_publishers(game: dict) -> list[str]:
        if game.get("publisher"):
            return [str(game["publisher"])]
        result = []
        for item in game.get("involved_companies") or []:
            if item.get("publisher"):
                company = item.get("company") or {}
                if company.get("name"):
                    result.append(company["name"])
        return result

    @staticmethod
    def get_developer(game: dict) -> str:
        return ", ".join(GameService.get_developers(game))

    @staticmethod
    def get_publisher(game: dict) -> str:
        return ", ".join(GameService.get_publishers(game))

    @staticmethod
    def get_official_website(game: dict) -> str | None:
        if game.get("url"):
            return game["url"]
        for website in game.get("websites") or []:
            if website.get("url"):
                return website["url"]
        return None

    @staticmethod
    def get_game_url(game: dict) -> str | None:
        return game.get("url") or game.get("game_url") or None

    @staticmethod
    def get_store_links(game: dict):
        links = []
        if game.get("url"):
            links.append(("GameUP", game["url"]))
        for item in game.get("external_games") or []:
            url = item.get("url")
            if not url:
                continue
            source = item.get("external_game_source") or {}
            links.append((source.get("name") or "Link", url))
        return links

    @staticmethod
    def get_available_years():
        return database.get_available_years()

    @staticmethod
    def get_available_platforms():
        return database.get_available_platforms()

    @staticmethod
    def count_games():
        return database.count_games()
