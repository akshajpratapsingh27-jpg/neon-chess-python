"""Select and run the configured custom or Stockfish-backed level."""

from __future__ import annotations

from .levels import EngineLevel, get_level
from .search import Engine
from .stockfish import StockfishEngine, StockfishUnavailable, find_stockfish


class EngineManager:
    def __init__(self, level: int = 4, stockfish_path: str | None = None):
        self.level = get_level(level)
        self.stockfish_path = stockfish_path
        self._custom: dict[int, Engine] = {}
        self._active_custom: Engine | None = None
        self._active_stockfish: StockfishEngine | None = None

    @property
    def stockfish_path_found(self) -> str | None:
        return find_stockfish(self.stockfish_path)

    @property
    def stockfish_available(self) -> bool:
        return self.stockfish_path_found is not None

    def set_level(self, level: int | str | None) -> EngineLevel:
        self.level = get_level(level)
        return self.level

    def choose_move(self, board, time_limit: float | None = None) -> tuple:
        level = self.level
        limit = max(0.08, float(time_limit if time_limit is not None else level.default_time))
        if level.backend == "stockfish" and self.stockfish_available:
            try:
                stockfish = StockfishEngine(self.stockfish_path, level.threads, level.hash_mb)
                self._active_stockfish = stockfish
                move, info = stockfish.choose_move(
                    board,
                    limit,
                    level.stockfish_elo,
                    level.max_depth if limit >= 2.5 else None,
                )
                info.update({"level": level.id, "level_name": level.name})
                if move:
                    return move, info
            except (OSError, StockfishUnavailable) as error:
                fallback_reason = str(error)
            else:
                fallback_reason = "Stockfish returned no legal move"
            finally:
                self._active_stockfish = None
        else:
            fallback_reason = "Stockfish executable not configured"

        engine = self._custom.setdefault(level.id, Engine(max_depth=level.max_depth))
        self._active_custom = engine
        try:
            move, info = engine.choose_move(board, limit, max_depth=level.max_depth)
        finally:
            self._active_custom = None
        info.update(
            {
                "backend": "custom",
                "level": level.id,
                "level_name": level.name,
                "fallback": level.backend == "stockfish",
            }
        )
        if level.backend == "stockfish":
            info["fallback_reason"] = fallback_reason
        return move, info

    def stop(self) -> None:
        """Request cancellation of the current search when one is running."""

        if self._active_custom:
            self._active_custom.stop_requested = True
        if self._active_stockfish:
            self._active_stockfish.close()
