from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any, Callable

from telegram_mt5_bot.config import AppConfig
from telegram_mt5_bot.models import IncomingTelegramMessage


class TelegramListener:
    def __init__(self, config: AppConfig, on_message: Callable[[IncomingTelegramMessage], None], log_callback):
        self.config = config
        self.on_message = on_message
        self.log = log_callback
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client = None
        self._started_event = threading.Event()
        self._startup_error: Exception | None = None
        self._authorized = False
        self._source_chat_ok = False
        self._source_chat_label = ""

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            raise RuntimeError("Listener Telegram gia' attivo.")
        self._stop_event.clear()
        self._started_event.clear()
        self._startup_error = None
        self._authorized = False
        self._source_chat_ok = False
        self._source_chat_label = ""
        self._thread = threading.Thread(target=self._run, name="telegram-listener", daemon=True)
        self._thread.start()
        if not self._started_event.wait(timeout=15):
            raise RuntimeError("Timeout durante l'avvio del listener Telegram.")
        if self._startup_error is not None:
            raise RuntimeError(str(self._startup_error))

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
            self._startup_error = exc
            self._started_event.set()
            self.log(f"Listener Telegram fermato per errore: {exc}")
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
        if not api_id or not api_hash:
            raise RuntimeError("Config Telegram incompleta: servono api_id e api_hash.")
        source_chat = self.config.telegram.source_chat.strip()
        if not source_chat:
            raise RuntimeError("Config Telegram incompleta: manca source_chat.")

        session = _session_string(self.config)
        self._client = TelegramClient(session, api_id, api_hash)
        await self._client.connect()
        if not await self._client.is_user_authorized():
            raise RuntimeError("Sessione Telegram non autorizzata. Usa il pulsante 'Autorizza Telegram'.")
        self._authorized = True

        entity = await resolve_chat_entity(self._client, source_chat)
        entity_title = await _entity_label(self._client, entity, source_chat)
        self._source_chat_ok = True
        self._source_chat_label = entity_title
        self._started_event.set()

        @self._client.on(events.NewMessage(chats=entity))
        async def _handler(event) -> None:
            text = event.raw_text or ""
            if not text.strip():
                return
            message = IncomingTelegramMessage(
                chat_id=str(event.chat_id),
                message_id=int(event.id),
                text=text,
                timestamp=event.message.date.isoformat(),
            )
            self.on_message(message)

        self.log(f"Telegram in ascolto su {entity_title}.")
        while not self._stop_event.is_set():
            await asyncio.sleep(0.5)

        await self._client.disconnect()
        self._client = None

    def diagnostics_snapshot(self) -> dict[str, str | bool]:
        if self._startup_error is not None:
            message = str(self._startup_error)
            return {
                "authorized": False,
                "session_message": message,
                "source_chat_ok": False,
                "source_chat_message": "Controllo canale non completato.",
            }

        if not self._authorized:
            return {
                "authorized": False,
                "session_message": "Listener Telegram non ancora pronto.",
                "source_chat_ok": False,
                "source_chat_message": "Source Chat non ancora verificato.",
            }

        source_chat_message = "Source Chat risolto correttamente."
        if self._source_chat_label:
            source_chat_message = f"Source Chat risolto correttamente: {self._source_chat_label}."
        return {
            "authorized": True,
            "session_message": "Sessione Telegram gia' in uso dal relay attivo.",
            "source_chat_ok": self._source_chat_ok,
            "source_chat_message": source_chat_message if self._source_chat_ok else "Source Chat non verificato.",
        }


def authorize_session(config: AppConfig, prompt_callback, log_callback) -> None:
    TelegramClient, _, SessionPasswordNeededError = _import_telethon()
    api_id = _parse_api_id(config.telegram.api_id)
    api_hash = config.telegram.api_hash.strip()
    phone_number = config.telegram.phone_number.strip()
    if not api_id or not api_hash or not phone_number:
        raise RuntimeError("Per autorizzare Telegram servono api_id, api_hash e phone_number.")

    async def _authorize() -> None:
        session = _session_string(config)
        client = TelegramClient(session, api_id, api_hash)
        await client.connect()
        try:
            if await client.is_user_authorized():
                log_callback("Sessione Telegram gia' autorizzata.")
                return

            await client.send_code_request(phone_number)
            code = prompt_callback("Codice Telegram", "Inserisci il codice ricevuto su Telegram")
            if not code:
                raise RuntimeError("Autorizzazione annullata: codice mancante.")
            try:
                await client.sign_in(phone=phone_number, code=code.strip())
            except SessionPasswordNeededError:
                password = prompt_callback("Password 2FA", "Inserisci la password Telegram", show="*")
                if not password:
                    raise RuntimeError("Autorizzazione annullata: password 2FA mancante.")
                await client.sign_in(password=password)
            log_callback("Sessione Telegram autorizzata correttamente.")
        finally:
            await client.disconnect()

    asyncio.run(_authorize())


def _import_telethon():
    try:
        from telethon import TelegramClient, events  # type: ignore
        from telethon import errors  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on local environment
        raise RuntimeError(
            "Modulo Telethon non disponibile. Installa il pacchetto telethon per leggere il canale Telegram."
        ) from exc

    return TelegramClient, events, errors.SessionPasswordNeededError


async def resolve_chat_entity(client: Any, source_chat: str):
    reference = _normalize_chat_reference(source_chat)
    try:
        return await client.get_input_entity(reference)
    except Exception:
        if not isinstance(reference, int):
            raise

    async for dialog in client.iter_dialogs():
        if int(dialog.id) == reference:
            return await client.get_input_entity(dialog.entity)
    raise RuntimeError(f"Cannot find any entity corresponding to {source_chat!r}")


async def _entity_label(client: Any, entity: Any, source_chat: str) -> str:
    try:
        resolved = await client.get_entity(entity)
    except Exception:
        return str(source_chat)
    return (
        getattr(resolved, "title", None)
        or getattr(resolved, "username", None)
        or str(source_chat)
    )


def _parse_api_id(value: str) -> int:
    value = (value or "").strip()
    if not value:
        return 0
    return int(value)


def _normalize_chat_reference(value: str) -> str | int:
    value = (value or "").strip()
    if value and (value.isdigit() or (value.startswith("-") and value[1:].isdigit())):
        return int(value)
    return value


def _session_string(config: AppConfig) -> str:
    session_path = config.telegram.session_path()
    session_path.parent.mkdir(parents=True, exist_ok=True)
    return str(_without_double_suffix(session_path))


def _without_double_suffix(path: Path) -> Path:
    if path.suffix == ".session":
        return path.with_suffix("")
    return path
