import unittest
from types import SimpleNamespace

from telegram_mt5_bot.web.auth import _render_qr_data_uri, _sent_code_delivery_hint


class TelegramAuthTests(unittest.TestCase):
    def test_sent_code_delivery_hint_describes_app_delivery(self):
        sent_code = SimpleNamespace(type=type("SentCodeTypeApp", (), {})())
        hint = _sent_code_delivery_hint(sent_code)
        self.assertIn("dentro l'app", hint)
        self.assertIn("non via SMS", hint)

    def test_sent_code_delivery_hint_describes_sms_delivery(self):
        sent_code = SimpleNamespace(type=type("SentCodeTypeSms", (), {})())
        hint = _sent_code_delivery_hint(sent_code)
        self.assertEqual(hint, "Controlla gli SMS del numero configurato.")

    def test_render_qr_data_uri_returns_svg_data_uri(self):
        data_uri = _render_qr_data_uri("tg://login?token=test")
        self.assertTrue(data_uri.startswith("data:image/svg+xml;base64,"))


if __name__ == "__main__":
    unittest.main()
