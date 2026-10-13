"""Threaded local web server and authoritative chess game service."""

from __future__ import annotations

import json
import mimetypes
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

from chess_engine import Board, EngineManager, export_pgn, get_level, import_pgn, san_history
from chess_engine.core import Move
from chess_engine.levels import public_levels

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"


class GameService:
    """Own the game position and run engine searches away from HTTP threads."""

    def __init__(self):
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="neon-engine")
        self.board = Board()
        self.engine_manager = EngineManager(level=4)
        self.engine_time = 0.65
        self.player_color = "white"
        self.engine_level = 4
        self.last_engine_info = self._empty_engine_info()
        self.engine_future: Future | None = None
        self.engine_job_id: str | None = None
        self.engine_error: str | None = None
        self.position_version = 0
        self.game_id = uuid.uuid4().hex
        self.resigned_by: str | None = None
        self.clock_limit = 600.0
        self.clocks = {"white": self.clock_limit, "black": self.clock_limit}
        self.clock_updated_at = time.monotonic()

    @staticmethod
    def _empty_engine_info() -> dict:
        return {"depth": 0, "nodes": 0, "nps": 0, "score": 0, "pv": [], "backend": "idle"}

    def reset(self, settings: dict | None = None) -> dict:
        with self.lock:
            settings = settings or {}
            self.stop_engine()
            self.board = Board()
            self.game_id = uuid.uuid4().hex
            self.player_color = settings.get("player_color", "white")
            if self.player_color not in ("white", "black"):
                self.player_color = "white"
            self.engine_time = max(0.08, min(30.0, float(settings.get("engine_time", 0.65))))
            self.clock_limit = max(60.0, min(7200.0, float(settings.get("clock_seconds", 600))))
            self.clocks = {"white": self.clock_limit, "black": self.clock_limit}
            self.clock_updated_at = time.monotonic()
            self.engine_level = get_level(settings.get("engine_level", 4)).id
            self.engine_manager.set_level(self.engine_level)
            self.last_engine_info = self._empty_engine_info()
            self.engine_error = None
            self.resigned_by = None
            self.position_version += 1
            return self.state()

    def play(self, value: str) -> dict:
        with self.lock:
            self._update_clock()
            self._ensure_playing()
            if self._turn_color() != self.player_color:
                raise ValueError("It is the engine's turn")
            move = self._resolve_move(value)
            self.board.make_move(move)
            self.position_version += 1
            return self.state()

    def start_engine(self) -> dict:
        with self.lock:
            self._update_clock()
            self._ensure_playing()
            if self._turn_color() == self.player_color:
                return self.state()
            if self.engine_future and not self.engine_future.done():
                return self.state()

            snapshot = self.board.clone()
            version = self.position_version
            job_id = uuid.uuid4().hex
            self.engine_job_id = job_id
            self.engine_error = None
            self.engine_future = self.executor.submit(self._search, snapshot, version, job_id)
            self.engine_future.add_done_callback(self._finish_engine)
            return self.state()

    def engine_move(self) -> dict:
        """Compatibility endpoint: start an asynchronous engine move."""

        return self.start_engine()

    def stop_engine(self) -> dict:
        with self.lock:
            if self.engine_future and not self.engine_future.done():
                self.engine_manager.stop()
                self.engine_future.cancel()
            self.engine_future = None
            self.engine_job_id = None
            return self.state()

    def undo(self) -> dict:
        with self.lock:
            self._update_clock()
            self.stop_engine()
            if not self.board.history:
                return self.state()
            self.board.unmake_move()
            if self.board.history and self._turn_color() != self.player_color:
                self.board.unmake_move()
            self.position_version += 1
            self.last_engine_info = self._empty_engine_info()
            return self.state()

    def resign(self) -> dict:
        with self.lock:
            self._update_clock()
            if self._status() == "playing":
                self.stop_engine()
                self.resigned_by = self.player_color
                self.position_version += 1
            return self.state()

    def pgn(self) -> str:
        with self.lock:
            return export_pgn(
                self.board,
                {
                    "White": "Player" if self.player_color == "white" else "Neon Core",
                    "Black": "Player" if self.player_color == "black" else "Neon Core",
                    "Engine": get_level(self.engine_level).name,
                },
            )

    def load_pgn(self, text: str) -> dict:
        with self.lock:
            self.stop_engine()
            self.board = import_pgn(text)
            self.game_id = uuid.uuid4().hex
            self.resigned_by = None
            self.engine_error = None
            self.last_engine_info = self._empty_engine_info()
            self.clock_limit = 600.0
            self.clocks = {"white": self.clock_limit, "black": self.clock_limit}
            self.clock_updated_at = time.monotonic()
            self.position_version += 1
            return self.state()

    def load_fen(self, fen: str) -> dict:
        with self.lock:
            self.stop_engine()
            self.board = Board(fen)
            self.game_id = uuid.uuid4().hex
            self.resigned_by = None
            self.engine_error = None
            self.last_engine_info = self._empty_engine_info()
            self.clock_limit = 600.0
            self.clocks = {"white": self.clock_limit, "black": self.clock_limit}
            self.clock_updated_at = time.monotonic()
            self.position_version += 1
            return self.state()

    def _search(self, board: Board, version: int, job_id: str) -> tuple:
        move, info = self.engine_manager.choose_move(board, self.engine_time)
        return move, info, version, job_id

    def _finish_engine(self, future: Future) -> None:
        try:
            move, info, version, job_id = future.result()
        except Exception as error:  # Keep failures visible in the API and UI.
            with self.lock:
                if future.cancelled() or self.engine_future is not future:
                    return
                self.engine_error = str(error)
                self.engine_future = None
                self.engine_job_id = None
            return

        with self.lock:
            self._update_clock()
            if job_id != self.engine_job_id or version != self.position_version:
                return
            if move and self._status() == "playing" and self._turn_color() != self.player_color:
                self.board.make_move(move)
                self.position_version += 1
            self.last_engine_info = info
            self.engine_future = None
            self.engine_job_id = None

    def _resolve_move(self, value: str) -> Move:
        requested = Move.from_uci(value)
        for move in self.board.legal_moves():
            if (
                move.from_square == requested.from_square
                and move.to_square == requested.to_square
                and move.promotion == requested.promotion
            ):
                return move
        raise ValueError(f"Illegal move: {value}")

    def _ensure_playing(self) -> None:
        if self._status() != "playing":
            raise ValueError("The game is over")

    def _turn_color(self) -> str:
        return "white" if self.board.white_to_move else "black"

    def _status(self) -> str:
        if self.resigned_by:
            return f"resigned_{self.resigned_by}"
        if self.clocks["white"] <= 0:
            return "time_white"
        if self.clocks["black"] <= 0:
            return "time_black"
        return self.board.game_status()

    def _update_clock(self) -> None:
        now = time.monotonic()
        if self.clock_updated_at <= 0 or self.resigned_by:
            self.clock_updated_at = now
            return
        if self.board.game_status() != "playing":
            self.clock_updated_at = now
            return
        side = self._turn_color()
        self.clocks[side] = max(0.0, self.clocks[side] - (now - self.clock_updated_at))
        self.clock_updated_at = now

    def state(self) -> dict:
        with self.lock:
            self._update_clock()
            legal = self.board.legal_moves()
            white_material, black_material = self.board.material()
            level = get_level(self.engine_level)
            # Keep the UI in the thinking state until the completion callback
            # has applied the move to the authoritative board. A Future can
            # finish between submission and this snapshot.
            thinking = self.engine_future is not None
            info = dict(self.last_engine_info)
            info["status"] = "thinking" if thinking else "error" if self.engine_error else "ready"
            if self.engine_error:
                info["error"] = self.engine_error
            return {
                "fen": self.board.to_fen(),
                "board": self.board.squares,
                "turn": self._turn_color(),
                "status": self._status(),
                "in_check": self.board.in_check(),
                "legal_moves": [move.uci for move in legal],
                "history": [move.uci for move in self.board.history],
                "san_history": san_history(self.board),
                "last_move": self.board.history[-1].uci if self.board.history else None,
                "player_color": self.player_color,
                "engine_level": level.id,
                "engine_level_name": level.name,
                "engine_available": level.backend == "custom" or self.engine_manager.stockfish_available,
                "stockfish_available": self.engine_manager.stockfish_available,
                "engine_info": info,
                "engine_levels": public_levels(self.engine_manager.stockfish_available),
                "material": {"white": white_material, "black": black_material},
                "clocks": {side: round(seconds, 1) for side, seconds in self.clocks.items()},
                "clock_limit": self.clock_limit,
                "revision": self.position_version,
                "game_id": self.game_id,
                "actual_backend": info.get("backend"),
                "warning": info.get("fallback_reason", "") if info.get("fallback") else "",
            }


SERVICE = GameService()


class ChessHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:
        if self.path.startswith("/api/"):
            super().log_message(format, *args)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ("/api/state", "/api/engine/status"):
            self._json(SERVICE.state())
            return
        if parsed.path == "/api/levels":
            self._json({"levels": public_levels(SERVICE.engine_manager.stockfish_available)})
            return
        if parsed.path == "/api/pgn":
            encoded = SERVICE.pgn().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/x-chess-pgn; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Content-Disposition", "attachment; filename=neon-chess-game.pgn")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)
            return
        self._asset(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self._payload()
            if parsed.path == "/api/new":
                result = SERVICE.reset(payload)
            elif parsed.path == "/api/move":
                result = SERVICE.play(str(payload.get("move", "")))
            elif parsed.path in ("/api/engine", "/api/engine/start"):
                result = SERVICE.start_engine()
            elif parsed.path == "/api/engine/stop":
                result = SERVICE.stop_engine()
            elif parsed.path == "/api/undo":
                result = SERVICE.undo()
            elif parsed.path == "/api/resign":
                result = SERVICE.resign()
            elif parsed.path == "/api/pgn":
                result = SERVICE.load_pgn(str(payload.get("pgn", "")))
            elif parsed.path == "/api/fen":
                result = SERVICE.load_fen(str(payload.get("fen", "")))
            else:
                self._json({"error": "Not found"}, 404)
                return
            self._json(result)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self._json({"error": str(error)}, 400)
        except Exception as error:  # Keep local development responses readable.
            self._json({"error": f"Server error: {error}"}, 500)

    def _payload(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def _json(self, payload: dict, status: int = 200) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _asset(self, path: str) -> None:
        if path == "/favicon.ico":
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        clean = "/index.html" if path in ("", "/") else path
        candidate = (WEB / clean.lstrip("/")).resolve()
        if WEB not in candidate.parents and candidate != WEB:
            self._json({"error": "Forbidden"}, 403)
            return
        if not candidate.is_file():
            self._json({"error": "Not found"}, 404)
            return
        content = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)
