import time
import unittest

from server import GameService


class ServiceTests(unittest.TestCase):
    def wait_until_idle(self, service, timeout=4.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = service.state()
            if state["engine_info"]["status"] != "thinking":
                return state
            time.sleep(0.03)
        self.fail("engine search did not finish in time")

    def test_async_engine_move_updates_authoritative_position(self):
        service = GameService()
        service.reset({"player_color": "white", "engine_level": 1, "engine_time": 0.08})
        service.play("e2e4")
        started = service.start_engine()
        self.assertEqual(started["engine_info"]["status"], "thinking")
        finished = self.wait_until_idle(service)
        self.assertEqual(len(finished["history"]), 2)
        self.assertEqual(finished["turn"], finished["player_color"])

    def test_black_game_starts_with_engine_turn(self):
        service = GameService()
        initial = service.reset({"player_color": "black", "engine_level": 1, "engine_time": 0.08})
        self.assertEqual(initial["turn"], "white")
        self.assertEqual(len(initial["history"]), 0)
        service.start_engine()
        finished = self.wait_until_idle(service)
        self.assertEqual(len(finished["history"]), 1)

    def test_stop_prevents_a_stale_engine_result(self):
        service = GameService()
        service.reset({"player_color": "white", "engine_level": 6, "engine_time": 0.08})
        service.play("e2e4")
        service.start_engine()
        service.stop_engine()
        time.sleep(0.2)
        state = service.state()
        self.assertEqual(state["history"], ["e2e4"])
        self.assertIsNone(state["engine_info"].get("error"))

    def test_pgn_export_and_import_preserve_position(self):
        service = GameService()
        service.play("e2e4")
        service.start_engine()
        state = self.wait_until_idle(service)
        pgn = service.pgn()
        restored = GameService()
        restored.load_pgn(pgn)
        self.assertEqual(restored.state()["fen"], state["fen"])

    def test_clock_control_is_returned_and_decreases(self):
        service = GameService()
        initial = service.reset({"player_color": "white", "clock_seconds": 60})
        self.assertEqual(initial["clock_limit"], 60.0)
        time.sleep(0.05)
        later = service.state()
        self.assertLess(later["clocks"]["white"], initial["clocks"]["white"])


if __name__ == "__main__":
    unittest.main()
