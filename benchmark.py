"""Run a bounded deterministic engine-vs-engine benchmark.

The output is a diagnostic match record, not an Elo estimate.  Stockfish
levels are strict by default: use ``--allow-fallback`` when a custom-engine
fallback is an intentional part of the run.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Iterable, TextIO

from chess_engine import Board, EngineManager


OPENING_SEQUENCES: tuple[tuple[str, ...], ...] = (
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6"),
    ("d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "g8f6"),
    ("c2c4", "e7e5", "g1f3", "b8c6", "g2g3", "g7g6"),
    ("g1f3", "d7d5", "d2d4", "g8f6", "c2c4", "e7e6"),
    ("e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4"),
    ("e2e4", "e7e6", "d2d4", "d7d5", "b1c3", "g8f6"),
    ("e2e4", "c7c6", "d2d4", "d7d5", "b1c3", "d5e4"),
    ("d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "f8g7"),
)

_MAX_GAMES = 1_000
_MAX_SECONDS = 30.0
_MAX_PLIES = 300


def _requested_backend(manager: EngineManager) -> str:
    return str(getattr(getattr(manager, "level", None), "backend", "custom"))


def _identity(manager: EngineManager, backend: str) -> str:
    if backend == "stockfish":
        path = getattr(manager, "stockfish_path_found", None)
        return f"stockfish@{path}" if path else "stockfish@unresolved"
    return "neon-chess-custom-search"


def _stop_all(managers: Iterable[EngineManager]) -> None:
    """Stop every manager, even when an earlier stop call fails."""

    first_error: BaseException | None = None
    for manager in managers:
        try:
            manager.stop()
        except BaseException as error:  # pragma: no cover - defensive cleanup
            if first_error is None:
                first_error = error
    if first_error is not None:
        raise first_error


def play_game(
    white_level: int,
    black_level: int,
    seconds: float,
    max_plies: int = 80,
    opening_moves: Iterable[str] = (),
    allow_fallback: bool = False,
) -> dict:
    """Play one bounded game and return a truthful diagnostic record.

    ``opening_moves`` is expected to be a deterministic legal UCI sequence.
    It is applied within the ply bound so a smoke run can never exceed its
    requested limit.  Every created manager is stopped on success or error.
    """

    max_plies = max(0, min(_MAX_PLIES, int(max_plies)))
    seconds = max(0.01, min(_MAX_SECONDS, float(seconds)))
    board = Board()
    managers: dict[str, EngineManager] = {}
    observed_backend: dict[str, str] = {}
    observed_identity: dict[str, str] = {}
    total_nodes = {"white": 0, "black": 0}
    applied_opening: list[str] = []
    started = time.monotonic()

    try:
        # Construct separately so a failure while creating the second manager
        # still leaves the first one in the cleanup set.
        managers["white"] = EngineManager(white_level)
        managers["black"] = EngineManager(black_level)
        for side, manager in managers.items():
            if _requested_backend(manager) == "stockfish" and not manager.stockfish_available:
                if not allow_fallback:
                    raise RuntimeError(
                        f"Stockfish is unavailable for {side} level; rerun with --allow-fallback "
                        "to permit the custom backend"
                    )

        for requested in opening_moves:
            if len(board.history) >= max_plies or board.game_status() != "playing":
                break
            try:
                board.push_uci(requested)
            except ValueError as error:
                raise ValueError(f"Illegal benchmark opening move: {requested}") from error
            applied_opening.append(requested)

        while len(board.history) < max_plies and board.game_status() == "playing":
            side = "white" if board.white_to_move else "black"
            manager = managers[side]
            move, info = manager.choose_move(board, seconds)
            info = info or {}
            requested_backend = _requested_backend(manager)
            backend = str(info.get("backend") or requested_backend)
            if requested_backend == "stockfish" and backend != "stockfish" and not allow_fallback:
                raise RuntimeError(
                    f"{side} level fell back from Stockfish to {backend}; "
                    "rerun with --allow-fallback to permit the custom backend"
                )
            observed_backend[side] = backend
            observed_identity[side] = _identity(manager, backend)
            if move is None:
                break

            legal_by_uci = {legal.uci: legal for legal in board.legal_moves()}
            legal_move = legal_by_uci.get(move.uci)
            if legal_move is None:
                raise RuntimeError(f"Engine returned an illegal move: {move.uci}")
            total_nodes[side] += int(info.get("nodes", 0) or 0)
            board.make_move(legal_move)

        status = board.game_status()
        result = (
            "1-0"
            if status == "checkmate_white"
            else "0-1"
            if status == "checkmate_black"
            else "1/2-1/2"
            if status != "playing"
            else "*"
        )
        for side, manager in managers.items():
            if side not in observed_backend:
                backend = "stockfish" if _requested_backend(manager) == "stockfish" and manager.stockfish_available else "custom"
                observed_backend[side] = backend
                observed_identity[side] = _identity(manager, backend)
        return {
            "result": result,
            "status": status,
            "unfinished": status == "playing",
            "plies": len(board.history),
            "max_plies": max_plies,
            "fen": board.to_fen(),
            "nodes": total_nodes,
            "seconds": round(time.monotonic() - started, 3),
            "opening": applied_opening,
            "backend": observed_backend,
            "engine_identity": observed_identity,
            "levels": {"white": white_level, "black": black_level},
        }
    finally:
        # If gameplay raises, cleanup still attempts both managers.  A cleanup
        # error is allowed to surface only when there is no active exception.
        active_exception = sys.exc_info()[0] is not None
        try:
            _stop_all(managers.values())
        except BaseException:
            if not active_exception:
                raise


def run_benchmark(
    games: int = 10,
    seconds: float = 0.5,
    white_level: int = 4,
    black_level: int = 4,
    max_plies: int = 80,
    allow_fallback: bool = False,
    progress: bool = True,
    progress_stream: TextIO | None = None,
) -> dict:
    """Run paired-color games with deterministic, varied openings."""

    games = max(1, min(_MAX_GAMES, int(games)))
    seconds = max(0.08, min(_MAX_SECONDS, float(seconds)))
    max_plies = max(0, min(_MAX_PLIES, int(max_plies)))
    progress_stream = progress_stream or sys.stderr
    results: list[dict] = []
    for index in range(games):
        # Swap the configured levels on alternate games so each level gets
        # both colors in every pair.
        white = white_level if index % 2 == 0 else black_level
        black = black_level if index % 2 == 0 else white_level
        detail = play_game(
            white,
            black,
            seconds,
            max_plies,
            OPENING_SEQUENCES[index % len(OPENING_SEQUENCES)],
            allow_fallback,
        )
        results.append(detail)
        if progress:
            print(
                f"game {index + 1}/{games}: {detail['result']} "
                f"({detail['plies']} plies, {detail['backend']['white']}/"
                f"{detail['backend']['black']})",
                file=progress_stream,
                flush=True,
            )

    return {
        "white_level": white_level,
        "black_level": black_level,
        "games": games,
        "seconds_per_move": seconds,
        "max_plies": max_plies,
        "paired_colors": True,
        "wins_white": sum(item["result"] == "1-0" for item in results),
        "wins_black": sum(item["result"] == "0-1" for item in results),
        "draws": sum(item["result"] == "1/2-1/2" for item in results),
        "unfinished": sum(item["unfinished"] for item in results),
        "actual_backends": {
            side: sorted({item["backend"][side] for item in results}) for side in ("white", "black")
        },
        "engine_identities": {
            side: sorted({item["engine_identity"][side] for item in results})
            for side in ("white", "black")
        },
        "games_detail": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Neon Chess engine levels")
    parser.add_argument("--games", type=int, default=10)
    parser.add_argument("--seconds", type=float, default=0.5)
    parser.add_argument("--white-level", type=int, default=4)
    parser.add_argument("--black-level", type=int, default=4)
    parser.add_argument("--max-plies", type=int, default=80)
    parser.add_argument(
        "--allow-fallback",
        action="store_true",
        help="permit Stockfish levels to use the custom backend when unavailable",
    )
    args = parser.parse_args()
    try:
        summary = run_benchmark(
            args.games,
            args.seconds,
            args.white_level,
            args.black_level,
            args.max_plies,
            args.allow_fallback,
        )
    except (RuntimeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
