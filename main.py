from __future__ import annotations

import os

from telegram_mt5_bot.web import create_app


if __name__ == "__main__":
    app = create_app()
    host = os.getenv("BOT_WEB_HOST", "127.0.0.1")
    port = int(os.getenv("BOT_WEB_PORT", "8765"))
    print(f"Web UI disponibile su http://{host}:{port}")
    app.run(host=host, port=port, debug=False, threaded=True)
