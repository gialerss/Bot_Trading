import unittest

from telegram_mt5_bot.models import EventKind, TradeSide
from telegram_mt5_bot.parser import parse_message


class ParserTests(unittest.TestCase):
    def test_parse_open_signal(self):
        payload = """Apro una nuova operazione 🚀
XAUUSD BUY
Entry: 5120
SL: 5107.78
TP1: 5123.98
TP2: 5125.18
TP3: 5129.68
"""
        event = parse_message(payload)
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, EventKind.OPEN)
        self.assertEqual(event.symbol, "XAUUSD")
        self.assertEqual(event.side, TradeSide.BUY)
        self.assertEqual(event.entry, 5120.0)
        self.assertEqual(event.sl, 5107.78)
        self.assertEqual(event.tps, [5123.98, 5125.18, 5129.68])

    def test_parse_signal_alert_format(self):
        payload = """SIGNAL ALERT

SELL EURCHF 0.94066

✅ TP1 0.93915
✅ TP2 0.93565
✅ TP3 0.93065
🛑 SL 0.94566 ( 50 pips )"""
        event = parse_message(payload)
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, EventKind.OPEN)
        self.assertEqual(event.symbol, "EURCHF")
        self.assertEqual(event.side, TradeSide.SELL)
        self.assertEqual(event.entry, 0.94066)
        self.assertEqual(event.sl, 0.94566)
        self.assertEqual(event.tps, [0.93915, 0.93565, 0.93065])

    def test_parse_stop_loss(self):
        payload = """🛑 Stop Loss preso
XAUUSD"""
        event = parse_message(payload)
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, EventKind.STOP_LOSS_HIT)
        self.assertEqual(event.symbol, "XAUUSD")

    def test_parse_tp_level(self):
        payload = """✅ Take Profit 1 preso
XAUUSD"""
        event = parse_message(payload)
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, EventKind.TAKE_PROFIT_LEVEL_HIT)
        self.assertEqual(event.tp_level, 1)
        self.assertEqual(event.symbol, "XAUUSD")

    def test_parse_tp_level_short_format(self):
        event = parse_message("TP1✅")
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, EventKind.TAKE_PROFIT_LEVEL_HIT)
        self.assertEqual(event.tp_level, 1)
        self.assertIsNone(event.symbol)

    def test_parse_move_stop_break_even(self):
        event = parse_message("Sposto lo Stop Loss a: Break Even")
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, EventKind.MOVE_SL_BREAK_EVEN)
        self.assertIsNone(event.symbol)

    def test_parse_break_even_closed(self):
        payload = """⚖️ Chiusa a Break Even
XAUUSD"""
        event = parse_message(payload)
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, EventKind.BREAK_EVEN_CLOSED)
        self.assertEqual(event.symbol, "XAUUSD")

    def test_parse_break_even_closed_plural_format(self):
        event = parse_message("Chiusi a break even")
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, EventKind.BREAK_EVEN_CLOSED)
        self.assertIsNone(event.symbol)

    def test_parse_generic_take_profit(self):
        payload = """✅ Take Profit preso
XAUUSD"""
        event = parse_message(payload)
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, EventKind.TAKE_PROFIT_HIT)
        self.assertEqual(event.symbol, "XAUUSD")

    def test_parse_manual_close_message(self):
        event = parse_message("Chiudiamo manualmente anche la terza operazione✅")
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, EventKind.TAKE_PROFIT_CLOSED)

    def test_ignore_missed_tp_sl_hit_message(self):
        self.assertIsNone(parse_message("MISSED TP SL HIT"))

    def test_ignore_unrelated_message(self):
        self.assertIsNone(parse_message("Voliamo ragazzi🔥"))


if __name__ == "__main__":
    unittest.main()
