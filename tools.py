import html
import re


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", str(text))
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def escape_html(text: str | None) -> str:
    return html.escape(clean_text(text))


def truncate(text: str | None, length: int = 500) -> str:
    text = clean_text(text)
    if len(text) <= length:
        return text
    return text[: max(length - 3, 1)] + "..."


def _names(values):
    result = []
    for item in values or []:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("name") or item.get("platform", {}).get("name") or ""
        else:
            name = str(item)
        if name and name not in result:
            result.append(name)
    return result


def get_platform_names(game: dict) -> list[str]:
    return _names(game.get("platforms") or game.get("platform"))


def get_genre_names(game: dict) -> list[str]:
    return _names(game.get("genres") or game.get("genre"))


def get_developer_names(game: dict) -> list[str]:
    if game.get("developer"):
        return [str(game["developer"])]
    result = []
    for item in game.get("involved_companies") or []:
        if item.get("developer"):
            name = (item.get("company") or {}).get("name")
            if name:
                result.append(name)
    return result


def get_publisher_names(game: dict) -> list[str]:
    if game.get("publisher"):
        return [str(game["publisher"])]
    result = []
    for item in game.get("involved_companies") or []:
        if item.get("publisher"):
            name = (item.get("company") or {}).get("name")
            if name:
                result.append(name)
    return result


def get_store_links(game: dict):
    links = []
    if game.get("url"):
        links.append(("GameUP", game["url"]))

    for item in game.get("external_games") or game.get("stores") or []:
        url = item.get("url")
        if not url:
            continue
        source = item.get("external_game_source") or item.get("store") or {}
        name = source.get("name") or "Link"
        links.append((name, url))

    return links
