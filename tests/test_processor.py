import os
import tempfile
import unittest
from pathlib import Path

from telegram_mt5_bot.config import AppConfig, TradingSettings
from telegram_mt5_bot.models import IncomingTelegramMessage
from telegram_mt5_bot.mt5_bridge import OrderPlacementResult
from telegram_mt5_bot.processor import SignalProcessor
from telegram_mt5_bot.state import SignalStateStore


class FakeMT5Client:
    def __init__(self):
        self.active_signals: dict[str, bool] = {}
        self.close_all_calls: list[str] = []
        self.break_even_calls: list[str] = []
        self.placements: list[dict[str, float | str | None]] = []

    def place_signal(self, signal, broker_symbol: str, signal_id: str, volume: float, broker_tp: float | None = None) -> OrderPlacementResult:
        self.active_signals[signal_id] = True
        self.placements.append(
            {
                "signal_id": signal_id,
                "broker_symbol": broker_symbol,
                "volume": volume,
                "broker_tp": broker_tp,
            }
        )
        tp_level = int(signal_id.rsplit("tp", 1)[1])
        return OrderPlacementResult(
            order_ticket=100 + tp_level,
            position_ticket=200 + tp_level,
            is_pending=False,
            requested_price=signal.entry,
            requested_volume=volume,
            order_comment=f"test:{signal_id[-10:]}",
        )

    def sync_signal(self, signal):
        return signal

    def signal_exists(self, signal) -> bool:
        return self.active_signals.get(signal.signal_id, False)

    def move_stop_to_break_even(self, signal) -> None:
        self.break_even_calls.append(signal.signal_id)

    def close_all(self, signal) -> float:
        self.close_all_calls.append(signal.signal_id)
        self.active_signals[signal.signal_id] = False
        return signal.remaining_volume_estimate


class ProcessorTests(unittest.TestCase):
    def test_selected_tp_value_falls_back_to_last_available(self):
        settings = TradingSettings(selected_tp_level=3)
        level, value = settings.selected_tp_value([10.0, 20.0])
        self.assertEqual(level, 2)
        self.assertEqual(value, 20.0)

    def test_processor_opens_one_trade_for_each_tp_and_manages_break_even(self):
        logs: list[str] = []
        config = AppConfig(trading=TradingSettings(default_volume=0.04, apply_final_tp_to_broker=True))
        fake_mt5 = FakeMT5Client()

        with tempfile.TemporaryDirectory() as tmp_dir:
            previous = Path.cwd()
            os.chdir(tmp_dir)
            try:
                state_store = SignalStateStore()
                processor = SignalProcessor(config, state_store, fake_mt5, logs.append)

                processor.handle_message(
                    IncomingTelegramMessage(
                        chat_id="chat-1",
                        message_id=100,
                        timestamp="2026-03-05T09:01:00+00:00",
                        text="""SIGNAL ALERT

SELL XAUUSD 5161

TP1 5156.48
TP2 5155.28
TP3 5150.78
SL 5172.68""",
                    )
                )

                active_after_open = state_store.find_active_by_symbol("XAUUSD")
                self.assertEqual(len(active_after_open), 3)
                self.assertEqual(
                    [placement["broker_tp"] for placement in fake_mt5.placements],
                    [5156.48, 5155.28, 5150.78],
                )

                processor.handle_message(
                    IncomingTelegramMessage(
                        chat_id="chat-1",
                        message_id=101,
                        timestamp="2026-03-05T09:03:00+00:00",
                        text="TP1 PRESO✅",
                    )
                )

                active_after_tp1 = state_store.find_active_by_symbol("XAUUSD")
                self.assertEqual(len(active_after_tp1), 2)
                self.assertEqual(fake_mt5.close_all_calls, ["chat-1-100-tp1"])

                processor.handle_message(
                    IncomingTelegramMessage(
                        chat_id="chat-1",
                        message_id=102,
                        timestamp="2026-03-05T09:03:30+00:00",
                        text="Sposto lo Stop Loss a: Break Even",
                    )
                )

                active_after_be = state_store.find_active_by_symbol("XAUUSD")
                self.assertEqual(len(active_after_be), 2)
                self.assertCountEqual(
                    fake_mt5.break_even_calls,
                    ["chat-1-100-tp2", "chat-1-100-tp3"],
                )
                self.assertTrue(all(signal.moved_to_break_even for signal in active_after_be))

                processor.handle_message(
                    IncomingTelegramMessage(
                        chat_id="chat-1",
                        message_id=103,
                        timestamp="2026-03-05T09:04:00+00:00",
                        text="Take profit 2✅",
                    )
                )

                active_after_tp2 = state_store.find_active_by_symbol("XAUUSD")
                self.assertEqual(len(active_after_tp2), 1)
                self.assertCountEqual(
                    fake_mt5.close_all_calls,
                    ["chat-1-100-tp1", "chat-1-100-tp2"],
                )

                processor.handle_message(
                    IncomingTelegramMessage(
                        chat_id="chat-1",
                        message_id=104,
                        timestamp="2026-03-05T09:05:00+00:00",
                        text="Chiusi a break even",
                    )
                )

                self.assertEqual(state_store.find_active_by_symbol("XAUUSD"), [])
                self.assertCountEqual(
                    fake_mt5.close_all_calls,
                    ["chat-1-100-tp1", "chat-1-100-tp2", "chat-1-100-tp3"],
                )
                stored_signals = sorted(state_store.all_signals(), key=lambda item: item.signal_id)
                self.assertEqual([signal.closed_reason for signal in stored_signals], ["tp1", "tp2", "break_even_closed"])
                self.assertIn("create 3 operazioni", "\n".join(logs))
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
