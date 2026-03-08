import unittest

from telegram_mt5_bot.config import TelegramBotSettings
from telegram_mt5_bot.control_bot import BotUserIdentity, TelegramControlBot


class DummyController:
    def get_status_payload(self):
        return {}

    def start_bot(self):
        return {}

    def stop_bot(self):
        return {}

    def list_signals(self):
        return []

    def run_full_diagnostics(self):
        return {"summary": {"message": "ok"}, "checks": []}

    def list_logs(self):
        return []


class ControlBotTests(unittest.TestCase):
    def test_bot_settings_parse_allowed_users(self):
        settings = TelegramBotSettings(
            allowed_user_ids_text="123\n456\n# comment",
            allowed_usernames_text="@Mario\nluca\n# comment",
        )
        self.assertEqual(settings.allowed_user_ids(), {123, 456})
        self.assertEqual(settings.allowed_usernames(), {"mario", "luca"})

    def test_authorization_accepts_id_or_username(self):
        config = type(
            "Config",
            (),
            {
                "telegram_bot": TelegramBotSettings(
                    allowed_user_ids_text="111",
                    allowed_usernames_text="trusted_user",
                ),
                "telegram": type("Telegram", (), {"api_id": "1", "api_hash": "hash"})(),
            },
        )()
        bot = TelegramControlBot(config, DummyController(), lambda *_: None)

        self.assertTrue(bot._is_authorized(BotUserIdentity(user_id=111, username=None, is_private=True)))
        self.assertTrue(bot._is_authorized(BotUserIdentity(user_id=222, username="trusted_user", is_private=True)))
        self.assertFalse(bot._is_authorized(BotUserIdentity(user_id=222, username="other", is_private=True)))
        self.assertFalse(bot._is_authorized(BotUserIdentity(user_id=111, username=None, is_private=False)))


if __name__ == "__main__":
    unittest.main()
