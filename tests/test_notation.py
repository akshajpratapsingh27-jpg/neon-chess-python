import unittest

from chess_engine import Board, export_pgn, import_pgn, move_to_san, resolve_san, san_history


class NotationTests(unittest.TestCase):
    def test_opening_moves_render_as_san(self):
        board = Board()
        move = resolve_san(board, "e4")
        self.assertEqual(move_to_san(board, move), "e4")
        board.make_move(move)
        move = resolve_san(board, "e5")
        self.assertEqual(move_to_san(board, move), "e5")

    def test_castling_and_checkmate_notation(self):
        board = Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        move = resolve_san(board, "O-O")
        self.assertTrue(move.is_castle)
        self.assertEqual(move_to_san(board, move), "O-O")
        mate = Board("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")
        self.assertEqual(mate.game_status(), "checkmate_white")

    def test_pgn_round_trip(self):
        board = Board()
        for san in ("e4", "e5", "Nf3", "Nc6", "Bb5"):
            board.make_move(resolve_san(board, san))
        self.assertEqual(san_history(board), ["e4", "e5", "Nf3", "Nc6", "Bb5"])
        restored = import_pgn(export_pgn(board))
        self.assertEqual(restored.to_fen(), board.to_fen())

    def test_non_starting_fen_is_preserved_in_pgn(self):
        board = Board("4k3/8/8/8/8/8/4K3/8 w - - 0 1")
        pgn = export_pgn(board)
        self.assertIn('[SetUp "1"]', pgn)
        self.assertIn('[FEN "4k3/8/8/8/8/8/4K3/8 w - - 0 1"]', pgn)
        self.assertEqual(import_pgn(pgn).to_fen(), board.to_fen())

    def test_compact_mainline_skips_nested_rav_comments_and_nags(self):
        pgn = """
            [Event "Annotated \\"game\\""]
            [Result "*"]

            1.e4 {mainline (text)} e5 $1 2.Nf3 (2.d4 d5 (2...exd4)) Nc6
            3.Bb5 a6 *
        """
        board = import_pgn(pgn)
        self.assertEqual(san_history(board), ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"])
        self.assertEqual(board.pgn_result, "*")

    def test_malformed_or_multiple_games_are_rejected(self):
        for pgn in (
            "1. e4 (1... e5 *",
            "1. e4 {unterminated",
            "1. e4 ) *",
            "1. e4 *\n\n[Event \"second\"]\n1. d4 *",
        ):
            with self.subTest(pgn=pgn):
                with self.assertRaises(ValueError):
                    import_pgn(pgn)

    def test_imported_result_and_explicit_result_override_are_preserved(self):
        board = import_pgn('[Result "0-1"]\n\n1. e4 0-1')
        self.assertIn('[Result "0-1"]', export_pgn(board))
        self.assertIn('[Result "1-0"]', export_pgn(board, result="1-0"))

    def test_explicit_setup_tag_is_preserved_for_start_fen(self):
        fen = Board().to_fen()
        board = import_pgn(f'[SetUp "1"]\n[FEN "{fen}"]\n\n*')
        exported = export_pgn(board)
        self.assertIn('[SetUp "1"]', exported)
        self.assertIn(f'[FEN "{fen}"]', exported)

    def test_black_to_move_fullmove_number_is_exported(self):
        board = Board("4k3/8/8/8/8/8/4K3/8 b - - 0 17")
        board.make_move(resolve_san(board, "Kd7"))
        self.assertIn("17... Kd7", export_pgn(board))

    def test_tag_values_are_escaped_and_wrong_check_markers_rejected(self):
        board = Board()
        pgn = export_pgn(board, headers={"Annotator": 'A "quoted" \\ path'})
        self.assertIn('\\"quoted\\"', pgn)
        self.assertIn("\\\\ path", pgn)
        with self.assertRaises(ValueError):
            resolve_san(Board(), "e4+")


if __name__ == "__main__":
    unittest.main()
