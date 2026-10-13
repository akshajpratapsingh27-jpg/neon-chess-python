"""A compact, upgradeable alpha-beta chess search."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .core import Board, Move, PIECE_VALUES

MATE_SCORE = 100_000
INF = 1_000_000

# Tables are indexed from White's first rank toward the eighth rank.  Black
# positions are mirrored with ``square ^ 56`` in evaluate().
PIECE_SQUARES = {
    "p": [
        0, 0, 0, 0, 0, 0, 0, 0,
        50, 50, 50, 50, 50, 50, 50, 50,
        10, 10, 20, 30, 30, 20, 10, 10,
        5, 5, 10, 25, 25, 10, 5, 5,
        0, 0, 0, 20, 20, 0, 0, 0,
        5, -5, -10, 0, 0, -10, -5, 5,
        5, 10, 10, -20, -20, 10, 10, 5,
        0, 0, 0, 0, 0, 0, 0, 0,
    ],
    "n": [
        -50, -40, -30, -30, -30, -30, -40, -50,
        -40, -20, 0, 5, 5, 0, -20, -40,
        -30, 5, 10, 15, 15, 10, 5, -30,
        -30, 0, 15, 20, 20, 15, 0, -30,
        -30, 5, 15, 20, 20, 15, 5, -30,
        -30, 0, 10, 15, 15, 10, 0, -30,
        -40, -20, 0, 0, 0, 0, -20, -40,
        -50, -40, -30, -30, -30, -30, -40, -50,
    ],
    "b": [
        -20, -10, -10, -10, -10, -10, -10, -20,
        -10, 5, 0, 0, 0, 0, 5, -10,
        -10, 10, 10, 10, 10, 10, 10, -10,
        -10, 0, 10, 10, 10, 10, 0, -10,
        -10, 5, 5, 10, 10, 5, 5, -10,
        -10, 0, 5, 10, 10, 5, 0, -10,
        -10, 0, 0, 0, 0, 0, 0, -10,
        -20, -10, -10, -10, -10, -10, -10, -20,
    ],
    "r": [
        0, 0, 0, 5, 5, 0, 0, 0,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        5, 10, 10, 10, 10, 10, 10, 5,
        0, 0, 0, 5, 5, 0, 0, 0,
    ],
    "q": [
        -20, -10, -10, 0, 0, -10, -10, -20,
        -10, 0, 5, 0, 0, 0, 0, -10,
        -10, 5, 5, 5, 5, 5, 5, 0,
        0, 0, 5, 5, 5, 5, 5, -5,
        0, 0, 5, 5, 5, 5, 5, -5,
        -10, 0, 5, 5, 5, 5, 5, 0,
        -10, 0, 5, 0, 0, 0, 0, -10,
        -20, -10, -10, 0, 0, -10, -10, -20,
    ],
    "k": [
        -50, -40, -30, -20, -20, -30, -40, -50,
        -30, -20, -10, 0, 0, -10, -20, -30,
        -30, -10, 20, 30, 30, 20, -10, -30,
        -30, -10, 30, 40, 40, 30, -10, -30,
        -30, -10, 30, 40, 40, 30, -10, -30,
        -30, -10, 20, 30, 30, 20, -10, -30,
        -30, -30, 0, 0, 0, 0, -30, -30,
        -50, -30, -30, -30, -30, -30, -30, -50,
    ],
}


@dataclass(slots=True)
class TTEntry:
    depth: int
    score: int
    flag: str
    move: Move | None


class SearchTimeout(Exception):
    pass


class Engine:
    """Iterative alpha-beta search with a deterministic public API."""

    def __init__(self, max_depth: int = 4):
        self.max_depth = max_depth
        self.table: dict[str, TTEntry] = {}
        self.nodes = 0
        self.start_time = 0.0
        self.time_limit = 0.0
        self.stop_requested = False
        self.root_depth = 0
        self.completed_depth = 0
        self.last_score = 0
        self.last_pv: list[Move] = []

    def choose_move(
        self, board: Board, time_limit: float = 0.8, max_depth: int | None = None
    ) -> tuple[Move | None, dict]:
        self.nodes = 0
        self.start_time = time.monotonic()
        self.time_limit = max(0.02, time_limit)
        self.stop_requested = False
        self.root_depth = 0
        self.completed_depth = 0
        self.last_score = 0
        self.last_pv = []

        legal = board.legal_moves()
        if not legal or self._is_draw(board):
            return None, self.info()

        best = legal[0]
        self.last_pv = [best]
        limit = self.max_depth if max_depth is None else max_depth
        for depth in range(1, limit + 1):
            try:
                score, move, pv = self._root(board, depth)
            except SearchTimeout:
                break
            if move is not None:
                best = move
                self.last_score = score
                self.last_pv = pv
            # Only publish a depth after its complete root iteration returned.
            self.completed_depth = depth
            self.root_depth = depth
        return best, self.info()

    def _root(self, board: Board, depth: int) -> tuple[int, Move | None, list[Move]]:
        alpha, beta = -INF, INF
        best_score = -INF
        best_move = None
        best_pv: list[Move] = []
        moves = self._ordered_moves(board, board.legal_moves(), None)
        for move in moves:
            self._check_time()
            undo = board.make_move(move)
            try:
                score = -self._search(board, depth - 1, -beta, -alpha, 1)
            finally:
                board.unmake_move(undo)
            if score > best_score:
                best_score = score
                best_move = move
                best_pv = [move]
            if score > alpha:
                alpha = score
        return best_score, best_move, best_pv

    def _search(self, board: Board, depth: int, alpha: int, beta: int, ply: int) -> int:
        self._check_time()
        self.nodes += 1
        if depth <= 0:
            return self._quiescence(board, alpha, beta, ply)
        if self._is_draw(board):
            return 0

        key = self._tt_key(board)
        original_alpha, original_beta = alpha, beta
        cached = self.table.get(key)
        if cached and cached.depth >= depth:
            if cached.flag == "exact":
                return cached.score
            if cached.flag == "lower":
                alpha = max(alpha, cached.score)
            elif cached.flag == "upper":
                beta = min(beta, cached.score)
            if alpha >= beta:
                return cached.score

        moves = self._ordered_moves(board, board.legal_moves(), cached.move if cached else None)
        if not moves:
            return -MATE_SCORE + ply if board.in_check() else 0

        best_score = -INF
        best_move = None
        for move in moves:
            undo = board.make_move(move)
            try:
                score = -self._search(board, depth - 1, -beta, -alpha, ply + 1)
            finally:
                board.unmake_move(undo)
            if score > best_score:
                best_score, best_move = score, move
            alpha = max(alpha, score)
            if alpha >= beta:
                break

        if best_score <= original_alpha:
            flag = "upper"
        elif best_score >= original_beta:
            flag = "lower"
        else:
            flag = "exact"
        self.table[key] = TTEntry(depth, best_score, flag, best_move)
        return best_score

    def _quiescence(self, board: Board, alpha: int, beta: int, ply: int) -> int:
        self._check_time()
        self.nodes += 1
        legal = board.legal_moves()
        if not legal:
            return -MATE_SCORE + ply if board.in_check() else 0
        if self._is_draw(board):
            return 0

        if board.in_check():
            moves = legal
        else:
            stand_pat = self.evaluate(board)
            if stand_pat >= beta:
                return beta
            alpha = max(alpha, stand_pat)
            moves = [
                move
                for move in legal
                if board.squares[move.to_square] is not None or move.is_en_passant or move.promotion
            ]
        for move in self._ordered_moves(board, moves, None):
            undo = board.make_move(move)
            try:
                score = -self._quiescence(board, -beta, -alpha, ply + 1)
            finally:
                board.unmake_move(undo)
            if score >= beta:
                return beta
            alpha = max(alpha, score)
        return alpha

    def evaluate(self, board: Board) -> int:
        score = 0
        bishops = {True: 0, False: 0}
        for square, piece in enumerate(board.squares):
            if not piece:
                continue
            white = piece.isupper()
            value = PIECE_VALUES[piece.lower()] + PIECE_SQUARES[piece.lower()][square if white else square ^ 56]
            score += value if white else -value
            if piece.lower() == "b":
                bishops[white] += 1
        if bishops[True] >= 2:
            score += 30
        if bishops[False] >= 2:
            score -= 30
        mobility = len(board.legal_moves())
        score += mobility * 2 if board.white_to_move else -mobility * 2
        return score if board.white_to_move else -score

    def _ordered_moves(self, board: Board, moves: list[Move], preferred: Move | None) -> list[Move]:
        def score(move: Move) -> int:
            attacker = board.squares[move.from_square]
            captured = board.squares[move.to_square]
            if move.is_en_passant:
                captured = "p" if board.white_to_move else "P"
            capture_score = 0
            if captured:
                capture_score = 10 * PIECE_VALUES[captured.lower()] - PIECE_VALUES[attacker.lower()]
            return (
                (1_000_000 if preferred and move == preferred else 0)
                + capture_score
                + (100_000 + PIECE_VALUES[move.promotion] if move.promotion else 0)
                + (50 if move.is_castle else 0)
            )

        return sorted(moves, key=score, reverse=True)

    def _is_draw(self, board: Board) -> bool:
        return (
            board.halfmove >= 100
            or board.position_history.count(board.repetition_key()) >= 3
            or board.is_insufficient_material()
        )

    def _tt_key(self, board: Board) -> str:
        """Include all path-sensitive state that can change a draw result."""

        return repr((board.hash_key(), board.halfmove, tuple(board.position_history)))

    def _check_time(self) -> None:
        if self.stop_requested or time.monotonic() - self.start_time >= self.time_limit:
            raise SearchTimeout

    def info(self) -> dict:
        elapsed = max(0.001, time.monotonic() - self.start_time) if self.start_time else 0.001
        return {
            "depth": self.completed_depth,
            "completed_depth": self.completed_depth,
            "nodes": self.nodes,
            "nps": int(self.nodes / elapsed),
            "score": self.last_score,
            "pv": [move.uci for move in self.last_pv],
        }
