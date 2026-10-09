import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from config import DATABASE_PATH


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(DATABASE_PATH)
if not DB_PATH.is_absolute():
    DB_PATH = BASE_DIR / DB_PATH
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_connection():
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _ensure_column(connection, table: str, column: str, definition: str):
    existing = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in existing:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT UNIQUE,
            name TEXT NOT NULL,
            description TEXT,
            short_description TEXT,
            genres TEXT,
            genre_source TEXT,
            platforms TEXT,
            rating REAL,
            cover_url TEXT,
            release_date TEXT,
            developer TEXT,
            publisher TEXT,
            url TEXT,
            source TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Migrate the user's existing games.db without destroying data.
    _ensure_column(cursor.connection, "games", "genre_source", "TEXT")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            game_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(telegram_id, game_id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS followed_games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            game_id INTEGER NOT NULL,
            game_name TEXT NOT NULL,
            release_date TEXT,
            notified INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(telegram_id, game_id)
        )
        """
    )

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_name ON games(name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_rating ON games(rating)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_release_date ON games(release_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(telegram_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_followed_user ON followed_games(telegram_id)")

    connection.commit()
    connection.close()


def _json_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def save_game(game: dict):
    if not isinstance(game, dict):
        raise TypeError("game must be a dict")

    external_id = str(
        game.get("game_id")
        or game.get("id")
        or game.get("url")
        or ""
    ).strip()

    name = str(game.get("name") or game.get("title") or "").strip()
    if not external_id or not name:
        raise ValueError("game_id/url and name are required")

    genres = _json_list(game.get("genres"))
    platforms = _json_list(game.get("platforms"))

    connection = get_connection()
    old = connection.execute(
        "SELECT genres, genre_source FROM games WHERE game_id = ?",
        (external_id,),
    ).fetchone()

    if not genres and old and old["genres"]:
        try:
            genres = json.loads(old["genres"])
        except (TypeError, json.JSONDecodeError):
            genres = []

    genre_source = game.get("genre_source") or (old["genre_source"] if old else "none")

    connection.execute(
        """
        INSERT INTO games (
            game_id,
            name,
            description,
            short_description,
            genres,
            genre_source,
            platforms,
            rating,
            cover_url,
            release_date,
            developer,
            publisher,
            url,
            source,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(game_id) DO UPDATE SET
            name = excluded.name,
            description = CASE
                WHEN excluded.description IS NOT NULL AND excluded.description != ''
                THEN excluded.description ELSE games.description END,
            short_description = CASE
                WHEN excluded.short_description IS NOT NULL AND excluded.short_description != ''
                THEN excluded.short_description ELSE games.short_description END,
            genres = CASE
                WHEN excluded.genres IS NOT NULL AND excluded.genres != '[]'
                THEN excluded.genres ELSE games.genres END,
            genre_source = CASE
                WHEN excluded.genres IS NOT NULL AND excluded.genres != '[]'
                THEN excluded.genre_source ELSE games.genre_source END,
            platforms = CASE
                WHEN excluded.platforms IS NOT NULL AND excluded.platforms != '[]'
                THEN excluded.platforms ELSE games.platforms END,
            rating = COALESCE(excluded.rating, games.rating),
            cover_url = COALESCE(NULLIF(excluded.cover_url, ''), games.cover_url),
            release_date = COALESCE(NULLIF(excluded.release_date, ''), games.release_date),
            developer = COALESCE(NULLIF(excluded.developer, ''), games.developer),
            publisher = COALESCE(NULLIF(excluded.publisher, ''), games.publisher),
            url = COALESCE(NULLIF(excluded.url, ''), games.url),
            source = COALESCE(NULLIF(excluded.source, ''), games.source),
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            external_id,
            name,
            game.get("description") or game.get("summary") or "",
            game.get("short_description") or game.get("summary") or "",
            json.dumps(genres, ensure_ascii=False),
            genre_source,
            json.dumps(platforms, ensure_ascii=False),
            game.get("rating"),
            game.get("cover_url") or game.get("thumbnail") or "",
            game.get("release_date") or "",
            game.get("developer") or "",
            game.get("publisher") or "",
            game.get("url") or game.get("game_url") or external_id,
            game.get("source") or "gameup",
        ),
    )

    row = connection.execute(
        "SELECT id FROM games WHERE game_id = ?",
        (external_id,),
    ).fetchone()
    connection.commit()
    connection.close()

    return int(row["id"]) if row else None


def _get_game_row_by_id(game_id: int | str):
    connection = get_connection()
    row = connection.execute("SELECT * FROM games WHERE id = ?", (int(game_id),)).fetchone()
    connection.close()
    return row


def get_game(game_id: int | str):
    row = _get_game_row_by_id(game_id)
    return row_to_game(row) if row else None


def get_game_by_external_id(game_id: str):
    connection = get_connection()
    row = connection.execute("SELECT * FROM games WHERE game_id = ?", (str(game_id),)).fetchone()
    connection.close()
    return row_to_game(row) if row else None


def _fetch_games(query: str, params=()):
    connection = get_connection()
    rows = connection.execute(query, params).fetchall()
    connection.close()
    return [row_to_game(row) for row in rows]


def get_games(page: int = 1, limit: int = 50):
    """Return a shuffled discovery list; popular games use their own ranking."""
    page = max(int(page), 1)
    limit = max(min(int(limit), 100), 1)
    offset = (page - 1) * limit
    return _fetch_games(
        """
        SELECT * FROM games
        ORDER BY RANDOM()
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    )



def search_games(query: str, limit: int = 50):
    query = (query or "").strip()
    if not query:
        return []

    pattern = f"%{query}%"
    return _fetch_games(
        """
        SELECT * FROM games
        WHERE name LIKE ? COLLATE NOCASE
           OR description LIKE ? COLLATE NOCASE
        ORDER BY COALESCE(rating, 0) DESC, name COLLATE NOCASE ASC
        LIMIT ?
        """,
        (pattern, pattern, max(min(int(limit), 100), 1)),
    )


def get_popular_games(limit: int = 50):
    return _fetch_games(
        """
        SELECT * FROM games
        ORDER BY COALESCE(rating, 0) DESC, name COLLATE NOCASE ASC
        LIMIT ?
        """,
        (max(min(int(limit), 100), 1),),
    )


def get_games_by_year(year: int, limit: int = 50):
    """Filter on the year parsed from several common release-date formats."""
    import re

    requested_year = int(year)
    all_games = _fetch_games(
        "SELECT * FROM games WHERE release_date IS NOT NULL AND TRIM(release_date) != ''"
    )
    matches = []
    for game in all_games:
        value = str(game.get("release_date") or "").strip()
        match = re.search(r"(?<!\d)(?:19|20|21)\d{2}(?!\d)", value)
        if match and int(match.group(0)) == requested_year:
            matches.append(game)
    matches.sort(
        key=lambda item: (
            item.get("rating") is not None,
            item.get("rating") or 0,
            str(item.get("name") or "").casefold(),
        ),
        reverse=True,
    )
    return matches[:max(min(int(limit), 100), 1)]



def get_games_by_genre(genre: str, limit: int = 50):
    return _fetch_games(
        """
        SELECT * FROM games
        WHERE genres LIKE ?
        ORDER BY COALESCE(rating, 0) DESC, name COLLATE NOCASE ASC
        LIMIT ?
        """,
        (f"%{genre}%", max(min(int(limit), 100), 1)),
    )


def get_games_by_platform(platform: str, limit: int = 50):
    return _fetch_games(
        """
        SELECT * FROM games
        WHERE platforms LIKE ?
        ORDER BY COALESCE(rating, 0) DESC, name COLLATE NOCASE ASC
        LIMIT ?
        """,
        (f"%{platform}%", max(min(int(limit), 100), 1)),
    )


def _parse_date(value: str):
    value = (value or "").strip()
    if not value:
        return None

    candidates = [value[:10], value.split("T", 1)[0], value.split(" ", 1)[0]]
    formats = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d")
    for candidate in candidates:
        for fmt in formats:
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    return None


def get_upcoming_games(limit: int = 50):
    all_games = _fetch_games(
        "SELECT * FROM games WHERE release_date IS NOT NULL AND release_date != ''",
    )
    today = datetime.now(timezone.utc).date()
    upcoming = []
    for game in all_games:
        release = _parse_date(game.get("release_date"))
        if release and release >= today:
            upcoming.append((release, game))

    upcoming.sort(key=lambda item: (item[0], -(item[1].get("rating") or 0)))
    return [game for _, game in upcoming[: max(min(int(limit), 100), 1)]]


def get_available_years():
    """Read only release_date; do not convert a partial row into a full game."""
    import re

    connection = get_connection()
    try:
        rows = connection.execute(
            "SELECT release_date FROM games WHERE release_date IS NOT NULL AND TRIM(release_date) != ''"
        ).fetchall()
    finally:
        connection.close()

    years = set()
    for row in rows:
        value = str(row["release_date"] or "").strip()
        match = re.search(r"(?<!\d)(?:19|20|21)\d{2}(?!\d)", value)
        if match:
            years.add(int(match.group(0)))
    return sorted(years, reverse=True)



def get_available_genres():
    """Extract genres from each game's JSON list without requiring a name column."""
    connection = get_connection()
    try:
        rows = connection.execute("SELECT genres FROM games").fetchall()
    finally:
        connection.close()

    genres = set()
    for row in rows:
        try:
            values = json.loads(row["genres"] or "[]")
        except (TypeError, json.JSONDecodeError):
            values = []
        if isinstance(values, str):
            values = [values]
        for value in values if isinstance(values, list) else []:
            if isinstance(value, dict):
                value = value.get("name") or ""
            if isinstance(value, str) and value.strip():
                genres.add(value.strip())
    return sorted(genres, key=str.casefold)

def get_available_platforms():
    connection = get_connection()
    rows = connection.execute("SELECT platforms FROM games").fetchall()
    connection.close()

    platforms = set()
    for row in rows:
        try:
            values = json.loads(row["platforms"] or "[]")
        except (TypeError, json.JSONDecodeError):
            values = []
        for value in values:
            if isinstance(value, str):
                platforms.add(value)

    return sorted(platforms, key=str.casefold)


def count_games():
    connection = get_connection()
    count = connection.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    connection.close()
    return int(count)


# ------------------------------------------------------------------
# Users
# ------------------------------------------------------------------

def add_user(telegram_id: int, username: str | None = None, first_name: str | None = None):
    connection = get_connection()
    connection.execute(
        """
        INSERT INTO users (telegram_id, username, first_name)
        VALUES (?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name,
            updated_at = CURRENT_TIMESTAMP
        """,
        (int(telegram_id), username, first_name),
    )
    connection.commit()
    connection.close()


# ------------------------------------------------------------------
# Favorites
# ------------------------------------------------------------------

def add_favorite(telegram_id: int, game_id: int, game_name: str | None = None):
    del game_name  # game_name is retained only for old callers
    connection = get_connection()
    connection.execute(
        "INSERT OR IGNORE INTO favorites (telegram_id, game_id) VALUES (?, ?)",
        (int(telegram_id), int(game_id)),
    )
    connection.commit()
    connection.close()


def remove_favorite(telegram_id: int, game_id: int):
    connection = get_connection()
    connection.execute(
        "DELETE FROM favorites WHERE telegram_id = ? AND game_id = ?",
        (int(telegram_id), int(game_id)),
    )
    connection.commit()
    connection.close()


def is_favorite(telegram_id: int, game_id: int) -> bool:
    connection = get_connection()
    row = connection.execute(
        "SELECT 1 FROM favorites WHERE telegram_id = ? AND game_id = ?",
        (int(telegram_id), int(game_id)),
    ).fetchone()
    connection.close()
    return row is not None


def get_favorites(telegram_id: int):
    return _fetch_games(
        """
        SELECT g.*
        FROM favorites f
        JOIN games g ON g.id = f.game_id
        WHERE f.telegram_id = ?
        ORDER BY f.created_at DESC
        """,
        (int(telegram_id),),
    )


# ------------------------------------------------------------------
# Follow / release notification
# ------------------------------------------------------------------

def follow_game(
    telegram_id: int,
    game_id: int,
    game_name: str | None = None,
    release_date: str | None = None,
):
    connection = get_connection()
    if not game_name or release_date is None:
        row = connection.execute("SELECT name, release_date FROM games WHERE id = ?", (int(game_id),)).fetchone()
        if row:
            game_name = game_name or row["name"]
            release_date = release_date if release_date is not None else row["release_date"]

    if not game_name:
        connection.close()
        return

    connection.execute(
        """
        INSERT INTO followed_games (telegram_id, game_id, game_name, release_date, notified)
        VALUES (?, ?, ?, ?, 0)
        ON CONFLICT(telegram_id, game_id) DO UPDATE SET
            game_name = excluded.game_name,
            release_date = excluded.release_date,
            notified = 0
        """,
        (int(telegram_id), int(game_id), game_name, release_date),
    )
    connection.commit()
    connection.close()


def unfollow_game(telegram_id: int, game_id: int):
    connection = get_connection()
    connection.execute(
        "DELETE FROM followed_games WHERE telegram_id = ? AND game_id = ?",
        (int(telegram_id), int(game_id)),
    )
    connection.commit()
    connection.close()


def is_following(telegram_id: int, game_id: int) -> bool:
    connection = get_connection()
    row = connection.execute(
        "SELECT 1 FROM followed_games WHERE telegram_id = ? AND game_id = ?",
        (int(telegram_id), int(game_id)),
    ).fetchone()
    connection.close()
    return row is not None


def get_followed_games():
    connection = get_connection()
    rows = connection.execute(
        "SELECT * FROM followed_games ORDER BY created_at DESC"
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def mark_notified(follow_id: int):
    connection = get_connection()
    connection.execute(
        "UPDATE followed_games SET notified = 1 WHERE id = ?",
        (int(follow_id),),
    )
    connection.commit()
    connection.close()


def row_to_game(row):
    if row is None:
        return None

    game = dict(row)

    try:
        game["genres"] = json.loads(game.get("genres") or "[]")
    except (json.JSONDecodeError, TypeError):
        game["genres"] = []

    try:
        game["platforms"] = json.loads(game.get("platforms") or "[]")
    except (json.JSONDecodeError, TypeError):
        game["platforms"] = []

    game["genre"] = game["genres"]
    game["platform"] = game["platforms"]
    game["title"] = game.get("name") or ""
    game["thumbnail"] = game.get("cover_url") or ""
    game["game_url"] = game.get("url") or ""
    game["summary"] = game.get("short_description") or game.get("description") or ""

    return game


if __name__ == "__main__":
    init_db()
    print("Database initialized:")
    print(DB_PATH)
    print("Games:", count_games())
