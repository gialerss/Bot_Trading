from __future__ import annotations

from collections import deque
from dataclasses import asdict
from itertools import count
from threading import Lock
from typing import Any

from telegram_mt5_bot.config import AppConfig, ConfigStore, Mt5Settings, TelegramBotSettings, TelegramSettings, TradingSettings, strip_format_chars
from telegram_mt5_bot.control_bot import TelegramControlBot
from telegram_mt5_bot.models import utc_now_iso
from telegram_mt5_bot.service import BotService
from telegram_mt5_bot.state import SignalStateStore
from telegram_mt5_bot.web.auth import TelegramAuthManager


class LogBuffer:
    def __init__(self, max_entries: int = 500) -> None:
        self._entries: deque[dict[str, Any]] = deque(maxlen=max_entries)
        self._sequence = count(1)
        self._lock = Lock()

    def append(self, message: str, level: str = "info") -> dict[str, Any]:
        entry = {
            "id": next(self._sequence),
            "timestamp": utc_now_iso(),
            "level": level,
            "message": message,
        }
        with self._lock:
            self._entries.append(entry)
        return entry

    def since(self, after_id: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return [entry for entry in self._entries if int(entry["id"]) > int(after_id)]

    def latest(self) -> dict[str, Any] | None:
        with self._lock:
            return self._entries[-1] if self._entries else None


class BotController:
    def __init__(self) -> None:
        self._config_store = ConfigStore()
        self._config = self._config_store.load()
        self._service: BotService | None = None
        self._control_bot: TelegramControlBot | None = None
        self._auth = TelegramAuthManager()
        self._logs = LogBuffer()
        self._diagnostics = self._empty_diagnostics()
        self._lock = Lock()
        self._logs.append("Pannello web pronto.")

    def dashboard_bootstrap(self) -> dict[str, Any]:
        logs = self.list_logs()
        return {
            "config": self.get_config_payload(),
            "status": self.get_status_payload(),
            "signals": self.list_signals(),
            "logs": logs,
            "diagnostics": self.diagnostics_payload(),
            "log_cursor": max((int(entry["id"]) for entry in logs), default=0),
        }

    def get_config_payload(self) -> dict[str, Any]:
        return asdict(self._config)

    def save_config_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = self._coerce_config(payload)
        with self._lock:
            was_running = self.is_running
            control_bot_running = self.is_control_bot_running
            if was_running:
                self._stop_locked(log_message="Servizio fermato per applicare la nuova configurazione.")
            if control_bot_running:
                self._stop_control_bot_locked(log_message="Bot Telegram di controllo fermato per applicare la nuova configurazione.")
            self._config = config
            self._config_store.save(config)
            self._logs.append("Configurazione salvata su config.json.")
            if was_running:
                self._start_locked(log_message="Servizio riavviato con la nuova configurazione.")
            if control_bot_running:
                self._start_control_bot_locked(log_message="Bot Telegram di controllo riavviato con la nuova configurazione.")
        return self.get_config_payload()

    def start_bot(self) -> dict[str, Any]:
        with self._lock:
            self._start_locked()
        return self.get_status_payload()

    def stop_bot(self) -> dict[str, Any]:
        with self._lock:
            self._stop_locked()
        return self.get_status_payload()

    def start_control_bot(self) -> dict[str, Any]:
        with self._lock:
            self._start_control_bot_locked()
        return self.get_status_payload()

    def stop_control_bot(self) -> dict[str, Any]:
        with self._lock:
            self._stop_control_bot_locked()
        return self.get_status_payload()

    def test_mt5(self) -> str:
        service = BotService(self._config, self._logs.append)
        result = service.healthcheck_mt5()
        self._logs.append(f"Healthcheck {self._platform_label()} completato con successo.")
        return result

    def request_telegram_code(self) -> dict[str, str]:
        result = self._auth.request_code(self._config)
        self._logs.append(result["message"])
        return result

    def complete_telegram_auth(self, code: str, password: str = "") -> dict[str, str]:
        result = self._auth.complete_sign_in(self._config, code=code, password=password)
        self._logs.append(result["message"])
        return result

    def diagnostics_payload(self) -> dict[str, Any]:
        return self._diagnostics

    def run_telegram_diagnostics(self) -> dict[str, Any]:
        return self._store_diagnostics(self._build_telegram_checks())

    def run_mt5_diagnostics(self) -> dict[str, Any]:
        return self._store_diagnostics([self._build_mt5_check()])

    def run_full_diagnostics(self) -> dict[str, Any]:
        checks = [*self._build_telegram_checks(), self._build_mt5_check()]
        return self._store_diagnostics(checks)

    def get_status_payload(self) -> dict[str, Any]:
        latest_log = self._logs.latest()
        return {
            "running": self.is_running,
            "session_path": str(self._config.telegram.session_path()),
            "session_file_exists": self._config.telegram.session_path().exists(),
            "telegram_pending_code": self._auth.has_pending_code(self._config),
            "config_path": str(self._config_store.path),
            "active_signal_count": len([signal for signal in self.list_signals() if signal["status"] in {"open", "partial", "pending"}]),
            "control_bot_running": self.is_control_bot_running,
            "control_bot_session_path": str(self._config.telegram_bot.session_path()),
            "last_log": latest_log,
        }

    def list_logs(self, after_id: int = 0) -> list[dict[str, Any]]:
        return self._logs.since(after_id)

    def list_signals(self) -> list[dict[str, Any]]:
        store = SignalStateStore()
        signals = [signal.to_dict() for signal in store.all_signals()]
        signals.sort(key=lambda item: (item.get("opened_at", ""), item.get("source_message_id", 0)), reverse=True)
        return signals[:20]

    @property
    def is_running(self) -> bool:
        return self._service is not None and self._service.is_running

    @property
    def is_control_bot_running(self) -> bool:
        return self._control_bot is not None

    def _start_locked(self, log_message: str | None = None) -> None:
        if self._service is not None and self._service.is_running:
            raise RuntimeError("Il bot e' gia' in esecuzione.")
        self._service = BotService(self._config, self._logs.append)
        self._service.start()
        if log_message:
            self._logs.append(log_message)

    def _stop_locked(self, log_message: str | None = None) -> None:
        if self._service is None:
            return
        try:
            self._service.stop()
        finally:
            self._service = None
            if log_message:
                self._logs.append(log_message)

    def _start_control_bot_locked(self, log_message: str | None = None) -> None:
        if self._control_bot is not None:
            raise RuntimeError("Il bot Telegram di controllo e' gia' in esecuzione.")
        self._control_bot = TelegramControlBot(self._config, self, self._logs.append)
        self._control_bot.start()
        if log_message:
            self._logs.append(log_message)

    def _stop_control_bot_locked(self, log_message: str | None = None) -> None:
        if self._control_bot is None:
            return
        try:
            self._control_bot.stop()
        finally:
            self._control_bot = None
            if log_message:
                self._logs.append(log_message)

    def _build_telegram_checks(self) -> list[dict[str, Any]]:
        if self._service is not None and self._service.is_running:
            inspection = self._service.telegram_diagnostics_snapshot()
            if inspection is not None:
                return [
                    {
                        "key": "telegram_session",
                        "label": "Telegram sessione",
                        "ok": bool(inspection.get("authorized")),
                        "detail": str(inspection.get("session_message", "Controllo sessione completato.")),
                    },
                    {
                        "key": "telegram_source_chat",
                        "label": "Telegram source chat",
                        "ok": bool(inspection.get("source_chat_ok")),
                        "detail": str(inspection.get("source_chat_message", "Controllo canale completato.")),
                    },
                ]

        try:
            inspection = self._auth.inspect_session(self._config)
        except Exception as exc:
            message = str(exc)
            self._logs.append(f"Check Telegram fallito: {message}", level="error")
            return [
                {
                    "key": "telegram_session",
                    "label": "Telegram sessione",
                    "ok": False,
                    "detail": message,
                },
                {
                    "key": "telegram_source_chat",
                    "label": "Telegram source chat",
                    "ok": False,
                    "detail": "Controllo canale non completato.",
                },
            ]

        return [
            {
                "key": "telegram_session",
                "label": "Telegram sessione",
                "ok": bool(inspection.get("authorized")),
                "detail": str(inspection.get("session_message", "Controllo sessione completato.")),
            },
            {
                "key": "telegram_source_chat",
                "label": "Telegram source chat",
                "ok": bool(inspection.get("source_chat_ok")),
                "detail": str(inspection.get("source_chat_message", "Controllo canale completato.")),
            },
        ]

    def _build_mt5_check(self) -> dict[str, Any]:
        try:
            detail = self.test_mt5()
            return {
                "key": "mt5_bridge",
                "label": self._platform_label(),
                "ok": True,
                "detail": f"Connessione riuscita: {detail}",
            }
        except Exception as exc:
            message = str(exc)
            self._logs.append(f"Check MT5 fallito: {message}", level="error")
            return {
                "key": "mt5_bridge",
                "label": self._platform_label(),
                "ok": False,
                "detail": message,
            }

    def _store_diagnostics(self, checks: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(checks)
        passed = sum(1 for check in checks if check.get("ok"))
        failed = total - passed
        ok = total > 0 and failed == 0
        summary = {
            "ok": ok,
            "passed": passed,
            "failed": failed,
            "total": total,
            "message": (
                "Tutti i check sono andati a buon fine."
                if ok
                else f"{passed}/{total} check ok, {failed} da verificare."
            ),
        }
        payload = {
            "checks": checks,
            "summary": summary,
            "generated_at": utc_now_iso(),
        }
        self._diagnostics = payload
        self._logs.append(summary["message"], level="info" if ok else "warning")
        return payload

    def _empty_diagnostics(self) -> dict[str, Any]:
        return {
            "checks": [],
            "summary": {
                "ok": False,
                "passed": 0,
                "failed": 0,
                "total": 0,
                "message": "Nessun check eseguito.",
            },
            "generated_at": utc_now_iso(),
        }

    def _coerce_config(self, payload: dict[str, Any]) -> AppConfig:
        telegram_payload = payload.get("telegram", {})
        telegram_bot_payload = payload.get("telegram_bot", {})
        mt5_payload = payload.get("mt5", {})
        trading_payload = payload.get("trading", {})

        telegram_defaults = TelegramSettings()
        telegram_bot_defaults = TelegramBotSettings()
        mt5_defaults = Mt5Settings()
        trading_defaults = TradingSettings()

        return AppConfig(
            telegram=TelegramSettings(
                api_id=str(telegram_payload.get("api_id", telegram_defaults.api_id)).strip(),
                api_hash=str(telegram_payload.get("api_hash", telegram_defaults.api_hash)).strip(),
                session_name=str(telegram_payload.get("session_name", telegram_defaults.session_name)).strip() or telegram_defaults.session_name,
                phone_number=str(telegram_payload.get("phone_number", telegram_defaults.phone_number)).strip(),
                source_chat=str(telegram_payload.get("source_chat", telegram_defaults.source_chat)).strip(),
            ),
            telegram_bot=TelegramBotSettings(
                bot_token=str(telegram_bot_payload.get("bot_token", telegram_bot_defaults.bot_token)).strip(),
                session_name=str(telegram_bot_payload.get("session_name", telegram_bot_defaults.session_name)).strip()
                or telegram_bot_defaults.session_name,
                allowed_user_ids_text=str(
                    telegram_bot_payload.get("allowed_user_ids_text", telegram_bot_defaults.allowed_user_ids_text)
                ).strip(),
                allowed_usernames_text=str(
                    telegram_bot_payload.get("allowed_usernames_text", telegram_bot_defaults.allowed_usernames_text)
                ).strip(),
            ),
            mt5=Mt5Settings(
                platform=str(mt5_payload.get("platform", mt5_defaults.platform)).strip().lower() or mt5_defaults.platform,
                terminal_path=str(mt5_payload.get("terminal_path", mt5_defaults.terminal_path)).strip(),
                login=strip_format_chars(str(mt5_payload.get("login", mt5_defaults.login))).strip(),
                password=str(mt5_payload.get("password", mt5_defaults.password)),
                server=str(mt5_payload.get("server", mt5_defaults.server)).strip(),
                portable=self._as_bool(mt5_payload.get("portable", mt5_defaults.portable)),
                magic=self._as_int(mt5_payload.get("magic", mt5_defaults.magic), mt5_defaults.magic),
                comment_prefix=str(mt5_payload.get("comment_prefix", mt5_defaults.comment_prefix)).strip() or mt5_defaults.comment_prefix,
                deviation_points=self._as_int(mt5_payload.get("deviation_points", mt5_defaults.deviation_points), mt5_defaults.deviation_points),
            ),
            trading=TradingSettings(
                default_volume=self._as_float(trading_payload.get("default_volume", trading_defaults.default_volume), trading_defaults.default_volume),
                execution_mode=str(trading_payload.get("execution_mode", trading_defaults.execution_mode)).strip() or trading_defaults.execution_mode,
                max_market_deviation_points=self._as_int(
                    trading_payload.get("max_market_deviation_points", trading_defaults.max_market_deviation_points),
                    trading_defaults.max_market_deviation_points,
                ),
                selected_tp_level=self._as_int(
                    trading_payload.get("selected_tp_level", trading_defaults.selected_tp_level),
                    trading_defaults.selected_tp_level,
                ),
                allow_pending_orders=self._as_bool(trading_payload.get("allow_pending_orders", trading_defaults.allow_pending_orders)),
                prevent_duplicate_symbol=self._as_bool(trading_payload.get("prevent_duplicate_symbol", trading_defaults.prevent_duplicate_symbol)),
                apply_final_tp_to_broker=self._as_bool(trading_payload.get("apply_final_tp_to_broker", trading_defaults.apply_final_tp_to_broker)),
                tp1_close_percent=self._as_float(trading_payload.get("tp1_close_percent", trading_defaults.tp1_close_percent), trading_defaults.tp1_close_percent),
                tp2_close_percent=self._as_float(trading_payload.get("tp2_close_percent", trading_defaults.tp2_close_percent), trading_defaults.tp2_close_percent),
                tp3_close_percent=self._as_float(trading_payload.get("tp3_close_percent", trading_defaults.tp3_close_percent), trading_defaults.tp3_close_percent),
                generic_tp_close_percent=self._as_float(
                    trading_payload.get("generic_tp_close_percent", trading_defaults.generic_tp_close_percent),
                    trading_defaults.generic_tp_close_percent,
                ),
                symbol_map_text=str(trading_payload.get("symbol_map_text", trading_defaults.symbol_map_text)).strip(),
                allowed_symbols_text=str(trading_payload.get("allowed_symbols_text", trading_defaults.allowed_symbols_text)).strip(),
            ),
        )

    def _as_int(self, value: Any, default: int) -> int:
        if value in (None, ""):
            return default
        if isinstance(value, str):
            value = strip_format_chars(value).strip()
        return int(value)

    def _as_float(self, value: Any, default: float) -> float:
        if value in (None, ""):
            return default
        if isinstance(value, str):
            value = strip_format_chars(value).strip()
        return float(value)

    def _as_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _platform_label(self) -> str:
        platform = (self._config.mt5.platform or "mt5").strip().lower()
        if platform == "mt4":
            return "MetaTrader 4"
        return "MetaTrader 5"
