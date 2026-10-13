"""Legal chess rules and position state for Neon Chess.

The first version deliberately favours transparent, testable Python over
micro-optimised bitboards. The public Board/Move API is stable so the search
layer can be upgraded without changing the web application.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

FILES = "abcdefgh"
RANKS = "12345678"
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
PROMOTIONS = "qrbn"
PIECE_VALUES = {"p": 100, "n": 320, "b": 330, "r": 500, "q": 900, "k": 0}

KNIGHT_STEPS = (-17, -15, -10, -6, 6, 10, 15, 17)
KING_STEPS = (-9, -8, -7, -1, 1, 7, 8, 9)
BISHOP_DIRECTIONS = (-9, -7, 7, 9)
ROOK_DIRECTIONS = (-8, -1, 1, 8)
QUEEN_DIRECTIONS = BISHOP_DIRECTIONS + ROOK_DIRECTIONS


def square_name(square: int) -> str:
    return FILES[square % 8] + RANKS[square // 8]


def parse_square(value: str) -> int:
    if len(value) != 2 or value[0] not in FILES or value[1] not in RANKS:
        raise ValueError(f"Invalid square: {value}")
    return FILES.index(value[0]) + 8 * RANKS.index(value[1])


def is_white(piece: str | None) -> bool:
    return bool(piece) and piece.isupper()


def is_black(piece: str | None) -> bool:
    return bool(piece) and piece.islower()


def same_side(piece: str | None, white: bool) -> bool:
    return bool(piece) and piece.isupper() == white


def on_board(square: int) -> bool:
    return 0 <= square < 64


def same_file_or_rank(previous: int, current: int, delta: int) -> bool:
    if delta in (-8, 8):
        return previous % 8 == current % 8
    if delta in (-1, 1):
        return previous // 8 == current // 8
    return abs(previous % 8 - current % 8) == 1 and abs(previous // 8 - current // 8) == 1


@dataclass(frozen=True, slots=True)
class Move:
    """A chess move represented with 0..63 squares."""

    from_square: int
    to_square: int
    promotion: str = ""
    is_castle: bool = False
    is_en_passant: bool = False

    @property
    def uci(self) -> str:
        return square_name(self.from_square) + square_name(self.to_square) + self.promotion.lower()

    @classmethod
    def from_uci(cls, value: str) -> "Move":
        if len(value) not in (4, 5):
            raise ValueError(f"Invalid UCI move: {value}")
        promotion = value[4].lower() if len(value) == 5 else ""
        if promotion and promotion not in PROMOTIONS:
            raise ValueError(f"Invalid promotion: {value}")
        return cls(parse_square(value[:2]), parse_square(value[2:4]), promotion)


@dataclass(slots=True)
class Undo:
    move: Move
    captured: str | None
    castling: str
    en_passant: int | None
    halfmove: int
    fullmove: int
    previous_hash: str


class Board:
    """A legal chess position with reversible make/unmake operations."""

    def __init__(self, fen: str = START_FEN):
        self.initial_fen = fen
        self.squares: list[str | None] = [None] * 64
        self.white_to_move = True
        self.castling = "KQkq"
        self.en_passant: int | None = None
        self.halfmove = 0
        self.fullmove = 1
        self.history: list[Move] = []
        self.position_history: list[str] = []
        self._undo_stack: list[Undo] = []
        self.pgn_setup = False
        self.pgn_result: str | None = None
        self.set_fen(fen)

    def clone(self) -> "Board":
        copy = Board(self.to_fen())
        copy.initial_fen = self.initial_fen
        copy.history = self.history.copy()
        copy.position_history = self.position_history.copy()
        copy._undo_stack = self._undo_stack.copy()
        copy.pgn_setup = self.pgn_setup
        copy.pgn_result = self.pgn_result
        return copy

    def set_fen(self, fen: str) -> None:
        self.initial_fen = fen
        self.pgn_setup = False
        self.pgn_result = None
        fields = fen.split()
        if len(fields) != 6:
            raise ValueError("FEN must have six fields")
        rows = fields[0].split("/")
        if len(rows) != 8:
            raise ValueError("FEN must have eight ranks")
        self.squares = [None] * 64
        for fen_rank, row in enumerate(rows):
            file_index = 0
            for character in row:
                if character in "12345678":
                    file_index += int(character)
                elif character in "PNBRQKpnbrqk" and file_index < 8:
                    self.squares[(7 - fen_rank) * 8 + file_index] = character
                    file_index += 1
                else:
                    raise ValueError(f"Invalid FEN rank: {row}")
            if file_index != 8:
                raise ValueError(f"Invalid FEN rank: {row}")
        if fields[1] not in ("w", "b"):
            raise ValueError("Invalid side to move")
        self.white_to_move = fields[1] == "w"
        if fields[2] == "-":
            self.castling = ""
        elif (
            not fields[2]
            or any(right not in "KQkq" for right in fields[2])
            or len(set(fields[2])) != len(fields[2])
            or fields[2] != "".join(right for right in "KQkq" if right in fields[2])
        ):
            raise ValueError("Invalid castling rights")
        else:
            self.castling = fields[2]
        self.en_passant = None if fields[3] == "-" else parse_square(fields[3])
        if not fields[4].isascii() or not fields[4].isdigit():
            raise ValueError("Invalid halfmove clock")
        if not fields[5].isascii() or not fields[5].isdigit() or int(fields[5]) < 1:
            raise ValueError("Invalid fullmove number")
        self.halfmove = int(fields[4])
        self.fullmove = int(fields[5])
        self._validate_fen_position()
        self.history = []
        self.position_history = [self.repetition_key()]
        self._undo_stack = []

    def _validate_fen_position(self) -> None:
        """Validate the structural constraints that make a FEN usable."""

        white_kings = [square for square, piece in enumerate(self.squares) if piece == "K"]
        black_kings = [square for square, piece in enumerate(self.squares) if piece == "k"]
        if len(white_kings) != 1 or len(black_kings) != 1:
            raise ValueError("FEN must contain exactly one king per side")
        white_king, black_king = white_kings[0], black_kings[0]
        if abs(white_king % 8 - black_king % 8) <= 1 and abs(white_king // 8 - black_king // 8) <= 1:
            raise ValueError("Kings may not be adjacent")

        for square in (*range(8), *range(56, 64)):
            if self.squares[square] and self.squares[square].lower() == "p":
                raise ValueError("Pawns may not be on the first or eighth rank")

        castling_squares = {
            "K": (4, 7, "K", "R"),
            "Q": (4, 0, "K", "R"),
            "k": (60, 63, "k", "r"),
            "q": (60, 56, "k", "r"),
        }
        for right, (king_square, rook_square, king, rook) in castling_squares.items():
            if right in self.castling and (
                self.squares[king_square] != king or self.squares[rook_square] != rook
            ):
                raise ValueError("Castling rights do not match the board")

        if self.en_passant is None:
            return
        target = self.en_passant
        if self.squares[target] is not None:
            raise ValueError("En passant target must be empty")
        if self.white_to_move:
            if target // 8 != 5 or self.squares[target - 8] != "p" or self.squares[target + 8] is not None:
                raise ValueError("Invalid en passant target")
        elif target // 8 != 2 or self.squares[target + 8] != "P" or self.squares[target - 8] is not None:
            raise ValueError("Invalid en passant target")

    def to_fen(self) -> str:
        rows = []
        for rank in range(7, -1, -1):
            row = ""
            empty = 0
            for file_index in range(8):
                piece = self.squares[rank * 8 + file_index]
                if piece is None:
                    empty += 1
                else:
                    if empty:
                        row += str(empty)
                        empty = 0
                    row += piece
            if empty:
                row += str(empty)
            rows.append(row)
        return " ".join(
            (
                "/".join(rows),
                "w" if self.white_to_move else "b",
                self.castling or "-",
                square_name(self.en_passant) if self.en_passant is not None else "-",
                str(self.halfmove),
                str(self.fullmove),
            )
        )

    def repetition_key(self) -> str:
        fen = self.to_fen().split()
        if self.en_passant is not None and not self._has_legal_en_passant():
            fen[3] = "-"
        return " ".join(fen[:4])

    def hash_key(self) -> str:
        return self.repetition_key()

    def _has_legal_en_passant(self) -> bool:
        """Return whether the current en passant target has a legal capture.

        This deliberately edits only the three affected squares temporarily,
        avoiding legal_moves()/make_move() recursion while computing hashes.
        """

        target = self.en_passant
        if target is None or self.squares[target] is not None:
            return False
        white = self.white_to_move
        direction = 8 if white else -8
        target_file = target % 8
        captured_square = target - 8 if white else target + 8
        captured_piece = "p" if white else "P"
        if self.squares[captured_square] != captured_piece:
            return False
        for file_delta in (-1, 1):
            from_square = target - direction - file_delta
            if not on_board(from_square) or abs(from_square % 8 - target_file) != 1:
                continue
            if self.squares[from_square] != ("P" if white else "p"):
                continue
            moving_piece = self.squares[from_square]
            self.squares[from_square] = None
            self.squares[target] = moving_piece
            self.squares[captured_square] = None
            try:
                legal = not self.in_check(white)
            finally:
                self.squares[from_square] = moving_piece
                self.squares[target] = None
                self.squares[captured_square] = captured_piece
            if legal:
                return True
        return False

    def piece_at(self, square: int | str) -> str | None:
        if isinstance(square, str):
            square = parse_square(square)
        return self.squares[square]

    def king_square(self, white: bool) -> int:
        target = "K" if white else "k"
        try:
            return self.squares.index(target)
        except ValueError:
            return -1

    def is_attacked(self, square: int, by_white: bool) -> bool:
        # Pawn attacks point in the opposite direction from pawn movement.
        rank, file_index = divmod(square, 8)
        pawn = "P" if by_white else "p"
        pawn_rank = rank - 1 if by_white else rank + 1
        if 0 <= pawn_rank < 8:
            for pawn_file in (file_index - 1, file_index + 1):
                if 0 <= pawn_file < 8 and self.squares[pawn_rank * 8 + pawn_file] == pawn:
                    return True

        knight = "N" if by_white else "n"
        for delta in KNIGHT_STEPS:
            candidate = square + delta
            if on_board(candidate) and abs(candidate % 8 - file_index) <= 2 and self.squares[candidate] == knight:
                if abs(candidate // 8 - rank) + abs(candidate % 8 - file_index) in (3, 4):
                    return True

        king = "K" if by_white else "k"
        for delta in KING_STEPS:
            candidate = square + delta
            if on_board(candidate) and abs(candidate % 8 - file_index) <= 1 and self.squares[candidate] == king:
                return True

        for directions, targets in (
            (BISHOP_DIRECTIONS, "BQ" if by_white else "bq"),
            (ROOK_DIRECTIONS, "RQ" if by_white else "rq"),
        ):
            for delta in directions:
                candidate = square
                while True:
                    next_square = candidate + delta
                    if not on_board(next_square) or not same_file_or_rank(candidate, next_square, delta):
                        break
                    candidate = next_square
                    piece = self.squares[candidate]
                    if piece is None:
                        continue
                    if piece in targets:
                        return True
                    break
        return False

    def in_check(self, white: bool | None = None) -> bool:
        if white is None:
            white = self.white_to_move
        king = self.king_square(white)
        return king >= 0 and self.is_attacked(king, not white)

    def _pseudo_moves(self) -> Iterable[Move]:
        white = self.white_to_move
        for from_square, piece in enumerate(self.squares):
            if not same_side(piece, white):
                continue
            kind = piece.lower()
            rank, file_index = divmod(from_square, 8)
            if kind == "p":
                direction = 8 if white else -8
                start_rank = 1 if white else 6
                promotion_rank = 7 if white else 0
                one = from_square + direction
                if on_board(one) and self.squares[one] is None:
                    if one // 8 == promotion_rank:
                        for promotion in PROMOTIONS:
                            yield Move(from_square, one, promotion)
                    else:
                        yield Move(from_square, one)
                    two = from_square + 2 * direction
                    if rank == start_rank and self.squares[two] is None:
                        yield Move(from_square, two)
                for file_delta in (-1, 1):
                    if not 0 <= file_index + file_delta < 8:
                        continue
                    target = from_square + direction + file_delta
                    if not on_board(target):
                        continue
                    target_piece = self.squares[target]
                    if (
                        target_piece is not None
                        and target_piece.isupper() != white
                        and target_piece.lower() != "k"
                    ) or target == self.en_passant:
                        if target // 8 == promotion_rank:
                            for promotion in PROMOTIONS:
                                yield Move(from_square, target, promotion, is_en_passant=target == self.en_passant)
                        else:
                            yield Move(from_square, target, is_en_passant=target == self.en_passant)
            elif kind == "n":
                for delta in KNIGHT_STEPS:
                    target = from_square + delta
                    if on_board(target) and abs(target % 8 - file_index) <= 2 and abs(target // 8 - rank) <= 2:
                        if not same_side(self.squares[target], white) and self.squares[target] != ("k" if white else "K"):
                            yield Move(from_square, target)
            elif kind in "brq":
                directions = BISHOP_DIRECTIONS if kind == "b" else ROOK_DIRECTIONS if kind == "r" else QUEEN_DIRECTIONS
                for delta in directions:
                    target = from_square
                    while True:
                        next_square = target + delta
                        if not on_board(next_square) or not same_file_or_rank(target, next_square, delta):
                            break
                        target = next_square
                        if self.squares[target] is None:
                            yield Move(from_square, target)
                        else:
                            if not same_side(self.squares[target], white) and self.squares[target].lower() != "k":
                                yield Move(from_square, target)
                            break
            elif kind == "k":
                for delta in KING_STEPS:
                    target = from_square + delta
                    if (
                        on_board(target)
                        and abs(target % 8 - file_index) <= 1
                        and not same_side(self.squares[target], white)
                        and self.squares[target] != ("k" if white else "K")
                    ):
                        yield Move(from_square, target)
                yield from self._castle_moves(from_square, white)

    def _castle_moves(self, from_square: int, white: bool) -> Iterable[Move]:
        if self.in_check(white):
            return
        rank = 0 if white else 7
        king_start = rank * 8 + 4
        if from_square != king_start:
            return
        if ("K" if white else "k") in self.castling:
            rook_square = rank * 8 + 7
            if self.squares[rook_square] == ("R" if white else "r") and all(self.squares[rank * 8 + file_index] is None for file_index in (5, 6)):
                if not self.is_attacked(rank * 8 + 5, not white) and not self.is_attacked(rank * 8 + 6, not white):
                    yield Move(king_start, rank * 8 + 6, is_castle=True)
        if ("Q" if white else "q") in self.castling:
            rook_square = rank * 8
            if self.squares[rook_square] == ("R" if white else "r") and all(self.squares[rank * 8 + file_index] is None for file_index in (1, 2, 3)):
                if not self.is_attacked(rank * 8 + 3, not white) and not self.is_attacked(rank * 8 + 2, not white):
                    yield Move(king_start, rank * 8 + 2, is_castle=True)

    def legal_moves(self) -> list[Move]:
        legal = []
        for move in self._pseudo_moves():
            undo = self.make_move(move)
            if not self.in_check(not self.white_to_move):
                legal.append(move)
            self.unmake_move(undo)
        return legal

    def legal_moves_from(self, from_square: int | str) -> list[Move]:
        if isinstance(from_square, str):
            from_square = parse_square(from_square)
        return [move for move in self.legal_moves() if move.from_square == from_square]

    def make_move(self, move: Move) -> Undo:
        piece = self.squares[move.from_square]
        if piece is None:
            raise ValueError("No piece on move origin")
        captured = self.squares[move.to_square]
        undo = Undo(move, captured, self.castling, self.en_passant, self.halfmove, self.fullmove, self.hash_key())
        self.squares[move.from_square] = None
        if move.is_en_passant:
            captured_square = move.to_square - 8 if piece.isupper() else move.to_square + 8
            captured = self.squares[captured_square]
            self.squares[captured_square] = None
        placed = piece
        if move.promotion:
            placed = move.promotion.upper() if piece.isupper() else move.promotion.lower()
        self.squares[move.to_square] = placed
        if move.is_castle:
            if move.to_square > move.from_square:
                rook_from, rook_to = move.from_square + 3, move.from_square + 1
            else:
                rook_from, rook_to = move.from_square - 4, move.from_square - 1
            self.squares[rook_to] = self.squares[rook_from]
            self.squares[rook_from] = None
        self._update_castling(move, piece, captured)
        self.en_passant = None
        if piece.lower() == "p" and abs(move.to_square - move.from_square) == 16:
            self.en_passant = (move.to_square + move.from_square) // 2
        self.halfmove = 0 if piece.lower() == "p" or captured else self.halfmove + 1
        if not self.white_to_move:
            self.fullmove += 1
        self.white_to_move = not self.white_to_move
        self.history.append(move)
        self._undo_stack.append(undo)
        self.position_history.append(self.repetition_key())
        return undo

    def _update_castling(self, move: Move, piece: str, captured: str | None) -> None:
        rights = set(self.castling)
        rights.discard({"K": "K", "k": "k"}.get(piece, ""))
        if piece == "K":
            rights.discard("K")
            rights.discard("Q")
        elif piece == "k":
            rights.discard("k")
            rights.discard("q")
        if move.from_square == 0 or move.to_square == 0 or captured == "R" and move.to_square == 0:
            rights.discard("Q")
        if move.from_square == 7 or move.to_square == 7 or captured == "R" and move.to_square == 7:
            rights.discard("K")
        if move.from_square == 56 or move.to_square == 56 or captured == "r" and move.to_square == 56:
            rights.discard("q")
        if move.from_square == 63 or move.to_square == 63 or captured == "r" and move.to_square == 63:
            rights.discard("k")
        self.castling = "".join(right for right in "KQkq" if right in rights)

    def unmake_move(self, undo: Undo | None = None) -> None:
        if undo is None:
            if not self._undo_stack:
                raise ValueError("No move to unmake")
            undo = self._undo_stack[-1]
        move = undo.move
        self.white_to_move = not self.white_to_move
        if not self.white_to_move:
            self.fullmove -= 1
        self.castling = undo.castling
        self.en_passant = undo.en_passant
        self.halfmove = undo.halfmove
        self.squares[move.from_square] = self.squares[move.to_square]
        self.squares[move.to_square] = undo.captured
        if move.promotion:
            self.squares[move.from_square] = "P" if self.white_to_move else "p"
        if move.is_en_passant:
            captured_square = move.to_square - 8 if self.white_to_move else move.to_square + 8
            self.squares[captured_square] = "p" if self.white_to_move else "P"
        if move.is_castle:
            if move.to_square > move.from_square:
                rook_from, rook_to = move.from_square + 3, move.from_square + 1
            else:
                rook_from, rook_to = move.from_square - 4, move.from_square - 1
            self.squares[rook_from] = self.squares[rook_to]
            self.squares[rook_to] = None
        if self.history:
            self.history.pop()
        if self.position_history:
            self.position_history.pop()
        if self._undo_stack:
            self._undo_stack.pop()

    def push_uci(self, value: str) -> Move:
        requested = Move.from_uci(value)
        for legal in self.legal_moves():
            if legal.from_square == requested.from_square and legal.to_square == requested.to_square and legal.promotion == requested.promotion:
                self.make_move(legal)
                return legal
        raise ValueError(f"Illegal move: {value}")

    def game_status(self) -> str:
        legal = self.legal_moves()
        if legal:
            if self.halfmove >= 100:
                return "draw_fifty_move"
            if self.position_history.count(self.repetition_key()) >= 3:
                return "draw_repetition"
            if self.is_insufficient_material():
                return "draw_insufficient_material"
            return "playing"
        if self.in_check():
            return "checkmate_black" if self.white_to_move else "checkmate_white"
        return "stalemate"

    def is_insufficient_material(self) -> bool:
        """Return only for conservative, immediately dead material cases."""

        minors = [
            (piece, square)
            for square, piece in enumerate(self.squares)
            if piece and piece.lower() in "bn"
        ]
        if any(piece and piece.lower() in "pqr" for piece in self.squares):
            return False
        if not minors or len(minors) == 1:
            return True
        if (
            len(minors) == 2
            and {piece.isupper() for piece, _ in minors} == {True, False}
            and all(piece.lower() == "b" for piece, _ in minors)
        ):
            return (minors[0][1] // 8 + minors[0][1] % 8) % 2 == (
                minors[1][1] // 8 + minors[1][1] % 8
            ) % 2
        return False

    def material(self) -> tuple[int, int]:
        white = sum(PIECE_VALUES[p.lower()] for p in self.squares if p and p.isupper())
        black = sum(PIECE_VALUES[p.lower()] for p in self.squares if p and p.islower())
        return white, black
