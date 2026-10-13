"""Small, bounded PGN export/import layer for local games."""

from __future__ import annotations

import re
from typing import Iterable

from .core import START_FEN, Board
from .notation import resolve_san, san_history

RESULTS = {"1-0", "0-1", "1/2-1/2", "*"}
_MAX_PGN_CHARS = 1_000_000
_MAX_MAINLINE_PLIES = 10_000
_TAG_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
_MOVE_NUMBER = re.compile(r"\d+\.(?:\.\.)?\Z")


def _escape_tag_value(value: str) -> str:
    """Escape a PGN tag value without allowing a header-line injection."""

    if any(ord(character) < 0x20 and character not in "\t" for character in value):
        raise ValueError("PGN tag values cannot contain newline or control characters")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _parse_tag_line(line: str) -> tuple[str, str] | None:
    """Parse one complete PGN tag pair, including PGN string escapes."""

    position = 0
    length = len(line)
    while position < length and line[position].isspace():
        position += 1
    if position == length:
        return None
    if line[position] != "[":
        raise ValueError("Malformed PGN tag pair")
    position += 1

    name_start = position
    while position < length and (line[position].isalnum() or line[position] == "_"):
        position += 1
    name = line[name_start:position]
    if not _TAG_NAME.fullmatch(name):
        raise ValueError("Malformed PGN tag name")
    while position < length and line[position].isspace():
        position += 1
    if position >= length or line[position] != '"':
        raise ValueError("PGN tag value must be quoted")
    position += 1

    value: list[str] = []
    while position < length:
        character = line[position]
        position += 1
        if character == '"':
            break
        if character == "\\":
            if position >= length:
                raise ValueError("Unterminated PGN tag escape")
            value.append(line[position])
            position += 1
        else:
            value.append(character)
    else:
        raise ValueError("Unterminated PGN tag value")

    while position < length and line[position].isspace():
        position += 1
    if position >= length or line[position] != "]":
        raise ValueError("Malformed PGN tag pair")
    position += 1
    if line[position:].strip():
        raise ValueError("Unexpected text after PGN tag pair")
    return name, "".join(value)


def _split_headers(text: str) -> tuple[dict[str, str], str]:
    """Read the initial tag section and return tags plus remaining movetext."""

    tags: dict[str, str] = {}
    lines = text.splitlines(keepends=True)
    consumed = 0
    saw_movetext = False
    for line in lines:
        stripped = line.strip()
        if not stripped and not saw_movetext:
            consumed += len(line)
            continue
        if stripped.startswith("[") and not saw_movetext:
            parsed = _parse_tag_line(line.rstrip("\r\n"))
            if parsed is None:
                consumed += len(line)
                continue
            key, value = parsed
            if key in tags:
                raise ValueError(f"Duplicate PGN tag: {key}")
            tags[key] = value
            consumed += len(line)
            continue
        saw_movetext = True
        break
    return tags, text[consumed:]


def _raw_mainline_tokens(text: str) -> list[str]:
    """Remove comments and RAVs while validating their nesting.

    Parenthesized recursive annotation variations are intentionally ignored,
    but their delimiters and comments are still checked.  Replacing skipped
    content with whitespace keeps adjacent compact move numbers separable.
    """

    output: list[str] = []
    variation_depth = 0
    in_brace_comment = False
    in_line_comment = False
    index = 0
    while index < len(text):
        character = text[index]
        if in_line_comment:
            if character in "\r\n":
                in_line_comment = False
                output.append(character)
            else:
                output.append(" ")
            index += 1
            continue
        if in_brace_comment:
            if character == "{":
                raise ValueError("Nested PGN brace comment")
            if character == "}":
                in_brace_comment = False
            output.append(" ")
            index += 1
            continue
        if character == ";":
            in_line_comment = True
            output.append(" ")
        elif character == "{":
            in_brace_comment = True
            output.append(" ")
        elif character == "}":
            raise ValueError("Unmatched PGN comment terminator")
        elif character == "(":
            variation_depth += 1
            output.append(" ")
        elif character == ")":
            if variation_depth == 0:
                raise ValueError("Unmatched PGN variation terminator")
            variation_depth -= 1
            output.append(" ")
        elif character == "$":
            # NAGs are skipped, including compact forms such as ``e4$1``.
            output.append(" ")
            index += 1
            if index >= len(text) or not text[index].isdigit():
                raise ValueError("Malformed PGN numeric annotation glyph")
            while index < len(text) and text[index].isdigit():
                output.append(" ")
                index += 1
            continue
        elif variation_depth:
            output.append(" ")
        else:
            output.append(character)
        index += 1

    if in_brace_comment:
        raise ValueError("Unterminated PGN comment")
    if variation_depth:
        raise ValueError("Unterminated PGN variation")
    return "".join(output).split()


def _expand_tokens(raw_tokens: Iterable[str]) -> list[str]:
    """Split compact move numbers and reject malformed move-number syntax."""

    expanded: list[str] = []
    for token in raw_tokens:
        if token in RESULTS:
            expanded.append(token)
            continue
        if _MOVE_NUMBER.fullmatch(token):
            expanded.append(token)
            continue
        compact = re.match(r"^(\d+)(\.{1,3})(.+)$", token)
        if compact:
            dots = compact.group(2)
            if len(dots) not in (1, 3):
                raise ValueError(f"Malformed PGN move number: {token}")
            expanded.extend((compact.group(1) + dots, compact.group(3)))
            continue
        if re.match(r"^\d+\.", token):
            raise ValueError(f"Malformed PGN move number: {token}")
        expanded.append(token)
    return expanded


def _movetext_tokens(text: str) -> list[str]:
    return _expand_tokens(_raw_mainline_tokens(text))


def export_pgn(
    board: Board,
    headers: dict[str, str] | None = None,
    result: str | None = None,
) -> str:
    """Export the board's full history with an explicit result override.

    Imported PGNs store their declared result on ``board.pgn_result``.  This
    keeps a service-supplied result distinct from the board's rule-derived
    status while allowing callers to override it explicitly.
    """

    tags: dict[str, str] = {"Event": "Neon Chess Local Game", "Site": "Local"}
    if board.initial_fen != START_FEN or getattr(board, "pgn_setup", False):
        tags.update({"SetUp": "1", "FEN": board.initial_fen})
    if headers:
        tags.update({str(key): str(value) for key, value in headers.items()})

    selected_result = result
    if selected_result is None:
        selected_result = getattr(board, "pgn_result", None) or tags.get("Result") or result_for(board)
    if selected_result not in RESULTS:
        raise ValueError(f"Invalid PGN result: {selected_result}")
    tags["Result"] = selected_result

    for key, value in tags.items():
        if not _TAG_NAME.fullmatch(key):
            raise ValueError(f"Invalid PGN tag name: {key}")
        tags[key] = str(value)
    lines = [f'[{key} "{_escape_tag_value(value)}"]' for key, value in tags.items()]
    moves = san_history(board)
    movetext: list[str] = []
    replay = Board(board.initial_fen)
    for san, recorded in zip(moves, board.history):
        marker = f"{replay.fullmove}." if replay.white_to_move else f"{replay.fullmove}..."
        movetext.extend((marker, san))
        replay.make_move(next(move for move in replay.legal_moves() if move.uci == recorded.uci))
    movetext.append(tags["Result"])
    return "\n".join(lines) + "\n\n" + " ".join(movetext) + "\n"


def import_pgn(text: str) -> Board:
    """Load one bounded main-line PGN, rejecting malformed extra games."""

    if not isinstance(text, str):
        raise TypeError("PGN text must be a string")
    if len(text) > _MAX_PGN_CHARS:
        raise ValueError("PGN is too large")

    tags, movetext = _split_headers(text)
    setup = tags.get("SetUp")
    if setup not in (None, "0", "1"):
        raise ValueError("PGN SetUp tag must be 0 or 1")
    if setup == "1" and not tags.get("FEN"):
        raise ValueError("PGN SetUp=1 requires a FEN tag")
    start_fen = tags.get("FEN") if setup == "1" else None
    board = Board(start_fen) if start_fen else Board()

    declared_tag_result = tags.get("Result")
    if declared_tag_result is not None and declared_tag_result not in RESULTS:
        raise ValueError(f"Invalid PGN Result tag: {declared_tag_result}")

    tokens = _movetext_tokens(movetext)
    result_token: str | None = None
    move_count = 0
    for token in tokens:
        if result_token is not None:
            raise ValueError("PGN movetext continues after the game result")
        if _MOVE_NUMBER.fullmatch(token):
            continue
        if token in RESULTS:
            if result_token is not None:
                raise ValueError("Multiple PGN game results")
            result_token = token
            continue
        move_count += 1
        if move_count > _MAX_MAINLINE_PLIES:
            raise ValueError("PGN main line is too long")
        board.make_move(resolve_san(board, token))

    if result_token and declared_tag_result and result_token != declared_tag_result:
        raise ValueError("PGN Result tag does not match movetext result")
    imported_result = result_token or declared_tag_result
    if setup == "1":
        # Keep an explicit SetUp/FEN pair even when the FEN happens to be the
        # normal starting position; Board.initial_fen alone cannot express
        # that distinction.
        board.pgn_setup = True
    if imported_result is not None:
        # Board.clone currently does not know about this application-level
        # attribute; the core owner should preserve it when updating clone().
        board.pgn_result = imported_result
    return board


def result_for(board: Board) -> str:
    status = board.game_status()
    if status == "checkmate_white":
        return "1-0"
    if status == "checkmate_black":
        return "0-1"
    if status.startswith("draw") or status == "stalemate":
        return "1/2-1/2"
    return "*"
