"""SAN notation helpers built on the authoritative Board move generator."""

from __future__ import annotations

import re

from .core import Board, Move, square_name


def move_to_san(board: Board, move: Move) -> str:
    """Render a legal move as Standard Algebraic Notation."""

    piece = board.squares[move.from_square]
    if not piece:
        raise ValueError("Cannot format a move from an empty square")
    capture = move.is_en_passant or board.squares[move.to_square] is not None

    if move.is_castle:
        san = "O-O" if move.to_square > move.from_square else "O-O-O"
    else:
        kind = piece.lower()
        prefix = "" if kind == "p" else kind.upper()
        if kind != "p":
            alternatives = [
                candidate
                for candidate in board.legal_moves()
                if candidate.to_square == move.to_square
                and candidate.from_square != move.from_square
                and board.squares[candidate.from_square]
                and board.squares[candidate.from_square].lower() == kind
            ]
            if alternatives:
                same_file = any(candidate.from_square % 8 == move.from_square % 8 for candidate in alternatives)
                same_rank = any(candidate.from_square // 8 == move.from_square // 8 for candidate in alternatives)
                if not same_file:
                    prefix += square_name(move.from_square)[0]
                elif not same_rank:
                    prefix += square_name(move.from_square)[1]
                else:
                    prefix += square_name(move.from_square)
        elif capture:
            prefix = square_name(move.from_square)[0]
        san = prefix + ("x" if capture else "") + square_name(move.to_square)
        if move.promotion:
            san += "=" + move.promotion.upper()

    undo = board.make_move(move)
    try:
        if board.in_check():
            san += "#" if not board.legal_moves() else "+"
    finally:
        board.unmake_move(undo)
    return san


def san_history(board: Board) -> list[str]:
    """Replay the current UCI history and return SAN moves."""

    replay = Board(board.initial_fen)
    result: list[str] = []
    for recorded in board.history:
        legal = next((move for move in replay.legal_moves() if move.uci == recorded.uci), None)
        if legal is None:
            raise ValueError(f"History contains an illegal move: {recorded.uci}")
        result.append(move_to_san(replay, legal))
        replay.make_move(legal)
    return result


def normalize_san(value: str) -> str:
    """Normalize harmless SAN variations before comparing candidate moves."""

    # Numeric castling is commonly emitted by otherwise valid PGN files, and
    # annotation glyphs do not change the move.  Check indicators do change
    # the move's correctness, however: stripping them would accept ``e4+``
    # for a move that does not give check (and would accept a false mate).
    normalized = value.strip().replace("0-0-0", "O-O-O").replace("0-0", "O-O")
    return re.sub(r"[!?]+$", "", normalized)


def resolve_san(board: Board, value: str) -> Move:
    """Resolve SAN against legal generated moves, rejecting ambiguity."""

    target = normalize_san(value)
    matches = [move for move in board.legal_moves() if normalize_san(move_to_san(board, move)) == target]
    if len(matches) != 1:
        raise ValueError(f"Illegal or ambiguous SAN move: {value}")
    return matches[0]
