import re


def clean_text(
    text: str | None,
) -> str:

    if not text:
        return ""

    text = re.sub(
        r"<[^>]+>",
        "",
        text,
    )

    text = text.replace(
        "&nbsp;",
        " ",
    )

    text = text.replace(
        "&amp;",
        "&",
    )

    text = text.replace(
        "&quot;",
        '"',
    )

    text = text.replace(
        "&#39;",
        "'",
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def truncate(
    text: str,
    length: int = 500,
) -> str:

    if len(text) <= length:
        return text

    return (
        text[:length - 3]
        + "..."
    )


def get_platform_names(
    game: dict,
) -> list[str]:

    platforms = []

    for item in game.get(
        "platforms",
        [],
    ):

        platform = item.get(
            "platform",
            {}
        )

        name = platform.get(
            "name"
        )

        if name:
            platforms.append(name)

    return platforms


def get_genre_names(
    game: dict,
) -> list[str]:

    genres = []

    for genre in game.get(
        "genres",
        [],
    ):

        name = genre.get(
            "name"
        )

        if name:
            genres.append(name)

    return genres


def get_developer_names(
    game: dict,
) -> list[str]:

    result = []

    for developer in game.get(
        "developers",
        [],
    ):

        name = developer.get(
            "name"
        )

        if name:
            result.append(name)

    return result


def get_publisher_names(
    game: dict,
) -> list[str]:

    result = []

    for publisher in game.get(
        "publishers",
        [],
    ):

        name = publisher.get(
            "name"
        )

        if name:
            result.append(name)

    return result


def get_store_links(
    game: dict,
):

    links = []

    for item in game.get(
        "stores",
        [],
    ):

        store = item.get(
            "store",
            {}
        )

        store_name = store.get(
            "name"
        )

        url = item.get(
            "url"
        )

        if store_name and url:

            links.append(
                (
                    store_name,
                    url,
                )
            )

    return links