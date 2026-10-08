import argparse
import logging
import time

import database
from config import REQUEST_TIMEOUT
from parvit.gameup import GameUPProvider


logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def sync_games(max_pages: int = 1, delay: float = 0.35, limit: int | None = None):
    database.init_db()
    provider = GameUPProvider(timeout=REQUEST_TIMEOUT)

    logger.info("Building GameUP game URL index...")
    index = provider.build_genre_index(
        max_pages_per_genre=max_pages,
        delay=delay,
    )

    urls = sorted(index.keys())
    if limit is not None:
        urls = urls[: max(int(limit), 0)]

    logger.info("Discovered %s unique game URLs.", len(urls))

    saved = 0
    failed = 0

    for number, url in enumerate(urls, start=1):
        logger.info("[%s/%s] %s", number, len(urls), url)

        game = provider.get_game_details(url)
        if not game:
            failed += 1
            continue

        indexed_genres = provider.genres_from_index(url, index)
        if not game.get("genres") and indexed_genres:
            game["genres"] = indexed_genres
            game["genre"] = indexed_genres
            game["genre_source"] = "sync_index"

        try:
            database.save_game(game)
            saved += 1
        except Exception as exc:
            failed += 1
            logger.exception("Could not save %s: %s", url, exc)

        if delay > 0:
            time.sleep(delay)

    logger.info(
        "Sync finished. saved=%s failed=%s database_total=%s",
        saved,
        failed,
        database.count_games(),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync GameUP games into SQLite")
    parser.add_argument("--pages", type=int, default=1, help="pages per GameUP category")
    parser.add_argument("--delay", type=float, default=0.35, help="delay between requests")
    parser.add_argument("--limit", type=int, default=None, help="only sync the first N game URLs")
    args = parser.parse_args()

    sync_games(
        max_pages=max(args.pages, 1),
        delay=max(args.delay, 0),
        limit=args.limit,
    )
