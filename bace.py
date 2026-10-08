from abc import ABC, abstractmethod


class GameProvider(ABC):
    """Minimal provider contract used by GameRadarBot."""

    @abstractmethod
    def get_game_details(self, game_id_or_url):
        raise NotImplementedError

    def get_games(self, page: int = 1, page_size: int = 10, **kwargs):
        raise NotImplementedError

    def search_games(self, query: str, page: int = 1, page_size: int = 10):
        raise NotImplementedError

    def get_popular_games(self, page: int = 1, page_size: int = 10):
        raise NotImplementedError

    def get_games_by_year(self, year: int, page: int = 1, page_size: int = 10):
        raise NotImplementedError

    def get_games_by_genre(self, genre: str, page: int = 1, page_size: int = 10):
        raise NotImplementedError

    def get_games_by_platform(self, platform: str, page: int = 1, page_size: int = 10):
        raise NotImplementedError

    def get_upcoming_games(self, page: int = 1, page_size: int = 10):
        raise NotImplementedError
