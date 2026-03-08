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

    def test_connect_strips_invisible_unicode_from_login_before_mt5_login(self):
        calls: dict[str, object] = {}

        class FakeMt5:
            def initialize(self, **kwargs):
                calls["initialize"] = kwargs
                return True

            def login(self, **kwargs):
                calls["login"] = kwargs
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

        self.assertEqual(calls["login"], {"login": 7003005, "password": "pw", "server": "demo"})
        client.disconnect()


if __name__ == "__main__":
    unittest.main()
