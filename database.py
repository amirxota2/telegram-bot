import os
import sqlite3

from config import DATABASE_PATH


def get_connection():
    """
    ایجاد اتصال به SQLite.
    """

    directory = os.path.dirname(DATABASE_PATH)

    if directory:
        os.makedirs(
            directory,
            exist_ok=True,
        )

    connection = sqlite3.connect(
        DATABASE_PATH
    )

    connection.row_factory = sqlite3.Row

    return connection


def init_database():
    """
    ساخت جداول دیتابیس.
    """

    connection = get_connection()
    cursor = connection.cursor()

    # -------------------------
    # Users
    # -------------------------

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            first_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # -------------------------
    # Favorites
    # -------------------------

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            telegram_id INTEGER NOT NULL,

            game_id INTEGER NOT NULL,
            game_name TEXT NOT NULL,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(
                telegram_id,
                game_id
            )
        )
        """
    )

    # -------------------------
    # Followed games
    # -------------------------

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS followed_games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            telegram_id INTEGER NOT NULL,

            game_id INTEGER NOT NULL,
            game_name TEXT NOT NULL,

            release_date TEXT,

            notified INTEGER DEFAULT 0,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(
                telegram_id,
                game_id
            )
        )
        """
    )

    connection.commit()
    connection.close()


def save_user(
    telegram_id: int,
    username: str | None,
    first_name: str | None,
):
    """
    ذخیره کاربر.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO users (
            telegram_id,
            username,
            first_name
        )

        VALUES (?, ?, ?)

        ON CONFLICT(telegram_id)
        DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name
        """,
        (
            telegram_id,
            username,
            first_name,
        ),
    )

    connection.commit()
    connection.close()


def add_favorite(
    telegram_id: int,
    game_id: int,
    game_name: str,
):
    """
    اضافه کردن بازی به علاقه‌مندی‌ها.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT OR IGNORE INTO favorites (
            telegram_id,
            game_id,
            game_name
        )

        VALUES (?, ?, ?)
        """,
        (
            telegram_id,
            game_id,
            game_name,
        ),
    )

    connection.commit()
    connection.close()


def remove_favorite(
    telegram_id: int,
    game_id: int,
):
    """
    حذف بازی از علاقه‌مندی‌ها.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        DELETE FROM favorites

        WHERE telegram_id = ?
        AND game_id = ?
        """,
        (
            telegram_id,
            game_id,
        ),
    )

    connection.commit()
    connection.close()


def is_favorite(
    telegram_id: int,
    game_id: int,
) -> bool:
    """
    بررسی اینکه بازی در علاقه‌مندی هست یا نه.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT 1

        FROM favorites

        WHERE telegram_id = ?
        AND game_id = ?

        LIMIT 1
        """,
        (
            telegram_id,
            game_id,
        ),
    )

    result = cursor.fetchone()

    connection.close()

    return result is not None


def get_favorites(
    telegram_id: int,
):
    """
    دریافت علاقه‌مندی‌های کاربر.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT *

        FROM favorites

        WHERE telegram_id = ?

        ORDER BY created_at DESC
        """,
        (
            telegram_id,
        ),
    )

    rows = cursor.fetchall()

    connection.close()

    return rows


def follow_game(
    telegram_id: int,
    game_id: int,
    game_name: str,
    release_date: str | None,
):
    """
    فعال کردن اعلان انتشار.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO followed_games (
            telegram_id,
            game_id,
            game_name,
            release_date,
            notified
        )

        VALUES (?, ?, ?, ?, 0)

        ON CONFLICT(
            telegram_id,
            game_id
        )

        DO UPDATE SET
            release_date = excluded.release_date,
            notified = 0
        """,
        (
            telegram_id,
            game_id,
            game_name,
            release_date,
        ),
    )

    connection.commit()
    connection.close()


def unfollow_game(
    telegram_id: int,
    game_id: int,
):
    """
    خاموش کردن اعلان بازی.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        DELETE FROM followed_games

        WHERE telegram_id = ?
        AND game_id = ?
        """,
        (
            telegram_id,
            game_id,
        ),
    )

    connection.commit()
    connection.close()


def get_followed_games():
    """
    دریافت بازی‌هایی که باید وضعیت انتشارشان بررسی شود.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT *

        FROM followed_games

        WHERE notified = 0
        """
    )

    rows = cursor.fetchall()

    connection.close()

    return rows


def mark_notified(
    row_id: int,
):
    """
    علامت‌گذاری اعلان ارسال‌شده.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        UPDATE followed_games

        SET notified = 1

        WHERE id = ?
        """,
        (
            row_id,
        ),
    )

    connection.commit()
    connection.close()