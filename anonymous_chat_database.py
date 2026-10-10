
"""SQLite storage for anonymous one-to-one chat profiles and matchmaking.

This database is separate from the game catalog database.
Chat message bodies are not stored: Telegram copies are delivered
directly to the matched partner.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

_CONFIGURED_PATH = Path(
    os.getenv("ANONYMOUS_DATABASE_PATH", "data/anonymous_messages.db")
).expanduser()

DB_PATH = (
    _CONFIGURED_PATH
    if _CONFIGURED_PATH.is_absolute()
    else (BASE_DIR / _CONFIGURED_PATH).resolve()
)

DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def _connection():
    conn = get_connection()
    try:
        yield conn

        if conn.in_transaction:
            conn.commit()

    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise

    finally:
        conn.close()


def init_db() -> None:
    """Create tables and safely migrate existing profile databases."""

    with _connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_profiles (
                user_id INTEGER PRIMARY KEY,
                display_name TEXT NOT NULL,
                gender TEXT NOT NULL
                    CHECK(gender IN ('female', 'male')),
                city TEXT NOT NULL,
                photo_file_id TEXT,
                preference TEXT NOT NULL DEFAULT 'any'
                    CHECK(preference IN ('female', 'male', 'any')),
                is_searching INTEGER NOT NULL DEFAULT 0,
                searching_since TEXT,
                partner_id INTEGER,
                waiting_message_id INTEGER,
                session_message_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        # Keep older databases compatible without deleting user data.
        existing_profile_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(chat_profiles)"
            ).fetchall()
        }

        if "waiting_message_id" not in existing_profile_columns:
            conn.execute(
                "ALTER TABLE chat_profiles "
                "ADD COLUMN waiting_message_id INTEGER"
            )

        if "session_message_id" not in existing_profile_columns:
            conn.execute(
                "ALTER TABLE chat_profiles "
                "ADD COLUMN session_message_id INTEGER"
            )

        if "photo_file_id" not in existing_profile_columns:
            conn.execute(
                "ALTER TABLE chat_profiles "
                "ADD COLUMN photo_file_id TEXT"
            )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS skipped_pairs (
                user_low INTEGER NOT NULL,
                user_high INTEGER NOT NULL,
                skipped_at TEXT NOT NULL,
                PRIMARY KEY(user_low, user_high),
                CHECK(user_low < user_high)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id INTEGER NOT NULL,
                reported_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(reporter_id, reported_id)
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_queue
            ON chat_profiles(is_searching, searching_since)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_partner
            ON chat_profiles(partner_id)
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS friend_requests (
                requester_id INTEGER NOT NULL,
                recipient_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'accepted', 'declined')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(requester_id, recipient_id),
                CHECK(requester_id != recipient_id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_friends (
                user_low INTEGER NOT NULL,
                user_high INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(user_low, user_high),
                CHECK(user_low < user_high)
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_friend_requests_recipient
            ON friend_requests(recipient_id, status)
            """
        )

        # Older messages/blocked_users tables, if present, are preserved.


def get_profile(user_id: int) -> dict[str, Any] | None:
    with _connection() as conn:
        row = conn.execute(
            "SELECT * FROM chat_profiles WHERE user_id = ?",
            (int(user_id),),
        ).fetchone()

        return dict(row) if row else None


def save_profile(
    user_id: int,
    display_name: str,
    gender: str,
    city: str,
    preference: str,
) -> None:
    if gender not in {"female", "male"}:
        raise ValueError("gender must be 'female' or 'male'")

    if preference not in {"female", "male", "any"}:
        raise ValueError("preference must be 'female', 'male' or 'any'")

    now = _now()

    with _connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        old = conn.execute(
            "SELECT created_at FROM chat_profiles WHERE user_id = ?",
            (int(user_id),),
        ).fetchone()

        created_at = old["created_at"] if old else now

        conn.execute(
            """
            INSERT INTO chat_profiles (
                user_id,
                display_name,
                gender,
                city,
                preference,
                is_searching,
                searching_since,
                partner_id,
                waiting_message_id,
                session_message_id,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, 0, NULL, NULL, NULL, NULL, ?, ?)

            ON CONFLICT(user_id) DO UPDATE SET
                display_name = excluded.display_name,
                gender = excluded.gender,
                city = excluded.city,
                preference = excluded.preference,
                is_searching = 0,
                searching_since = NULL,
                partner_id = NULL,
                waiting_message_id = NULL,
                session_message_id = NULL,
                updated_at = excluded.updated_at
            """,
            (
                int(user_id),
                display_name.strip(),
                gender,
                city.strip(),
                preference,
                created_at,
                now,
            ),
        )

        conn.commit()


def set_profile_photo(
    user_id: int,
    photo_file_id: str | None,
) -> None:
    """Save or remove a Telegram photo file_id for an existing profile."""

    with _connection() as conn:
        conn.execute(
            """
            UPDATE chat_profiles
            SET photo_file_id = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (
                photo_file_id,
                _now(),
                int(user_id),
            ),
        )


def set_waiting_message_id(
    user_id: int,
    message_id: int | None,
) -> None:
    with _connection() as conn:
        conn.execute(
            """
            UPDATE chat_profiles
            SET waiting_message_id = ?
            WHERE user_id = ?
            """,
            (
                int(message_id) if message_id is not None else None,
                int(user_id),
            ),
        )


def clear_waiting_message_id(user_id: int) -> None:
    set_waiting_message_id(user_id, None)


def set_session_message_id(
    user_id: int,
    message_id: int | None,
) -> None:
    with _connection() as conn:
        conn.execute(
            """
            UPDATE chat_profiles
            SET session_message_id = ?
            WHERE user_id = ?
            """,
            (
                int(message_id) if message_id is not None else None,
                int(user_id),
            ),
        )


def clear_session_message_id(user_id: int) -> None:
    set_session_message_id(user_id, None)


def update_preference(user_id: int, preference: str) -> None:
    if preference not in {"female", "male", "any"}:
        raise ValueError("invalid preference")

    with _connection() as conn:
        conn.execute(
            """
            UPDATE chat_profiles
            SET preference = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (
                preference,
                _now(),
                int(user_id),
            ),
        )


def get_partner_id(user_id: int) -> int | None:
    with _connection() as conn:
        row = conn.execute(
            "SELECT partner_id FROM chat_profiles WHERE user_id = ?",
            (int(user_id),),
        ).fetchone()

        return (
            int(row["partner_id"])
            if row and row["partner_id"] is not None
            else None
        )


def is_searching(user_id: int) -> bool:
    with _connection() as conn:
        row = conn.execute(
            "SELECT is_searching FROM chat_profiles WHERE user_id = ?",
            (int(user_id),),
        ).fetchone()

        return bool(row["is_searching"]) if row else False


def _pair_key(first: int, second: int) -> tuple[int, int]:
    return min(int(first), int(second)), max(int(first), int(second))


def _compatible(
    own: sqlite3.Row,
    candidate: sqlite3.Row,
) -> bool:
    own_pref = own["preference"]
    other_pref = candidate["preference"]

    return (
        own_pref == "any" or own_pref == candidate["gender"]
    ) and (
        other_pref == "any" or other_pref == own["gender"]
    )


def find_match_or_queue(user_id: int) -> int | None:
    """Match with the oldest mutually compatible queued user, or join queue."""

    uid = int(user_id)
    now = _now()

    with _connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        own = conn.execute(
            "SELECT * FROM chat_profiles WHERE user_id = ?",
            (uid,),
        ).fetchone()

        if not own:
            conn.rollback()
            raise LookupError("profile required before searching")

        if own["partner_id"] is not None:
            partner = int(own["partner_id"])
            conn.commit()
            return partner

        candidates = conn.execute(
            """
            SELECT * FROM chat_profiles
            WHERE is_searching = 1
              AND partner_id IS NULL
              AND user_id != ?
            ORDER BY COALESCE(searching_since, updated_at) ASC, user_id ASC
            """,
            (uid,),
        ).fetchall()

        chosen = None

        for candidate in candidates:
            if not _compatible(own, candidate):
                continue

            low, high = _pair_key(uid, int(candidate["user_id"]))

            skipped = conn.execute(
                """
                SELECT 1 FROM skipped_pairs
                WHERE user_low = ? AND user_high = ?
                """,
                (low, high),
            ).fetchone()

            reported = conn.execute(
                """
                SELECT 1 FROM chat_reports
                WHERE (reporter_id = ? AND reported_id = ?)
                   OR (reporter_id = ? AND reported_id = ?)
                LIMIT 1
                """,
                (
                    uid,
                    int(candidate["user_id"]),
                    int(candidate["user_id"]),
                    uid,
                ),
            ).fetchone()

            if skipped or reported:
                continue

            chosen = int(candidate["user_id"])
            break

        if chosen is None:
            conn.execute(
                """
                UPDATE chat_profiles
                SET is_searching = 1,
                    searching_since = COALESCE(searching_since, ?),
                    updated_at = ?
                WHERE user_id = ? AND partner_id IS NULL
                """,
                (now, now, uid),
            )
            conn.commit()
            return None

        conn.execute(
            """
            UPDATE chat_profiles
            SET is_searching = 0,
                searching_since = NULL,
                partner_id = ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (chosen, now, uid),
        )

        conn.execute(
            """
            UPDATE chat_profiles
            SET is_searching = 0,
                searching_since = NULL,
                partner_id = ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (uid, now, chosen),
        )

        conn.commit()
        return chosen


def end_chat(user_id: int, remember_pair: bool = True) -> int | None:
    """Remove a user from queue and detach an active partner atomically."""

    uid = int(user_id)
    now = _now()

    with _connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            "SELECT partner_id FROM chat_profiles WHERE user_id = ?",
            (uid,),
        ).fetchone()

        partner = (
            int(row["partner_id"])
            if row and row["partner_id"] is not None
            else None
        )

        conn.execute(
            """
            UPDATE chat_profiles
            SET is_searching = 0,
                searching_since = NULL,
                partner_id = NULL,
                waiting_message_id = NULL,
                updated_at = ?
            WHERE user_id = ?
            """,
            (now, uid),
        )

        if partner is not None:
            conn.execute(
                """
                UPDATE chat_profiles
                SET is_searching = 0,
                    searching_since = NULL,
                    partner_id = NULL,
                    waiting_message_id = NULL,
                    updated_at = ?
                WHERE user_id = ? AND partner_id = ?
                """,
                (now, partner, uid),
            )

            if remember_pair:
                low, high = _pair_key(uid, partner)

                conn.execute(
                    """
                    INSERT INTO skipped_pairs(
                        user_low, user_high, skipped_at
                    )
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_low, user_high)
                    DO UPDATE SET skipped_at = excluded.skipped_at
                    """,
                    (low, high, now),
                )

        conn.commit()

    return partner


def stop_search(user_id: int) -> bool:
    with _connection() as conn:
        cursor = conn.execute(
            """
            UPDATE chat_profiles
            SET is_searching = 0,
                searching_since = NULL,
                waiting_message_id = NULL,
                updated_at = ?
            WHERE user_id = ?
              AND partner_id IS NULL
              AND is_searching = 1
            """,
            (_now(), int(user_id)),
        )

        return cursor.rowcount > 0


def record_report(reporter_id: int, reported_id: int) -> None:
    with _connection() as conn:
        conn.execute(
            """
            INSERT INTO chat_reports(
                reporter_id, reported_id, created_at
            )
            VALUES (?, ?, ?)
            ON CONFLICT(reporter_id, reported_id)
            DO UPDATE SET created_at = excluded.created_at
            """,
            (int(reporter_id), int(reported_id), _now()),
        )


def get_counts() -> dict[str, int]:
    with _connection() as conn:
        profiles = conn.execute(
            "SELECT COUNT(*) FROM chat_profiles"
        ).fetchone()[0]

        searching = conn.execute(
            "SELECT COUNT(*) FROM chat_profiles WHERE is_searching = 1"
        ).fetchone()[0]

        active = conn.execute(
            "SELECT COUNT(*) FROM chat_profiles WHERE partner_id IS NOT NULL"
        ).fetchone()[0] // 2

        reports = conn.execute(
            "SELECT COUNT(*) FROM chat_reports"
        ).fetchone()[0]

    return {
        "profiles": int(profiles),
        "searching": int(searching),
        "active_chats": int(active),
        "reports": int(reports),
    }


# -------- friend requests and persistent friend list --------


def are_friends(first_id: int, second_id: int) -> bool:
    low, high = _pair_key(first_id, second_id)

    if low == high:
        return False

    with _connection() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM chat_friends
            WHERE user_low = ? AND user_high = ?
            """,
            (low, high),
        ).fetchone()

        return row is not None


def create_friend_request(
    requester_id: int,
    recipient_id: int,
) -> str:
    """Return 'created', 'pending', 'friends', or 'invalid'."""

    requester_id = int(requester_id)
    recipient_id = int(recipient_id)

    if requester_id == recipient_id:
        return "invalid"

    now = _now()
    low, high = _pair_key(requester_id, recipient_id)

    with _connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        recipient = conn.execute(
            "SELECT 1 FROM chat_profiles WHERE user_id = ?",
            (recipient_id,),
        ).fetchone()

        if recipient is None:
            conn.commit()
            return "invalid"

        if conn.execute(
            """
            SELECT 1 FROM chat_friends
            WHERE user_low = ? AND user_high = ?
            """,
            (low, high),
        ).fetchone():
            conn.commit()
            return "friends"

        existing = conn.execute(
            """
            SELECT status FROM friend_requests
            WHERE requester_id = ? AND recipient_id = ?
            """,
            (requester_id, recipient_id),
        ).fetchone()

        if existing and existing["status"] == "pending":
            conn.commit()
            return "pending"

        reverse = conn.execute(
            """
            SELECT status FROM friend_requests
            WHERE requester_id = ? AND recipient_id = ?
            """,
            (recipient_id, requester_id),
        ).fetchone()

        if reverse and reverse["status"] == "pending":
            conn.execute(
                """
                UPDATE friend_requests
                SET status = 'accepted', updated_at = ?
                WHERE requester_id = ? AND recipient_id = ?
                """,
                (now, recipient_id, requester_id),
            )

            conn.execute(
                """
                INSERT OR IGNORE INTO chat_friends(
                    user_low, user_high, created_at
                )
                VALUES (?, ?, ?)
                """,
                (low, high, now),
            )

            conn.commit()
            return "friends"

        conn.execute(
            """
            INSERT INTO friend_requests(
                requester_id,
                recipient_id,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, 'pending', ?, ?)
            ON CONFLICT(requester_id, recipient_id)
            DO UPDATE SET
                status = 'pending',
                updated_at = excluded.updated_at
            """,
            (requester_id, recipient_id, now, now),
        )

        conn.commit()

    return "created"


def respond_friend_request(
    recipient_id: int,
    requester_id: int,
    accept: bool,
) -> bool:
    recipient_id = int(recipient_id)
    requester_id = int(requester_id)
    now = _now()
    low, high = _pair_key(recipient_id, requester_id)

    with _connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            """
            SELECT status FROM friend_requests
            WHERE requester_id = ? AND recipient_id = ?
            """,
            (requester_id, recipient_id),
        ).fetchone()

        if not row or row["status"] != "pending":
            conn.commit()
            return False

        status = "accepted" if accept else "declined"

        conn.execute(
            """
            UPDATE friend_requests
            SET status = ?, updated_at = ?
            WHERE requester_id = ? AND recipient_id = ?
            """,
            (status, now, requester_id, recipient_id),
        )

        if accept:
            conn.execute(
                """
                INSERT OR IGNORE INTO chat_friends(
                    user_low, user_high, created_at
                )
                VALUES (?, ?, ?)
                """,
                (low, high, now),
            )

        conn.commit()
        return True


def list_friends(user_id: int) -> list[dict[str, Any]]:
    uid = int(user_id)

    with _connection() as conn:
        rows = conn.execute(
            """
            SELECT p.user_id, p.display_name, p.gender, p.city
            FROM chat_friends f
            JOIN chat_profiles p
              ON p.user_id = CASE
                  WHEN f.user_low = ? THEN f.user_high
                  ELSE f.user_low
              END
            WHERE f.user_low = ? OR f.user_high = ?
            ORDER BY lower(p.display_name), p.user_id
            """,
            (uid, uid, uid),
        ).fetchall()

        return [dict(row) for row in rows]


def remove_friend(user_id: int, friend_id: int) -> bool:
    low, high = _pair_key(user_id, friend_id)

    if low == high:
        return False

    with _connection() as conn:
        cur = conn.execute(
            """
            DELETE FROM chat_friends
            WHERE user_low = ? AND user_high = ?
            """,
            (low, high),
        )

        conn.execute(
            """
            UPDATE friend_requests
            SET status = 'declined', updated_at = ?
            WHERE (
                (requester_id = ? AND recipient_id = ?)
                OR
                (requester_id = ? AND recipient_id = ?)
            )
            AND status = 'pending'
            """,
            (
                _now(),
                int(user_id),
                int(friend_id),
                int(friend_id),
                int(user_id),
            ),
        )

        return cur.rowcount > 0


# Initialize tables and apply safe schema migrations.
init_db()
