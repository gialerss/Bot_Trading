import os
import shutil
import unittest
from pathlib import Path
from types import MethodType, SimpleNamespace
from uuid import uuid4

from telegram_mt5_bot.web.controller import BotController


def _make_test_dir(name: str) -> Path:
    path = Path(".tmp-test") / f"{name}-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path


class WebControllerTests(unittest.TestCase):
    def test_coerce_config_uses_defaults_for_blank_numeric_fields(self):
        sandbox = _make_test_dir("controller-coerce")
        previous = Path.cwd()
        try:
            os.chdir(sandbox)
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
            shutil.rmtree(sandbox, ignore_errors=True)

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
        sandbox = _make_test_dir("controller-bootstrap")
        previous = Path.cwd()
        try:
            os.chdir(sandbox)
            controller = BotController()
            payload = controller.dashboard_bootstrap()
        finally:
            os.chdir(previous)
            shutil.rmtree(sandbox, ignore_errors=True)

        self.assertIn("config", payload)
        self.assertIn("status", payload)
        self.assertIn("signals", payload)
        self.assertIn("logs", payload)
        self.assertIn("diagnostics", payload)
        self.assertFalse(payload["status"]["running"])

    def test_run_full_diagnostics_aggregates_results(self):
        sandbox = _make_test_dir("controller-diagnostics")
        previous = Path.cwd()
        try:
            os.chdir(sandbox)
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
            shutil.rmtree(sandbox, ignore_errors=True)

        self.assertEqual(diagnostics["summary"]["total"], 3)
        self.assertEqual(diagnostics["summary"]["passed"], 2)
        self.assertEqual(diagnostics["summary"]["failed"], 1)
        self.assertFalse(diagnostics["summary"]["ok"])
        self.assertEqual(len(diagnostics["checks"]), 3)

    def test_build_telegram_checks_uses_running_service_snapshot(self):
        sandbox = _make_test_dir("controller-telegram-checks")
        previous = Path.cwd()
        try:
            os.chdir(sandbox)
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
            shutil.rmtree(sandbox, ignore_errors=True)

        self.assertEqual(len(checks), 2)
        self.assertTrue(checks[0]["ok"])
        self.assertEqual(checks[0]["detail"], "Sessione Telegram gia' in uso dal relay attivo.")
        self.assertTrue(checks[1]["ok"])
        self.assertEqual(checks[1]["detail"], "Source Chat risolto correttamente: Test Channel.")

    def test_coerce_config_strips_invisible_unicode_from_mt5_login(self):
        sandbox = _make_test_dir("controller-login")
        previous = Path.cwd()
        try:
            os.chdir(sandbox)
            controller = BotController()
            config = controller._coerce_config({"mt5": {"login": "7003005\u200e"}})
        finally:
            os.chdir(previous)
            shutil.rmtree(sandbox, ignore_errors=True)

        self.assertEqual(config.mt5.login, "7003005")

    def test_request_telegram_code_stops_running_service_until_auth_completes(self):
        sandbox = _make_test_dir("controller-send-code")
        previous = Path.cwd()
        try:
            os.chdir(sandbox)
            controller = BotController()
            stop_calls: list[str] = []

            class DummyService:
                is_running = True

                def stop(self):
                    stop_calls.append("stopped")

            controller._service = DummyService()
            controller._auth = SimpleNamespace(
                request_code=lambda _config: {
                    "status": "code_sent",
                    "message": "Codice Telegram richiesto. Inseriscilo nel form di autorizzazione.",
                }
            )

            result = controller.request_telegram_code()
        finally:
            os.chdir(previous)
            shutil.rmtree(sandbox, ignore_errors=True)

        self.assertEqual(result["status"], "code_sent")
        self.assertEqual(stop_calls, ["stopped"])
        self.assertFalse(controller.is_running)
        self.assertTrue(controller._resume_service_after_telegram_auth)

    def test_start_telegram_qr_login_restarts_service_if_already_authorized(self):
        sandbox = _make_test_dir("controller-qr-start")
        previous = Path.cwd()
        try:
            os.chdir(sandbox)
            controller = BotController()
            stop_calls: list[str] = []
            restart_logs: list[str | None] = []

            class DummyService:
                is_running = True

                def stop(self):
                    stop_calls.append("stopped")

            def fake_start_locked(self, log_message=None):
                restart_logs.append(log_message)
                self._service = SimpleNamespace(is_running=True)

            controller._service = DummyService()
            controller._start_locked = MethodType(fake_start_locked, controller)
            controller._auth = SimpleNamespace(
                start_qr_login=lambda _config: {
                    "status": "already_authorized",
                    "message": "Sessione Telegram gia' autorizzata.",
                    "url": "",
                    "qr_svg_data_uri": "",
                    "expires_at": "",
                }
            )

            result = controller.start_telegram_qr_login()
        finally:
            os.chdir(previous)
            shutil.rmtree(sandbox, ignore_errors=True)

        self.assertEqual(result["status"], "already_authorized")
        self.assertEqual(stop_calls, ["stopped"])
        self.assertTrue(controller.is_running)
        self.assertEqual(restart_logs, ["Servizio riavviato: sessione Telegram gia' autorizzata."])
        self.assertFalse(controller._resume_service_after_telegram_auth)

    def test_telegram_qr_login_status_restarts_service_after_authorization(self):
        sandbox = _make_test_dir("controller-qr-status")
        previous = Path.cwd()
        try:
            os.chdir(sandbox)
            controller = BotController()
            restart_logs: list[str | None] = []

            def fake_start_locked(self, log_message=None):
                restart_logs.append(log_message)
                self._service = SimpleNamespace(is_running=True)

            controller._start_locked = MethodType(fake_start_locked, controller)
            controller._resume_service_after_telegram_auth = True
            controller._auth = SimpleNamespace(
                qr_login_status=lambda _config: {
                    "status": "authorized",
                    "message": "Sessione Telegram autorizzata correttamente tramite QR code.",
                    "url": "",
                    "qr_svg_data_uri": "",
                    "expires_at": "",
                }
            )

            result = controller.telegram_qr_login_status()
        finally:
            os.chdir(previous)
            shutil.rmtree(sandbox, ignore_errors=True)

        self.assertEqual(result["status"], "authorized")
        self.assertTrue(controller.is_running)
        self.assertEqual(restart_logs, ["Servizio riavviato dopo l'autorizzazione Telegram via QR."])
        self.assertFalse(controller._resume_service_after_telegram_auth)


if __name__ == "__main__":
    unittest.main()
