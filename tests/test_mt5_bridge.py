import unittest

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


if __name__ == "__main__":
    unittest.main()
