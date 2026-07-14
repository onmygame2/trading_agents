import unittest

from trade_engine_v2 import evaluate_sell_decision, is_limit_up_move, resolve_trade_rules


class TradingRuleTests(unittest.TestCase):
    def test_hard_stop_loss(self):
        rules = resolve_trade_rules("composite")
        position = {"avg_price": 10.0, "high_price": 10.0, "hold_days": 1}
        self.assertIn("硬止损", evaluate_sell_decision(position, 9.1, rules))

    def test_trailing_stop(self):
        rules = resolve_trade_rules("composite")
        position = {"avg_price": 10.0, "high_price": 12.0, "hold_days": 5}
        self.assertIn("移动止盈", evaluate_sell_decision(position, 10.4, rules))

    def test_board_specific_limit_up(self):
        self.assertTrue(is_limit_up_move("600000", 9.6))
        self.assertFalse(is_limit_up_move("688001", 9.8))


if __name__ == "__main__":
    unittest.main()
