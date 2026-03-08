import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from telegram_mt5_bot.web.controller import BotController


class WebControllerTests(unittest.TestCase):
    def test_coerce_config_uses_defaults_for_blank_numeric_fields(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            previous = Path.cwd()
            os.chdir(tmp_dir)
            try:
                controller = BotController()
                config = controller._coerce_config(
                    {
                        "telegram": {
                            "api_id": "12345",
                            "api_hash": "hash",
                            "session_name": "session_name",
                            "phone_number": "+390000000",
                            "source_chat": "@source",
                        },
                        "telegram_bot": {
                            "bot_token": "123:abc",
                            "session_name": "control_session",
                            "allowed_user_ids_text": "10\n20",
                            "allowed_usernames_text": "@mario\nluca",
                        },
                        "mt5": {
                            "platform": "mt4",
                            "magic": "",
                            "deviation_points": "",
                            "portable": "true",
                        },
                        "trading": {
                            "default_volume": "",
                            "selected_tp_level": "2",
                            "tp1_close_percent": "60",
                            "allow_pending_orders": "false",
                        },
                    }
                )
            finally:
                os.chdir(previous)

        self.assertEqual(config.telegram.api_id, "12345")
        self.assertEqual(config.telegram_bot.bot_token, "123:abc")
        self.assertEqual(config.telegram_bot.session_name, "control_session")
        self.assertEqual(config.telegram_bot.allowed_user_ids(), {10, 20})
        self.assertEqual(config.telegram_bot.allowed_usernames(), {"mario", "luca"})
        self.assertEqual(config.mt5.platform, "mt4")
        self.assertTrue(config.mt5.portable)
        self.assertEqual(config.mt5.magic, 260326)
        self.assertEqual(config.mt5.deviation_points, 50)
        self.assertEqual(config.trading.default_volume, 0.01)
        self.assertEqual(config.trading.selected_tp_level, 2)
        self.assertEqual(config.trading.tp1_close_percent, 60.0)
        self.assertFalse(config.trading.allow_pending_orders)

    def test_dashboard_bootstrap_contains_sections(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            previous = Path.cwd()
            os.chdir(tmp_dir)
            try:
                controller = BotController()
                payload = controller.dashboard_bootstrap()
            finally:
                os.chdir(previous)

        self.assertIn("config", payload)
        self.assertIn("status", payload)
        self.assertIn("signals", payload)
        self.assertIn("logs", payload)
        self.assertIn("diagnostics", payload)
        self.assertFalse(payload["status"]["running"])

    def test_run_full_diagnostics_aggregates_results(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            previous = Path.cwd()
            os.chdir(tmp_dir)
            try:
                controller = BotController()
                controller._build_telegram_checks = lambda: [
                    {"key": "telegram_session", "label": "Telegram sessione", "ok": True, "detail": "ok"},
                    {"key": "telegram_source_chat", "label": "Telegram source chat", "ok": False, "detail": "missing"},
                ]
                controller._build_mt5_check = lambda: {
                    "key": "mt5_bridge",
                    "label": "MetaTrader 5",
                    "ok": True,
                    "detail": "ok",
                }
                diagnostics = controller.run_full_diagnostics()
            finally:
                os.chdir(previous)

        self.assertEqual(diagnostics["summary"]["total"], 3)
        self.assertEqual(diagnostics["summary"]["passed"], 2)
        self.assertEqual(diagnostics["summary"]["failed"], 1)
        self.assertFalse(diagnostics["summary"]["ok"])
        self.assertEqual(len(diagnostics["checks"]), 3)

    def test_build_telegram_checks_uses_running_service_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            previous = Path.cwd()
            os.chdir(tmp_dir)
            try:
                controller = BotController()
                controller._service = SimpleNamespace(
                    is_running=True,
                    telegram_diagnostics_snapshot=lambda: {
                        "authorized": True,
                        "session_message": "Sessione Telegram gia' in uso dal relay attivo.",
                        "source_chat_ok": True,
                        "source_chat_message": "Source Chat risolto correttamente: Test Channel.",
                    },
                )
                checks = controller._build_telegram_checks()
            finally:
                os.chdir(previous)

        self.assertEqual(len(checks), 2)
        self.assertTrue(checks[0]["ok"])
        self.assertEqual(checks[0]["detail"], "Sessione Telegram gia' in uso dal relay attivo.")
        self.assertTrue(checks[1]["ok"])
        self.assertEqual(checks[1]["detail"], "Source Chat risolto correttamente: Test Channel.")

    def test_coerce_config_strips_invisible_unicode_from_mt5_login(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            previous = Path.cwd()
            os.chdir(tmp_dir)
            try:
                controller = BotController()
                config = controller._coerce_config({"mt5": {"login": "7003005\u200e"}})
            finally:
                os.chdir(previous)

        self.assertEqual(config.mt5.login, "7003005")


if __name__ == "__main__":
    unittest.main()
