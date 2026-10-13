import json
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from server import ChessHandler, SERVICE


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), ChessHandler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    def setUp(self):
        SERVICE.reset({"player_color": "white", "engine_level": 1, "engine_time": 0.08})

    @classmethod
    def tearDownClass(cls):
        SERVICE.stop_engine()
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def request(self, method, path, payload=None):
        connection = HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=5)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        connection.request(method, path, body, {"Content-Type": "application/json"} if body else {})
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response.status, response.getheader("Content-Type", ""), raw

    def test_state_endpoint_returns_authoritative_json(self):
        status, content_type, raw = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertIn("application/json", content_type)
        state = json.loads(raw)
        self.assertEqual(state["fen"].split()[1], "w")
        self.assertEqual(len(state["legal_moves"]), 20)
        self.assertTrue(state["game_id"])
        self.assertIsInstance(state["revision"], int)

    def test_move_and_pgn_endpoints(self):
        self.request("POST", "/api/new", {"player_color": "white", "engine_level": 1})
        status, _, raw = self.request("POST", "/api/move", {"move": "e2e4"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["san_history"], ["e4"])
        status, content_type, raw = self.request("GET", "/api/pgn")
        self.assertEqual(status, 200)
        self.assertIn("application/x-chess-pgn", content_type)
        self.assertIn("e4", raw.decode("utf-8"))

    def test_fen_endpoint_loads_a_position(self):
        fen = "4k3/8/8/8/8/8/8/4K3 w - - 0 1"
        status, _, raw = self.request("POST", "/api/fen", {"fen": fen})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["fen"], fen)


if __name__ == "__main__":
    unittest.main()
