"""Game catalogue service with local-first discovery and upcoming releases."""
from __future__ import annotations

import logging
import re
import time
from threading import Lock, Thread

import database
from game_sources import (
    detect_genre,
    search_online_catalog,
    search_online_games,
    search_online_genre,
)

logger = logging.getLogger(__name__)

# Upcoming releases refresh in the background at most once per 15 minutes.
# Existing database results are returned immediately while the cache refreshes.
_UPCOMING_REFRESH_INTERVAL = 15 * 60.0
_UPCOMING_STATE_LOCK = Lock()
_UPCOMING_REFRESHING = False
_UPCOMING_LAST_REFRESH = 0.0
_UPCOMING_ONLINE_CACHE: list[dict] = []


_STOP_PHRASES = (
    "لطفا", "لطفاً", "میشه", "می شه", "معرفی کن", "معرفی کنین",
    "معرفی کنید", "پیشنهاد بده", "پیشنهاد کن", "پیشنهاد میدی",
    "پیشنهاد می‌دی", "به من بگو", "پیدا کن", "پیدا کنین", "بهم بگو",
    "اطلاعات بده", "اطلاعات", "درباره", "در مورد", "راجب", "راجع به",
    "بهترین", "جدیدترین", "بازی های", "بازی‌های", "بازی هایی", "بازی‌هایی",
    "بازی", "games", "game", "recommend", "recommendation", "suggest",
    "show me", "tell me about", "best", "latest", "released in",
)


def _normalise_name(value: str | None) -> str:
    value = (value or "").casefold().strip()
    value = value.replace("’", "'").replace("‌", " ")
    return re.sub(r"[^\w]+", "", value, flags=re.UNICODE)


def _clean_query(query: str) -> str:

    value = (query or "").strip()
    leading = (
        r"^(?:(?:لطفا|لطفاً|میشه|می شه|بهترین|جدیدترین|پیشنهاد(?:ی)?|معرفی|"
        r"درباره|در مورد|راجع به|راجب|اطلاعات(?: بده)?|مشخصات|بهم بگو|به من بگو|"
        r"میخوام|می‌خوام|بازی(?:‌های|های| هایی| هایی)?|games?|recommend|suggest|show me|best|latest|"
        r"what is|what's|tell me about|details for|information about)\s+)+"
    )
    trailing = (
        r"\s+(?:(?:رو|را)?\s*(?:معرفی کن|معرفی کنین|پیشنهاد بده|پیدا کن|بگو|"
        r"چیه|چیست|چطوره|خوبه|ارزش بازی دارد|ارزش بازی کردن دارد|توضیح بده|"
        r"show me|please|is it good|worth playing|release date|details|information))$"
    )
    value = re.sub(leading, "", value, flags=re.IGNORECASE).strip()
    value = re.sub(trailing, "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"[؟?!،,:;]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value or (query or "").strip()


def _extract_year(query: str) -> int | None:
    """Treat a number as a year only when the query appears to ask for a year.

    This prevents a title such as Cyberpunk 2077 from being mistaken for a year filter.
    """
    match = re.search(r"(?<!\d)(?:19|20|21)\d{2}(?!\d)", query or "")
    if not match:
        return None
    year = int(match.group(0))
    text = (query or "").casefold().replace("‌", " ")
    before = text[:match.start()].rstrip()

    english_cue = re.search(r"(?<![a-z])(?:year|released|release|in|from|for)(?![a-z])\s*$", before)
    persian_cue = re.search(r"(?:سال انتشار|در سال|برای سال|سال|انتشار|منتشر)\s*$", before)
    if english_cue or persian_cue:
        return year

    rest = (text[:match.start()] + " " + text[match.end():]).strip()
    cleaned_rest = _clean_query(rest).casefold().strip()
    generic_words = {
        "", "بازی", "بازی ها", "بازی‌های", "بازیهای", "بازی هایی", "بازی‌هایی",
        "game", "games", "best games", "بهترین بازی", "بهترین بازی ها",
        "معرفی بازی", "پیشنهاد بازی", "new games", "latest games", "های",
    }
    if cleaned_rest in generic_words:
        return year
    if detect_genre(cleaned_rest) and _has_recommendation_intent(query):
        return year
    return None


def _has_recommendation_intent(query: str) -> bool:
    text = (query or "").casefold().replace("‌", " ").strip()
    markers = (
        "بازی", "معرفی", "پیشنهاد", "ژانر", "بهترین", "شبیه", "مثل",
        "games", "game", "recommend", "suggest", "best", "similar", "like", "genre",
    )
    if any(marker in text for marker in markers):
        return True

    return bool(detect_genre(text) and len(text.split()) == 1)


def _is_similar_query(query: str) -> bool:
    text = (query or "").casefold().replace("‌", " ")
    return any(token in text for token in ("شبیه", "مثل", "مشابه", "similar to", "games like", "game like", "like "))


def _similar_title(query: str) -> str:
    value = (query or "").strip()
    patterns = (
        r".*?(?:بازی(?:های)?\s*)?(?:شبیه|مثل|مشابه)\s+",
        r".*?(?:games?\s+like|similar\s+to|like)\s+",
    )
    for pattern in patterns:
        candidate = re.sub(pattern, "", value, flags=re.IGNORECASE).strip()
        if candidate and candidate != value:
            value = candidate
            break
    value = re.sub(r"^(?:بازی|game)\s+", "", value, flags=re.IGNORECASE).strip()
    return _clean_query(value)


_RELEASE_CALENDAR_URL = "https://www.gamesradar.com/video-game-release-dates/"
_MONTH_NUMBERS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}
_RELEASE_LINE_RE = re.compile(
    r"^(?P<title>.+?)\s*(?:\((?P<platforms>[^()]{1,120})\))?\s*[–—−-]\s*"
    r"(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(?P<day>\d{1,2})(?:,?\s+(?P<year>20\d{2}))?(?:\s*[–—−-].*)?$",
    re.IGNORECASE,
)


def _scrape_upcoming_release_calendar(limit: int = 100) -> list[dict]:
    """Read confirmed upcoming releases from GamesRadar's public release calendar.

    The scraper only returns games with a concrete month/day. The year is taken
    from the entry when present or from the nearest year heading on the page.
    """
    from datetime import date
    from urllib.parse import urljoin

    import requests
    from bs4 import BeautifulSoup

    today = date.today()
    response = requests.get(
        _RELEASE_CALENDAR_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; GameRadarBot/1.0)"},
        timeout=12,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    current_year = today.year
    found: list[dict] = []
    seen: set[str] = set()

    # Preserve document order so a heading such as "2027" changes the year
    # used for the date-only entries that follow it.
    for node in soup.find_all(["h2", "h3", "h4", "li", "p"]):
        text = " ".join(node.get_text(" ", strip=True).split())
        if not text:
            continue

        if node.name in {"h2", "h3", "h4"}:
            year_heading = re.fullmatch(r"(?:TBC\s+)?(20\d{2})", text, re.IGNORECASE)
            if year_heading:
                current_year = int(year_heading.group(1))
            continue

        match = _RELEASE_LINE_RE.match(text)
        if not match:
            continue

        title = match.group("title").strip(" •-*–—\t")
        if not title or len(title) > 160:
            continue

        month_number = _MONTH_NUMBERS[match.group("month").casefold()]
        year = int(match.group("year") or current_year)
        day_number = int(match.group("day"))
        try:
            release_day = date(year, month_number, day_number)
        except ValueError:
            continue
        if release_day < today:
            continue

        key = _normalise_name(title)
        if not key or key in seen:
            continue
        seen.add(key)

        raw_platforms = (match.group("platforms") or "").strip()
        platforms = [part.strip() for part in raw_platforms.split(",") if part.strip()]

        game_url = _RELEASE_CALENDAR_URL
        for anchor in node.find_all("a", href=True):
            anchor_text = " ".join(anchor.get_text(" ", strip=True).split())
            if anchor_text and anchor_text.casefold() in title.casefold():
                game_url = urljoin(_RELEASE_CALENDAR_URL, anchor["href"])
                break

        slug = key[:90]
        found.append({
            "name": title,
            "title": title,
            "game_id": f"gamesradar:{slug}",
            "release_date": release_day.isoformat(),
            "description": (
                f"تاریخ انتشار اعلام‌شده: {release_day.isoformat()}\n"
                "منبع: تقویم انتشار بازی‌های GamesRadar. تاریخ‌ها ممکن است تغییر کنند."
            ),
            "platforms": platforms,
            "genres": [],
            "url": game_url,
            "source": "gamesradar",
        })
        if len(found) >= max(1, min(int(limit), 100)):
            break

    return found


def _store_online_games(items: list[dict]) -> list[dict]:
    stored: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        try:
            # Normalize provider fields before passing them to the SQLite schema.
            game = dict(item)
            game.setdefault("name", game.get("title") or "")
            if not game.get("game_id"):
                game["game_id"] = game.get("url") or game.get("id")
            if not game.get("description"):
                game["description"] = game.get("summary") or game.get("short_description") or ""
            if not game.get("genres") and game.get("genre"):
                genre = game["genre"]
                game["genres"] = genre if isinstance(genre, list) else [genre]
            if not game.get("platforms") and game.get("platform"):
                platform = game["platform"]
                game["platforms"] = platform if isinstance(platform, list) else [platform]
            local_id = database.save_game(game)
            if local_id is not None:
                found = database.get_game(local_id)
                if found:
                    stored.append(found)
        except Exception:
            logger.exception("Could not save an online game result")
    return stored


def _merge_games(*groups: list[dict], limit: int = 100) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for group in groups:
        for game in group or []:
            if not isinstance(game, dict) or not game.get("id"):
                continue
            key = _normalise_name(game.get("name") or game.get("title"))
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(game)
            if len(merged) >= limit:
                return merged
    return merged


def _paginate(items: list[dict], page: int, page_size: int) -> list[dict]:
    page = max(int(page), 1)
    page_size = max(min(int(page_size), 100), 1)
    start = (page - 1) * page_size
    return items[start:start + page_size]


class GameService:
    """Local-first service. Online sources are queried on misses/short lists."""

    def get_games(self, page: int = 1, page_size: int = 50, **kwargs):
        del kwargs
        local = database.get_games(page=1, limit=100)
        # First-run installs often contain only a few seeded games. Enrich the
        # catalogue with a small live sample instead of returning the same five.
        if len(local) < 12:
            try:
                remote = _store_online_games(search_online_catalog(limit=8))
                local = _merge_games(local, remote, limit=100)
            except Exception:
                logger.exception("Could not enrich discovery catalogue")
        return _paginate(local, page, page_size)

    def search_games(self, query: str, page: int = 1, page_size: int = 50):
        original = (query or "").strip()
        if not original:
            return []

        year = _extract_year(original)
        # Prefer an exact local title match over interpreting a word in its title
        # as a genre (for example, a game whose title contains "Horror").
        exact_local = database.search_games(original, limit=100)
        exact_key = _normalise_name(original)
        if exact_key and any(_normalise_name(g.get("name")) == exact_key for g in exact_local):
            return _paginate(exact_local, page, page_size)
        genre = detect_genre(original) if _has_recommendation_intent(original) else None

        # "Games like X" should look up X, then recommend titles sharing its genre.
        if _is_similar_query(original):
            title_query = _similar_title(original)
            base = database.search_games(title_query, limit=10)
            if len(base) < 2:
                base = _merge_games(
                    base,
                    _store_online_games(search_online_games(title_query, limit=8)),
                    limit=10,
                )
            recommendations: list[dict] = []
            for game in base[:3]:
                genres = game.get("genres") or game.get("genre") or []
                if isinstance(genres, str):
                    genres = [genres]
                for item in genres:
                    genre_text = item.get("name", "") if isinstance(item, dict) else str(item)
                    if genre_text:
                        recommendations.extend(database.get_games_by_genre(genre_text, limit=20))
            recommendations = _merge_games(recommendations, base, limit=100)
            if len(recommendations) < 5 and base:
                first_genres = base[0].get("genres") or base[0].get("genre") or []
                if isinstance(first_genres, str):
                    first_genres = [first_genres]
                if first_genres:
                    label = first_genres[0].get("name", "") if isinstance(first_genres[0], dict) else str(first_genres[0])
                    if label:
                        try:
                            recommendations = _merge_games(
                                recommendations,
                                _store_online_games(search_online_genre(label, limit=8)),
                                limit=100,
                            )
                        except Exception:
                            logger.exception("Could not fetch similar games by genre")
            if not recommendations:
                recommendations = base
            return _paginate(recommendations, page, page_size)

        if year:
            items = database.get_games_by_year(year, limit=100)
            if genre:
                items = [g for g in items if any(genre.casefold() in str(x).casefold() for x in (g.get("genres") or []))]
            if not items and database.count_games() < 25:
                remote = _store_online_games(search_online_catalog(limit=8))
                items = [g for g in remote if _extract_year(str(g.get("release_date") or "")) == year]
            return _paginate(items, page, page_size)

        if genre:
            local = database.get_games_by_genre(genre, limit=100)
            if len(local) < 8:
                try:
                    remote = _store_online_games(search_online_genre(genre, limit=8))
                    local = _merge_games(local, remote, limit=100)
                except Exception:
                    logger.exception("Online genre search failed")
   
            clean = _clean_query(original)
            if clean and len(local) < 3:
                local = _merge_games(local, database.search_games(clean, limit=10), limit=100)
            return _paginate(local, page, page_size)

        clean = _clean_query(original)
        local = database.search_games(clean, limit=100)
   
        if len(local) < 5:
            try:
                remote = _store_online_games(search_online_games(clean, limit=10))
                local = _merge_games(local, remote, limit=100)
            except Exception:
                logger.exception("Online game search failed")
        return _paginate(local, page, page_size)

    def get_game_details(self, game_id):
        try:
            return database.get_game(int(game_id))
        except (TypeError, ValueError):
            return database.get_game_by_external_id(str(game_id))

    def get_popular_games(self, page: int = 1, page_size: int = 50):
        local = database.get_popular_games(limit=100)
        if len(local) < 8:
            try:
                remote = _store_online_games(search_online_catalog(limit=8))
                local = _merge_games(local, remote, limit=100)
                local.sort(key=lambda game: (game.get("rating") is not None, game.get("rating") or 0), reverse=True)
            except Exception:
                logger.exception("Could not enrich popular list")
        return _paginate(local, page, page_size)

    def get_games_by_year(self, year: int, page: int = 1, page_size: int = 50):
        local = database.get_games_by_year(int(year), limit=100)
        if not local and database.count_games() < 25:
            try:
                remote = _store_online_games(search_online_catalog(limit=8))
                local = [game for game in remote if _extract_year(str(game.get("release_date") or "")) == int(year)]
            except Exception:
                logger.exception("Could not enrich year filter")
        return _paginate(local, page, page_size)

    def get_games_by_genre(self, genre: str, page: int = 1, page_size: int = 50):
        local = database.get_games_by_genre(genre, limit=100)
        if len(local) < 8:
            try:
                remote = _store_online_games(search_online_genre(genre, limit=8))
                local = _merge_games(local, remote, limit=100)
            except Exception:
                logger.exception("Genre discovery failed")
        return _paginate(local, page, page_size)

    def get_games_by_platform(self, platform: str, page: int = 1, page_size: int = 50):
        return _paginate(database.get_games_by_platform(platform, limit=100), page, page_size)

    @staticmethod
    def _refresh_upcoming_online():
        """Refresh future releases in a daemon thread; never block the bot UI."""
        global _UPCOMING_REFRESHING, _UPCOMING_LAST_REFRESH, _UPCOMING_ONLINE_CACHE
        try:
            scraped = _scrape_upcoming_release_calendar(limit=100)
            online = _store_online_games(scraped)
            with _UPCOMING_STATE_LOCK:
                _UPCOMING_ONLINE_CACHE = online
                _UPCOMING_LAST_REFRESH = time.monotonic()
        except Exception:
            logger.exception("Could not refresh GamesRadar upcoming releases")
            with _UPCOMING_STATE_LOCK:
                # Cool down after failures so every button click doesn't launch
                # another request to an unavailable site.
                _UPCOMING_LAST_REFRESH = time.monotonic()
        finally:
            with _UPCOMING_STATE_LOCK:
                _UPCOMING_REFRESHING = False

    @staticmethod
    def _schedule_upcoming_refresh():
        global _UPCOMING_REFRESHING
        now = time.monotonic()
        with _UPCOMING_STATE_LOCK:
            if _UPCOMING_REFRESHING:
                return
            if now - _UPCOMING_LAST_REFRESH < _UPCOMING_REFRESH_INTERVAL:
                return
            _UPCOMING_REFRESHING = True

        Thread(
            target=GameService._refresh_upcoming_online,
            name="upcoming-release-refresh",
            daemon=True,
        ).start()

    def get_upcoming_games(self, page: int = 1, page_size: int = 50):
        """Return local releases immediately and refresh the public calendar in background."""
        local = database.get_upcoming_games(limit=100)

        with _UPCOMING_STATE_LOCK:
            cached_online = list(_UPCOMING_ONLINE_CACHE)
        if local or cached_online:
            # Stale-while-revalidate: show what is already known immediately.
            self._schedule_upcoming_refresh()
            combined = _merge_games(local, cached_online, limit=100)
        else:
            # Fresh installation: there is no useful local result yet, so do
            # one synchronous fetch instead of telling the user nothing exists.
            try:
                scraped = _scrape_upcoming_release_calendar(limit=100)
                online = _store_online_games(scraped)
                with _UPCOMING_STATE_LOCK:
                    _UPCOMING_ONLINE_CACHE = online
                    _UPCOMING_LAST_REFRESH = time.monotonic()
                combined = _merge_games(local, online, limit=100)
            except Exception:
                logger.exception("Could not fetch initial GamesRadar releases")
                combined = local

        combined.sort(
            key=lambda game: (
                str(game.get("release_date") or "9999-12-31"),
                str(game.get("name") or game.get("title") or "").casefold(),
            )
        )
        return _paginate(combined, page, page_size)

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
        if isinstance(values, str):
            values = [values]
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
        if isinstance(values, str):
            values = [values]
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
            links.append(("GameUP" if game.get("source") != "steam" else "Steam", game["url"]))
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
    def get_available_genres():
        known = {
            "استراتژیک", "اکشن", "ماجراجویی", "مخفی کاری", "نقش آفرینی",
            "تیراندازی - شوتر", "پلتفرمر", "پازل", "مترویدوانیا", "ترسناک",
            "رانندگی", "شبیه سازی", "علمی تخیلی", "بازی مستقل", "بقا",
            "تاکتیکال", "پارتی گیمز", "اکشن ماجراجویی", "ورزشی", "جهان باز",
        }
        return sorted(set(database.get_available_genres()) | known, key=str.casefold)

    @staticmethod
    def count_games():
        return database.count_games()
