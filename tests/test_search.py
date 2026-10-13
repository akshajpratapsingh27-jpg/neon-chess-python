import time
import unittest

from chess_engine import Board, Engine
from chess_engine.search import INF, MATE_SCORE, PIECE_SQUARES, SearchTimeout


class SearchTests(unittest.TestCase):
    def test_engine_returns_a_legal_move(self):
        board = Board()
        engine = Engine(max_depth=2)
        move, info = engine.choose_move(board, time_limit=0.2)
        self.assertIsNotNone(move)
        self.assertIn(move.uci, {candidate.uci for candidate in board.legal_moves()})
        self.assertIn("nodes", info)
        self.assertIn("depth", info)

    def test_search_stops_at_time_limit(self):
        board = Board()
        initial_fen = board.to_fen()
        engine = Engine(max_depth=20)
        move, info = engine.choose_move(board, time_limit=0.05)
        self.assertIsNotNone(move)
        self.assertGreaterEqual(info["nodes"], 1)
        self.assertEqual(board.to_fen(), initial_fen)

    def test_forced_timeout_restores_board_and_reports_completed_depth(self):
        board = Board()
        initial_fen = board.to_fen()
        engine = Engine(max_depth=2)
        original_search = engine._search

        def force_on_second_iteration(position, depth, alpha, beta, ply):
            if engine.completed_depth >= 1:
                raise SearchTimeout
            return original_search(position, depth, alpha, beta, ply)

        engine._search = force_on_second_iteration
        move, info = engine.choose_move(board, time_limit=10.0)

        self.assertIsNotNone(move)
        self.assertEqual(info["depth"], 1)
        self.assertEqual(info["completed_depth"], 1)
        self.assertEqual(board.to_fen(), initial_fen)

    def test_quiescence_handles_terminal_positions_and_en_passant(self):
        engine = Engine()
        engine.start_time = time.monotonic()
        engine.time_limit = 10.0

        checkmate = Board("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")
        stalemate = Board("7k/5Q2/7K/8/8/8/8/8 b - - 0 1")
        fifty_move = Board("4k3/8/8/8/8/8/8/4K3 w - - 100 1")
        insufficient = Board("7k/8/8/8/8/8/8/2B1K3 w - - 0 1")

        self.assertEqual(engine._quiescence(checkmate, -INF, INF, 0), -MATE_SCORE)
        self.assertEqual(engine._quiescence(stalemate, -INF, INF, 0), 0)
        self.assertEqual(engine._quiescence(fifty_move, -INF, INF, 0), 0)
        self.assertEqual(engine._quiescence(insufficient, -INF, INF, 0), 0)

        en_passant = Board("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
        capture = next(move for move in en_passant.legal_moves() if move.uci == "e5d6")
        self.assertTrue(capture.is_en_passant)
        self.assertGreater(
            engine._quiescence(en_passant, -INF, INF, 0),
            engine.evaluate(en_passant),
        )

    def test_piece_square_tables_are_complete(self):
        self.assertEqual({piece: len(values) for piece, values in PIECE_SQUARES.items()}, {
            "p": 64,
            "n": 64,
            "b": 64,
            "r": 64,
            "q": 64,
            "k": 64,
        })

    def test_tt_bounds_and_draw_context(self):
        board = Board("4k3/8/8/8/8/8/8/R3K3 w - - 0 1")
        engine = Engine()
        engine.start_time = time.monotonic()
        engine.time_limit = 10.0

        engine._search(board, 1, -1, 1, 0)
        self.assertEqual(engine.table[engine._tt_key(board)].flag, "lower")
        engine.table.clear()
        engine._search(board, 1, 1_000, 2_000, 0)
        self.assertEqual(engine.table[engine._tt_key(board)].flag, "upper")

        repeated = board.clone()
        repeated.position_history = [repeated.repetition_key()] * 3
        self.assertNotEqual(engine._tt_key(board), engine._tt_key(repeated))
        self.assertEqual(engine._search(repeated, 1, -INF, INF, 0), 0)


if __name__ == "__main__":
    unittest.main()
