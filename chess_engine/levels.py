"""Named playing levels shared by the API and browser interface."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EngineLevel:
    id: int
    name: str
    description: str
    backend: str
    target_elo: int
    default_time: float
    max_depth: int
    stockfish_elo: int | None = None
    threads: int = 1
    hash_mb: int = 64


LEVELS: tuple[EngineLevel, ...] = (
    EngineLevel(1, "BEGINNER", "Simple tactical choices", "custom", 650, 0.12, 1),
    EngineLevel(2, "CASUAL", "Short lookahead and material focus", "custom", 900, 0.25, 2),
    EngineLevel(3, "TACTICAL", "Quiescence search and combinations", "custom", 1200, 0.5, 3),
    EngineLevel(4, "CLUB", "Deeper custom search", "custom", 1550, 1.0, 5),
    EngineLevel(5, "EXPERT", "Stockfish at controlled strength", "stockfish", 1800, 1.5, 8, 1800, 1, 96),
    EngineLevel(6, "MASTER", "Full-strength Stockfish target", "stockfish", 2400, 3.0, 18, 2400, 2, 256),
)


def get_level(value: int | str | None) -> EngineLevel:
    """Return a configured level, defaulting to Club for invalid input."""

    try:
        level_id = int(value) if value is not None else 4
    except (TypeError, ValueError):
        level_id = 4
    return next((level for level in LEVELS if level.id == level_id), LEVELS[3])


def public_levels(stockfish_available: bool) -> list[dict]:
    """Serialize levels for the browser without exposing local paths."""

    return [
        {
            "id": level.id,
            "name": level.name,
            "description": level.description,
            "backend": level.backend,
            "target_elo": level.target_elo,
            "default_time": level.default_time,
            "available": level.backend != "stockfish" or stockfish_available,
        }
        for level in LEVELS
    ]
