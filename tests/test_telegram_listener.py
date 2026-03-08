import unittest

from telegram_mt5_bot.telegram_listener import _normalize_chat_reference


class TelegramListenerTests(unittest.TestCase):
    def test_normalize_numeric_source_chat_to_int(self):
        self.assertEqual(_normalize_chat_reference("-1002073368935"), -1002073368935)

    def test_keep_username_source_chat_as_string(self):
        self.assertEqual(_normalize_chat_reference("@sala_stark"), "@sala_stark")


if __name__ == "__main__":
    unittest.main()
