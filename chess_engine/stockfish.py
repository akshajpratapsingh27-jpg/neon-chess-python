"""Small dependency-free UCI adapter for a local Stockfish executable."""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .core import Board, Move


class StockfishUnavailable(RuntimeError):
    """Raised when the configured Stockfish executable cannot be started."""


def find_stockfish(path: str | None = None) -> str | None:
    """Find Stockfish using explicit configuration, project folders, or PATH."""

    candidates: list[Path] = []
    if path:
        explicit = Path(path)
        return str(explicit) if explicit.is_file() else None
    environment_path = os.environ.get("STOCKFISH_PATH")
    if environment_path:
        candidates.append(Path(environment_path))

    root = Path(__file__).resolve().parent.parent
    candidates.extend(
        (
            root / "stockfish.exe",
            root / "engine" / "stockfish.exe",
            root / "bin" / "stockfish.exe",
            root / "stockfish",
            root / "engine" / "stockfish",
            root / "bin" / "stockfish",
        )
    )
    located = shutil.which("stockfish") or shutil.which("stockfish.exe")
    if located:
        candidates.append(Path(located))

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        winget_root = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if winget_root.is_dir():
            candidates.extend(winget_root.glob("**/stockfish*.exe"))

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


class StockfishEngine:
    """Run one isolated UCI search and return a normalised engine info dict."""

    def __init__(self, path: str | None = None, threads: int = 1, hash_mb: int = 128):
        self.path = find_stockfish(path)
        self.threads = max(1, int(threads))
        self.hash_mb = max(16, int(hash_mb))
        self.process: subprocess.Popen[str] | None = None
        self.output: queue.Queue[str] = queue.Queue()
        self.reader: threading.Thread | None = None

    @property
    def available(self) -> bool:
        return self.path is not None

    def choose_move(
        self,
        board: Board,
        time_limit: float,
        target_elo: int | None = None,
        depth: int | None = None,
    ) -> tuple[Move | None, dict]:
        if not self.path:
            raise StockfishUnavailable("Stockfish was not found. Set STOCKFISH_PATH to stockfish.exe.")

        legal_by_uci = {move.uci: move for move in board.legal_moves()}
        if not legal_by_uci:
            return None, {"backend": "stockfish", "depth": 0, "nodes": 0, "nps": 0, "score": 0, "pv": []}

        started = time.monotonic()
        info = {"backend": "stockfish", "depth": 0, "nodes": 0, "nps": 0, "score": 0, "pv": []}
        best_uci: str | None = None
        try:
            self._start()
            self._send("setoption name Threads value %d" % self.threads)
            self._send("setoption name Hash value %d" % self.hash_mb)
            if target_elo is not None:
                self._send("setoption name UCI_LimitStrength value true")
                self._send("setoption name UCI_Elo value %d" % int(target_elo))
            else:
                self._send("setoption name UCI_LimitStrength value false")
            self._send("isready")
            self._wait_for("readyok", 5.0)
            self._send("ucinewgame")
            self._send("position fen %s" % board.to_fen())
            if depth:
                self._send("go depth %d" % int(depth))
            else:
                self._send("go movetime %d" % max(50, int(time_limit * 1000)))

            deadline = started + max(0.2, time_limit + 2.0)
            while time.monotonic() < deadline:
                try:
                    line = self.output.get(timeout=0.2)
                except queue.Empty:
                    continue
                if line.startswith("info "):
                    self._parse_info(line, info)
                elif line.startswith("bestmove "):
                    best_uci = line.split()[1]
                    break
            if best_uci is None:
                self._send("stop")
                best_uci = self._wait_for_bestmove(1.0)
        finally:
            self.close()

        move = legal_by_uci.get(best_uci or "")
        info["time"] = round(time.monotonic() - started, 3)
        info["fallback"] = move is None
        return move, info

    def _start(self) -> None:
        assert self.path
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            [self.path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )
        self.reader = threading.Thread(target=self._read_output, daemon=True)
        self.reader.start()
        self._send("uci")
        self._wait_for("uciok", 5.0)

    def _read_output(self) -> None:
        if not self.process or not self.process.stdout:
            return
        for line in self.process.stdout:
            self.output.put(line.strip())

    def _send(self, command: str) -> None:
        if not self.process or not self.process.stdin:
            raise StockfishUnavailable("Stockfish process is not running")
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()

    def _wait_for(self, expected: str, timeout: float) -> str | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self.output.get(timeout=0.1)
            except queue.Empty:
                continue
            if line == expected:
                return line
        raise StockfishUnavailable(f"Stockfish did not answer with {expected}")

    def _wait_for_bestmove(self, timeout: float) -> str | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self.output.get(timeout=0.1)
            except queue.Empty:
                continue
            if line.startswith("bestmove "):
                return line.split()[1]
        return None

    @staticmethod
    def _parse_info(line: str, info: dict) -> None:
        tokens = line.split()

        def value_after(token: str) -> str | None:
            try:
                return tokens[tokens.index(token) + 1]
            except (ValueError, IndexError):
                return None

        for token, key in (("depth", "depth"), ("nodes", "nodes"), ("nps", "nps")):
            value = value_after(token)
            if value and value.lstrip("-").isdigit():
                info[key] = int(value)

        score_index = tokens.index("score") + 2 if "score" in tokens else -1
        if 0 <= score_index < len(tokens):
            score_type = tokens[score_index - 1]
            raw_score = tokens[score_index]
            if raw_score.lstrip("-").isdigit():
                info["score"] = int(raw_score) * (1000 if score_type == "mate" else 1)

        if "pv" in tokens:
            info["pv"] = tokens[tokens.index("pv") + 1 :]

    def close(self) -> None:
        process = self.process
        self.process = None
        if not process:
            return
        try:
            if process.stdin:
                process.stdin.write("quit\n")
                process.stdin.flush()
            process.wait(timeout=1.0)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
            process.wait(timeout=1.0)
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream:
                    stream.close()
