from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from telegram_mt5_bot.config import AppConfig
from telegram_mt5_bot.telegram_listener import _import_telethon, _parse_api_id

if TYPE_CHECKING:
    from telegram_mt5_bot.web.controller import BotController


@dataclass(slots=True)
class BotUserIdentity:
    user_id: int
    username: str | None
    is_private: bool


class TelegramControlBot:
    def __init__(self, config: AppConfig, controller: "BotController", log_callback):
        self.config = config
        self.controller = controller
        self.log = log_callback
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            raise RuntimeError("Bot Telegram di controllo gia' attivo.")
        self._validate_config()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="telegram-control-bot", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(lambda: None)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except Exception as exc:
            self.log(f"Bot Telegram di controllo fermato per errore: {exc}")
        finally:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._loop.close()
            self._loop = None

    async def _main(self) -> None:
        TelegramClient, events, _ = _import_telethon()
        api_id = _parse_api_id(self.config.telegram.api_id)
        api_hash = self.config.telegram.api_hash.strip()
        bot_token = self.config.telegram_bot.bot_token.strip()
        session = _bot_session_string(self.config)

        self._client = TelegramClient(session, api_id, api_hash)
        await self._client.start(bot_token=bot_token)
        me = await self._client.get_me()
        self.log(f"Bot Telegram di controllo attivo come @{getattr(me, 'username', 'bot')} .")

        @self._client.on(events.NewMessage(incoming=True))
        async def _handler(event) -> None:
            message = (event.raw_text or "").strip()
            if not message.startswith("/"):
                return

            sender = await event.get_sender()
            identity = BotUserIdentity(
                user_id=int(getattr(sender, "id", 0) or 0),
                username=getattr(sender, "username", None),
                is_private=bool(event.is_private),
            )
            response = self._handle_command(message, identity)
            if response:
                await event.reply(response)

        while not self._stop_event.is_set():
            await asyncio.sleep(0.5)

        await self._client.disconnect()
        self._client = None

    def _handle_command(self, message: str, identity: BotUserIdentity) -> str:
        command = message.split()[0].split("@", 1)[0].casefold()
        if command in {"/start", "/help"}:
            return self._help_message(identity, authorized=self._is_authorized(identity))

        if command == "/id":
            username = f"@{identity.username}" if identity.username else "(senza username)"
            return f"Il tuo user id e' `{identity.user_id}`\nUsername: {username}"

        if not self._is_authorized(identity):
            self.log(f"Tentativo di accesso non autorizzato al bot control da user_id={identity.user_id}.")
            return "Utente non autorizzato. Usa /id e aggiungi il tuo user id o username nella whitelist del pannello."

        try:
            if command == "/status":
                status = self.controller.get_status_payload()
                return self._format_status(status)
            if command == "/startrelay":
                status = self.controller.start_bot()
                return "Relay avviato.\n\n" + self._format_status(status)
            if command == "/stoprelay":
                status = self.controller.stop_bot()
                return "Relay fermato.\n\n" + self._format_status(status)
            if command == "/signals":
                return self._format_signals(self.controller.list_signals())
            if command == "/checks":
                diagnostics = self.controller.run_full_diagnostics()
                return self._format_diagnostics(diagnostics)
            if command == "/logs":
                return self._format_logs(self.controller.list_logs()[-8:])
        except Exception as exc:
            self.log(f"Comando bot Telegram fallito ({command}): {exc}")
            return f"Errore: {exc}"

        return self._help_message(identity, authorized=True)

    def _help_message(self, identity: BotUserIdentity, authorized: bool) -> str:
        lines = [
            "Comandi disponibili:",
            "/id - mostra user id e username",
        ]
        if authorized:
            lines.extend(
                [
                    "/status - stato generale",
                    "/startrelay - avvia il relay segnali",
                    "/stoprelay - ferma il relay segnali",
                    "/signals - ultime posizioni/segnali",
                    "/checks - esegue i check Telegram/MT5",
                    "/logs - ultimi log",
                ]
            )
        else:
            lines.append("Non sei ancora autorizzato. Inserisci il tuo user id o username nella whitelist web.")
        return "\n".join(lines)

    def _is_authorized(self, identity: BotUserIdentity) -> bool:
        if not identity.is_private:
            return False
        allowed_ids = self.config.telegram_bot.allowed_user_ids()
        allowed_usernames = self.config.telegram_bot.allowed_usernames()
        username = (identity.username or "").casefold()
        if identity.user_id in allowed_ids:
            return True
        if username and username in allowed_usernames:
            return True
        return False

    def _validate_config(self) -> None:
        api_id = _parse_api_id(self.config.telegram.api_id)
        api_hash = self.config.telegram.api_hash.strip()
        bot_token = self.config.telegram_bot.bot_token.strip()
        if not api_id or not api_hash:
            raise RuntimeError("Per il bot Telegram servono anche api_id e api_hash della sezione Telegram.")
        if not bot_token:
            raise RuntimeError("Config bot Telegram incompleta: manca il bot token.")

    def _format_status(self, status: dict[str, object]) -> str:
        service_state = "running" if status.get("running") else "stopped"
        control_state = "running" if status.get("control_bot_running") else "stopped"
        return "\n".join(
            [
                f"Relay: {service_state}",
                f"Control bot: {control_state}",
                f"Segnali attivi: {status.get('active_signal_count', 0)}",
                f"Sessione file: {'si' if status.get('session_file_exists') else 'no'}",
            ]
        )

    def _format_signals(self, signals: list[dict[str, object]]) -> str:
        if not signals:
            return "Nessun segnale registrato."
        rows = []
        for signal in signals[:8]:
            tp_label = signal.get("assigned_tp_level")
            tp_text = f" TP{tp_label}" if tp_label else ""
            rows.append(
                f"{signal.get('symbol', '--')} {signal.get('side', '--')}{tp_text} | {signal.get('status', '--')} | vol {signal.get('remaining_volume_estimate', 0)}"
            )
        return "\n".join(rows)

    def _format_diagnostics(self, diagnostics: dict[str, object]) -> str:
        summary = diagnostics.get("summary", {}) if isinstance(diagnostics, dict) else {}
        checks = diagnostics.get("checks", []) if isinstance(diagnostics, dict) else []
        lines = [str(summary.get("message", "Check completati."))]
        for check in list(checks)[:6]:
            if not isinstance(check, dict):
                continue
            mark = "OK" if check.get("ok") else "KO"
            lines.append(f"{mark} {check.get('label', 'Check')}: {check.get('detail', '')}")
        return "\n".join(lines)

    def _format_logs(self, logs: list[dict[str, object]]) -> str:
        if not logs:
            return "Nessun log disponibile."
        rows = []
        for entry in logs:
            rows.append(f"{entry.get('timestamp', '--')} | {entry.get('message', '')}")
        return "\n".join(rows[-8:])


def _bot_session_string(config: AppConfig) -> str:
    session_path = config.telegram_bot.session_path()
    session_path.parent.mkdir(parents=True, exist_ok=True)
    return str(_without_double_suffix(session_path))


def _without_double_suffix(path: Path) -> Path:
    if path.suffix == ".session":
        return path.with_suffix("")
    return path
