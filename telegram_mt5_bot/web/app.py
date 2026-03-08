from __future__ import annotations

from pathlib import Path

from telegram_mt5_bot.web.controller import BotController


def create_app():
    try:
        from flask import Flask, jsonify, render_template, request
        from werkzeug.exceptions import HTTPException
    except Exception as exc:  # pragma: no cover - depends on local environment
        raise RuntimeError("Flask non disponibile. Installa il pacchetto 'Flask' nel virtualenv.") from exc

    root_dir = Path(__file__).resolve().parent
    app = Flask(
        __name__,
        template_folder=str(root_dir / "templates"),
        static_folder=str(root_dir / "static"),
    )
    controller = BotController()

    @app.get("/")
    def index():
        bootstrap = controller.dashboard_bootstrap()
        return render_template("dashboard.html", bootstrap=bootstrap)

    @app.get("/api/config")
    def get_config():
        return jsonify({"config": controller.get_config_payload()})

    @app.post("/api/config")
    def save_config():
        payload = request.get_json(silent=True) or {}
        config = controller.save_config_payload(payload.get("config", payload))
        return jsonify({"ok": True, "config": config, "status": controller.get_status_payload()})

    @app.get("/api/status")
    def get_status():
        return jsonify({"status": controller.get_status_payload()})

    @app.get("/api/logs")
    def get_logs():
        after_id = int(request.args.get("after", "0"))
        return jsonify({"logs": controller.list_logs(after_id)})

    @app.get("/api/signals")
    def get_signals():
        return jsonify({"signals": controller.list_signals()})

    @app.post("/api/bot/start")
    def start_bot():
        status = controller.start_bot()
        return jsonify({"ok": True, "status": status})

    @app.post("/api/bot/stop")
    def stop_bot():
        status = controller.stop_bot()
        return jsonify({"ok": True, "status": status})

    @app.post("/api/control-bot/start")
    def start_control_bot():
        status = controller.start_control_bot()
        return jsonify({"ok": True, "status": status})

    @app.post("/api/control-bot/stop")
    def stop_control_bot():
        status = controller.stop_control_bot()
        return jsonify({"ok": True, "status": status})

    @app.post("/api/mt5/test")
    def test_mt5():
        detail = controller.test_mt5()
        return jsonify({"ok": True, "detail": detail, "status": controller.get_status_payload()})

    @app.post("/api/checks/telegram")
    def check_telegram():
        diagnostics = controller.run_telegram_diagnostics()
        return jsonify({"ok": True, "diagnostics": diagnostics, "status": controller.get_status_payload()})

    @app.post("/api/checks/mt5")
    def check_mt5():
        diagnostics = controller.run_mt5_diagnostics()
        return jsonify({"ok": True, "diagnostics": diagnostics, "status": controller.get_status_payload()})

    @app.post("/api/checks/all")
    def check_all():
        diagnostics = controller.run_full_diagnostics()
        return jsonify({"ok": True, "diagnostics": diagnostics, "status": controller.get_status_payload()})

    @app.post("/api/telegram/send-code")
    def send_code():
        result = controller.request_telegram_code()
        return jsonify({"ok": True, **result, "status": controller.get_status_payload()})

    @app.post("/api/telegram/authorize")
    def authorize():
        payload = request.get_json(silent=True) or {}
        result = controller.complete_telegram_auth(
            code=str(payload.get("code", "")),
            password=str(payload.get("password", "")),
        )
        return jsonify({"ok": True, **result, "status": controller.get_status_payload()})

    @app.errorhandler(Exception)
    def handle_exception(exc):
        if isinstance(exc, HTTPException):
            return exc
        return jsonify({"ok": False, "error": str(exc)}), 400

    return app
