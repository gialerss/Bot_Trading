import unittest
from types import SimpleNamespace

from telegram_mt5_bot.config import AppConfig, Mt5Settings
from telegram_mt5_bot.mt5_bridge import MT5Client


class MtBridgeTests(unittest.TestCase):
    def test_mt4_requires_dedicated_bridge(self):
        client = MT5Client(
            AppConfig(mt5=Mt5Settings(platform="mt4")),
            lambda *_: None,
        )
        with self.assertRaisesRegex(RuntimeError, "bridge dedicato"):
            client.connect()

    def test_connect_passes_sanitized_login_to_initialize(self):
        calls: dict[str, object] = {}

        class FakeMt5:
            def initialize(self, **kwargs):
                calls["initialize"] = kwargs
                return True

            def shutdown(self):
                calls["shutdown"] = True

            def last_error(self):
                return (1, "Success")

            def terminal_info(self):
                return SimpleNamespace()

        class TestClient(MT5Client):
            def _import_mt5(self):
                return FakeMt5()

        client = TestClient(
            AppConfig(mt5=Mt5Settings(login="7003005\u200e", password="pw", server="demo")),
            lambda *_: None,
        )

        client.connect()

        self.assertEqual(calls["initialize"], {"login": 7003005, "password": "pw", "server": "demo"})
        client.disconnect()

    def test_healthcheck_includes_account_info_when_available(self):
        class FakeMt5:
            def initialize(self, **kwargs):
                return True

            def shutdown(self):
                return None

            def last_error(self):
                return (1, "Success")

            def terminal_info(self):
                return SimpleNamespace(company="MetaQuotes Ltd.", name="MetaTrader 5")

            def account_info(self):
                return SimpleNamespace(login=7003005, server="KeyToMarkets-Server", company="Key To Markets")

        class TestClient(MT5Client):
            def _import_mt5(self):
                return FakeMt5()

        client = TestClient(AppConfig(mt5=Mt5Settings()), lambda *_: None)

        detail = client.healthcheck()

        self.assertIn("TerminalInfo=", detail)
        self.assertIn("AccountInfo=", detail)
        self.assertIn("KeyToMarkets-Server", detail)
        client.disconnect()


if __name__ == "__main__":
    unittest.main()
