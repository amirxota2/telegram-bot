"""Deprecated compatibility module.

FreeToGame is no longer used by the GameRadarBot runtime.
GameUP is the single source used by sync_games.py.
"""

from parvit.gameup import GameUPProvider


class FreeToGameProvider(GameUPProvider):
    """Compatibility alias; do not use for new code."""

    pass
