"""Best-effort online game discovery for GameRadarBot.

Sources:
- GameUP: Persian game catalog, including genre result pages.
- Steam Store search/details: broad PC game catalog.

Online failures are deliberately non-fatal: the local SQLite catalog remains usable.
"""
from __future__ import annotations

import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT
from parvit.gameup import GameUPProvider

logger = logging.getLogger(__name__)

# Map Steam's genre labels to the local Persian genre taxonomy where possible.
STEAM_GENRE_FA = {
    "action": "اکشن",
    "adventure": "ماجراجویی",
    "role-playing": "نقش آفرینی",
    "rpg": "نقش آفرینی",
    "strategy": "استراتژیک",
    "indie": "بازی مستقل",
    "shooter": "تیراندازی - شوتر",
    "platformer": "پلتفرمر",
    "puzzle": "پازل",
    "racing": "رانندگی",
    "simulation": "شبیه سازی",
    "sports": "ورزشی",
    "horror": "ترسناک",
    "survival": "بقا",
    "stealth": "مخفی کاری",
    "massively multiplayer": "چندنفره آنلاین",
    "casual": "بازی مستقل",
}

GENRE_ALIASES = [
    ("اکشن ماجراجویی", "اکشن ماجراجویی"),
    ("action adventure", "اکشن ماجراجویی"),
    ("ترسناک", "ترسناک"), ("horror", "ترسناک"), ("scary", "ترسناک"),
    ("بقا", "بقا"), ("survival", "بقا"),
    ("استراتژیک", "استراتژیک"), ("strategy", "استراتژیک"), ("strategic", "استراتژیک"),
    ("نقش آفرینی", "نقش آفرینی"), ("نقش‌آفرینی", "نقش آفرینی"), ("rpg", "نقش آفرینی"), ("role playing", "نقش آفرینی"),
    ("تیراندازی", "تیراندازی - شوتر"), ("شوتر", "تیراندازی - شوتر"), ("shooter", "تیراندازی - شوتر"), ("fps", "تیراندازی - شوتر"),
    ("پلتفرمر", "پلتفرمر"), ("platformer", "پلتفرمر"),
    ("مترویدوانیا", "مترویدوانیا"), ("metroidvania", "مترویدوانیا"),
    ("پازل", "پازل"), ("puzzle", "پازل"),
    ("مخفی کاری", "مخفی کاری"), ("مخفی‌کاری", "مخفی کاری"), ("stealth", "مخفی کاری"),
    ("رانندگی", "رانندگی"), ("racing", "رانندگی"),
    ("شبیه سازی", "شبیه سازی"), ("شبیه‌سازی", "شبیه سازی"), ("simulation", "شبیه سازی"),
    ("علمی تخیلی", "علمی تخیلی"), ("علمی‌تخیلی", "علمی تخیلی"), ("sci-fi", "علمی تخیلی"), ("science fiction", "علمی تخیلی"),
    ("بازی مستقل", "بازی مستقل"), ("indie", "بازی مستقل"),
    ("تاکتیکال", "تاکتیکال"), ("tactical", "تاکتیکال"),
    ("ورزشی", "ورزشی"), ("sports", "ورزشی"), ("sport", "ورزشی"),
    ("جهان باز", "جهان باز"), ("جهان‌باز", "جهان باز"), ("open world", "جهان باز"), ("open-world", "جهان باز"),
    ("ماجراجویی", "ماجراجویی"), ("adventure", "ماجراجویی"),
    ("اکشن", "اکشن"), ("action", "اکشن"),
    ("پارتی", "پارتی گیمز"), ("party games", "پارتی گیمز"),
]


def detect_genre(text: str) -> str | None:
    """Return the canonical Persian genre mentioned in a query, if any."""
    normalized = re.sub(r"\s+", " ", (text or "").replace("‌", " ").casefold()).strip()
    for phrase, genre in sorted(GENRE_ALIASES, key=lambda x: len(x[0]), reverse=True):
        needle = phrase.casefold()
        if needle in normalized:
            return genre
    return None


def _clean_description(value: str | None) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _page_game_links(soup: BeautifulSoup, provider: GameUPProvider) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    # The existing sync tool uses the /game/ path; support /games/ as well.
    for anchor in soup.select('a[href*="/game/"], a[href*="/games/"]'):
        if anchor.find_parent(["nav", "footer", "header"]):
            continue
        href = anchor.get("href")
        if not href:
            continue
        try:
            url = provider._normalize_game_url(href)
        except Exception:
            continue
        if url and url not in seen and "gameup.ir" in url:
            seen.add(url)
            links.append(url)
    return links


def fetch_gameup_games(query: str | None = None, genre: str | None = None, limit: int = 5) -> list[dict]:
    """Fetch and parse a few GameUP results. No writes are performed here."""
    timeout = max(3, min(int(REQUEST_TIMEOUT or 8), 7))
    provider = GameUPProvider(timeout=timeout)
    if genre:
        slug = provider.GENRE_MAP.get(genre)
        if not slug:
            # If passed an English or alias label, canonicalise it first.
            canonical = detect_genre(genre) or genre
            slug = provider.GENRE_MAP.get(canonical)
        if not slug:
            return []
        url = f"{provider.BASE_URL}/search?genre={quote_plus(slug)}"
    elif query:
        url = f"{provider.BASE_URL}/search/?search={quote_plus(query.strip())}"
    else:
        url = f"{provider.BASE_URL}/search/"

    try:
        response = provider._get(url)
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception as exc:
        logger.info("GameUP lookup unavailable: %s", exc)
        return []

    result: list[dict] = []
    for game_url in _page_game_links(soup, provider)[: max(1, min(limit, 8))]:
        try:
            game = provider.get_game_details(game_url)
        except Exception as exc:
            logger.debug("GameUP details failed for %s: %s", game_url, exc)
            continue
        if not isinstance(game, dict) or not (game.get("name") or game.get("title")):
            continue
        game.setdefault("url", game_url)
        game.setdefault("game_id", game_url)
        game.setdefault("source", "gameup")
        # Make sure optional fields have predictable shapes for SQLite.
        if not game.get("genres") and game.get("genre"):
            game["genres"] = game["genre"] if isinstance(game["genre"], list) else [game["genre"]]
        if not game.get("platforms") and game.get("platform"):
            game["platforms"] = game["platform"] if isinstance(game["platform"], list) else [game["platform"]]
        if not game.get("description"):
            game["description"] = game.get("summary") or game.get("short_description") or ""
        result.append(game)
    return result


def fetch_steam_games(query: str, limit: int = 4) -> list[dict]:
    """Search Steam and turn the public store details into our local game schema."""
    query = (query or "").strip()
    if not query:
        return []
    timeout = 5
    session = requests.Session()
    session.headers.update({"User-Agent": "GameRadarBot/1.0 (game discovery)"})
    try:
        response = session.get(
            "https://store.steampowered.com/api/storesearch/",
            params={"term": query, "l": "english", "cc": "us"},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.info("Steam search unavailable: %s", exc)
        return []

    result: list[dict] = []
    items = payload.get("items", []) if isinstance(payload, dict) else []
    for item in items[: max(1, min(limit, 5))]:
        app_id = item.get("id")
        if not app_id:
            continue
        try:
            detail_response = session.get(
                "https://store.steampowered.com/api/appdetails/",
                params={"appids": app_id, "l": "english", "cc": "us"},
                timeout=timeout,
            )
            detail_response.raise_for_status()
            envelope = detail_response.json().get(str(app_id), {})
            if not envelope.get("success"):
                continue
            data = envelope.get("data") or {}
        except Exception as exc:
            logger.debug("Steam app detail unavailable for %s: %s", app_id, exc)
            continue

        platforms_data = data.get("platforms") or {}
        platforms = []
        if platforms_data.get("windows"):
            platforms.append("Windows")
        if platforms_data.get("mac"):
            platforms.append("macOS")
        if platforms_data.get("linux"):
            platforms.append("Linux")

        genres = []
        for entry in data.get("genres") or []:
            name = str(entry.get("description") or "").strip()
            if not name:
                continue
            label = STEAM_GENRE_FA.get(name.casefold(), name)
            if label not in genres:
                genres.append(label)

        release = (data.get("release_date") or {}).get("date") or ""
        year_match = re.search(r"(?<!\d)(?:19|20|21)\d{2}(?!\d)", release)
        release_date = year_match.group(0) if year_match else ""
        # Steam appdetails exposes Metacritic, not a comparable 5-star user
        # rating. Leave rating empty instead of presenting a converted score as
        # if it were the same metric used by GameUP.
        rating = None

        developers = data.get("developers") or []
        publishers = data.get("publishers") or []
        game = {
            "game_id": f"steam:{app_id}",
            "name": data.get("name") or item.get("name") or "",
            "description": _clean_description(data.get("short_description")),
            "short_description": _clean_description(data.get("short_description")),
            "genres": genres,
            "platforms": platforms,
            "rating": rating,
            "cover_url": data.get("header_image") or item.get("tiny_image") or "",
            "release_date": release_date,
            "developer": ", ".join(str(x) for x in developers),
            "publisher": ", ".join(str(x) for x in publishers),
            "url": f"https://store.steampowered.com/app/{app_id}/",
            "source": "steam",
        }
        if game["name"]:
            result.append(game)
    return result


def search_online_games(query: str, limit: int = 8) -> list[dict]:
    """Query GameUP and Steam in parallel; return raw game dictionaries."""
    query = (query or "").strip()
    if not query:
        return []
    pool = ThreadPoolExecutor(max_workers=2)
    futures = [
        pool.submit(fetch_gameup_games, query=query, limit=max(2, min(limit, 5))),
        pool.submit(fetch_steam_games, query=query, limit=max(2, min(limit, 4))),
    ]
    raw: list[dict] = []
    try:
        for future in as_completed(futures, timeout=12):
            try:
                raw.extend(future.result())
            except Exception as exc:
                logger.debug("Online source failed: %s", exc)
            # Limit work after a useful result set has been found.
            if len(raw) >= limit:
                break
    except TimeoutError:
        logger.info("Online game lookup reached its time limit")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return raw[:limit]


def search_online_genre(genre: str, limit: int = 8) -> list[dict]:
    """Fetch the relevant GameUP genre page and return parsed game dictionaries."""
    canonical = detect_genre(genre) or genre
    return fetch_gameup_games(genre=canonical, limit=limit)


def search_online_catalog(limit: int = 8) -> list[dict]:
    """Fetch a few current catalog entries when a new local install has little data."""
    return fetch_gameup_games(limit=limit)
