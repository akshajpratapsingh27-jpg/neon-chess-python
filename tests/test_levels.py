import unittest

from chess_engine import Board, EngineManager, LEVELS, get_level
from chess_engine.stockfish import StockfishEngine, find_stockfish


class LevelTests(unittest.TestCase):
    def test_six_levels_are_available(self):
        self.assertEqual([level.id for level in LEVELS], [1, 2, 3, 4, 5, 6])
        self.assertEqual(get_level(6).name, "MASTER")

    def test_invalid_level_defaults_to_club(self):
        self.assertEqual(get_level("invalid").id, 4)

    def test_manager_falls_back_without_stockfish(self):
        manager = EngineManager(level=6, stockfish_path="definitely-not-stockfish.exe")
        move, info = manager.choose_move(Board(), time_limit=0.08)
        self.assertIsNotNone(move)
        self.assertEqual(info["backend"], "custom")
        self.assertTrue(info["fallback"])

    @unittest.skipUnless(find_stockfish(), "Stockfish is not installed")
    def test_stockfish_master_level_returns_a_legal_move(self):
        manager = EngineManager(level=6)
        move, info = manager.choose_move(Board(), time_limit=0.25)
        self.assertIsNotNone(move)
        self.assertEqual(info["backend"], "stockfish")
        self.assertFalse(info["fallback"])


if __name__ == "__main__":
    unittest.main()
