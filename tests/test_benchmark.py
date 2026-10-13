import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import benchmark


class FakeManager:
    instances = []
    stockfish_available_by_level = {}

    def __init__(self, level):
        self.level = SimpleNamespace(backend="stockfish" if level == 5 else "custom")
        self.stockfish_available = self.stockfish_available_by_level.get(level, True)
        self.stopped = False
        self.instances.append(self)

    def choose_move(self, board, _seconds):
        return board.legal_moves()[0], {"backend": "custom", "nodes": 7}

    def stop(self):
        self.stopped = True


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        FakeManager.instances = []
        FakeManager.stockfish_available_by_level = {}

    def test_smoke_bound_is_unfinished_and_not_a_draw(self):
        summary = benchmark.run_benchmark(
            games=1,
            seconds=0.08,
            white_level=1,
            black_level=1,
            max_plies=2,
            progress=False,
        )
        detail = summary["games_detail"][0]
        self.assertEqual(detail["plies"], 2)
        self.assertEqual(detail["result"], "*")
        self.assertTrue(detail["unfinished"])
        self.assertEqual(summary["draws"], 0)

    def test_games_swap_colors_and_use_distinct_openings(self):
        with patch.object(benchmark, "EngineManager", FakeManager):
            summary = benchmark.run_benchmark(
                games=3,
                seconds=0.08,
                white_level=1,
                black_level=2,
                max_plies=8,
                progress=False,
            )
        details = summary["games_detail"]
        self.assertEqual([(item["levels"]["white"], item["levels"]["black"]) for item in details], [(1, 2), (2, 1), (1, 2)])
        self.assertEqual(len({tuple(item["opening"]) for item in details}), 3)
        self.assertTrue(all(item["backend"]["white"] == "custom" for item in details))
        self.assertTrue(all(manager.stopped for manager in FakeManager.instances))

    def test_stockfish_is_strict_unless_fallback_is_explicit(self):
        FakeManager.stockfish_available_by_level = {5: False}
        with patch.object(benchmark, "EngineManager", FakeManager):
            with self.assertRaises(RuntimeError):
                benchmark.play_game(5, 4, 0.08, max_plies=1)
        self.assertTrue(all(manager.stopped for manager in FakeManager.instances))

        FakeManager.instances = []
        with patch.object(benchmark, "EngineManager", FakeManager):
            result = benchmark.play_game(5, 4, 0.08, max_plies=1, allow_fallback=True)
        self.assertEqual(result["backend"]["white"], "custom")
        self.assertEqual(result["engine_identity"]["white"], "neon-chess-custom-search")

    def test_progress_is_flushed_to_the_progress_stream(self):
        stream = io.StringIO()
        with patch.object(benchmark, "EngineManager", FakeManager):
            benchmark.run_benchmark(
                games=1,
                seconds=0.08,
                white_level=1,
                black_level=1,
                max_plies=0,
                progress_stream=stream,
            )
        self.assertIn("game 1/1", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
