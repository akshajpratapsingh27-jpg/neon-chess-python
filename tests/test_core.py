import unittest

from chess_engine import Board


class BoardTests(unittest.TestCase):
    @staticmethod
    def perft(board, depth):
        if depth == 0:
            return 1
        nodes = 0
        for move in board.legal_moves():
            undo = board.make_move(move)
            nodes += BoardTests.perft(board, depth - 1)
            board.unmake_move(undo)
        return nodes

    def test_initial_position_has_twenty_moves(self):
        board = Board()
        self.assertEqual(len(board.legal_moves()), 20)

    def test_initial_position_perft_regression(self):
        board = Board()
        self.assertEqual(self.perft(board, 2), 400)
        self.assertEqual(self.perft(board, 3), 8902)

    def test_basic_moves_and_undo_restore_position(self):
        board = Board()
        initial_fen = board.to_fen()
        board.push_uci("e2e4")
        board.push_uci("e7e5")
        board.push_uci("g1f3")
        self.assertEqual(board.piece_at("f3"), "N")
        self.assertEqual(board.piece_at("e4"), "P")
        board.unmake_move()
        board.unmake_move()
        board.unmake_move()
        self.assertEqual(board.to_fen(), initial_fen)

    def test_castling_moves_are_legal(self):
        board = Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        moves = {move.uci for move in board.legal_moves()}
        self.assertIn("e1g1", moves)
        self.assertIn("e1c1", moves)

    def test_en_passant(self):
        board = Board("8/8/8/3pP3/8/8/8/4K2k w - d6 0 1")
        move = next(move for move in board.legal_moves() if move.uci == "e5d6")
        self.assertTrue(move.is_en_passant)
        self.assertTrue(board.repetition_key().endswith(" d6"))
        board.make_move(move)
        self.assertEqual(board.piece_at("d6"), "P")
        self.assertIsNone(board.piece_at("d5"))

    def test_pinned_en_passant_is_illegal_and_omitted_from_repetition_key(self):
        board = Board("k3r3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
        self.assertNotIn("e5d6", {move.uci for move in board.legal_moves()})
        without_ep = Board("k3r3/8/8/3pP3/8/8/8/4K3 w - - 0 1")
        self.assertEqual(board.repetition_key(), without_ep.repetition_key())

    def test_kiwipete_perft_regression(self):
        board = Board("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1")
        self.assertEqual(len(board.legal_moves()), 48)
        self.assertEqual(self.perft(board, 2), 2039)

    def test_fen_structural_validation(self):
        invalid = (
            "8/8/8/8/8/8/8/4K3 w - - 0 1",  # missing black king
            "4k3/8/8/8/8/8/8/4K2K w - - 0 1",  # duplicate white king
            "8/8/8/8/8/8/8/4kK3 w - - 0 1",  # adjacent kings
            "P3k3/8/8/8/8/8/8/4K3 w - - 0 1",  # pawn on the back rank
            "4k3/8/8/8/8/8/8/4K3 w K - 0 1",  # castling rook absent
            "4k3/8/8/8/4P3/8/8/4K3 w - e3 0 1",  # wrong EP side/rank
            "4k3/8/8/8/8/8/8/4K3 w - - -1 1",  # negative halfmove clock
            "4k3/8/8/8/8/8/8/4K3 w - - 0 0",  # invalid fullmove number
        )
        for fen in invalid:
            with self.subTest(fen=fen):
                with self.assertRaises(ValueError):
                    Board(fen)

    def test_clone_keeps_reversible_history(self):
        board = Board()
        board.push_uci("e2e4")
        clone = board.clone()
        clone.unmake_move()
        self.assertEqual(clone.to_fen(), Board().to_fen())
        self.assertEqual(board.to_fen(), "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")

    def test_insufficient_material_status(self):
        board = Board("7k/8/8/8/8/8/8/2B1K3 w - - 0 1")
        self.assertEqual(board.game_status(), "draw_insufficient_material")

    def test_promotion_generates_all_choices(self):
        board = Board("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
        promotions = {move.uci for move in board.legal_moves() if move.uci.startswith("a7a8")}
        self.assertEqual(promotions, {"a7a8q", "a7a8r", "a7a8b", "a7a8n"})

    def test_checkmate_status(self):
        board = Board("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")
        self.assertEqual(board.game_status(), "checkmate_white")


if __name__ == "__main__":
    unittest.main()
