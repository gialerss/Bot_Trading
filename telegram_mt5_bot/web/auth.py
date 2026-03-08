from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass

from telegram_mt5_bot.config import AppConfig
from telegram_mt5_bot.telegram_listener import _import_telethon, _parse_api_id, _session_string, resolve_chat_entity


@dataclass(slots=True)
class PendingTelegramCode:
    phone_code_hash: str
    requested_at: float


class TelegramAuthManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, PendingTelegramCode] = {}

    def inspect_session(self, config: AppConfig) -> dict[str, str | bool]:
        api_id = _parse_api_id(config.telegram.api_id)
        api_hash = config.telegram.api_hash.strip()
        if not api_id or not api_hash:
            raise RuntimeError("Config Telegram incompleta: servono api_id e api_hash.")

        source_chat = config.telegram.source_chat.strip()
        TelegramClient, _, _ = _import_telethon()

        async def _inspect() -> dict[str, str | bool]:
            client = TelegramClient(_session_string(config), api_id, api_hash)
            await client.connect()
            try:
                if not await client.is_user_authorized():
                    return {
                        "authorized": False,
                        "session_message": "Sessione Telegram non autorizzata.",
                        "source_chat_ok": False,
                        "source_chat_message": "Source Chat non verificabile finche' la sessione non e' autorizzata.",
                    }

                if not source_chat:
                    return {
                        "authorized": True,
                        "session_message": "Sessione Telegram autorizzata.",
                        "source_chat_ok": False,
                        "source_chat_message": "Source Chat non configurato.",
                    }

                try:
                    input_entity = await resolve_chat_entity(client, source_chat)
                    entity = await client.get_entity(input_entity)
                except Exception as exc:
                    return {
                        "authorized": True,
                        "session_message": "Sessione Telegram autorizzata.",
                        "source_chat_ok": False,
                        "source_chat_message": f"Source Chat non raggiungibile: {exc}",
                    }

                title = (
                    getattr(entity, "title", None)
                    or getattr(entity, "username", None)
                    or str(source_chat)
                )
                return {
                    "authorized": True,
                    "session_message": "Sessione Telegram autorizzata.",
                    "source_chat_ok": True,
                    "source_chat_message": f"Source Chat risolto correttamente: {title}.",
                }
            finally:
                await client.disconnect()

        return asyncio.run(_inspect())

    def request_code(self, config: AppConfig) -> dict[str, str]:
        api_id = _parse_api_id(config.telegram.api_id)
        api_hash = config.telegram.api_hash.strip()
        phone_number = config.telegram.phone_number.strip()
        if not api_id or not api_hash or not phone_number:
            raise RuntimeError("Per richiedere il codice servono api_id, api_hash e phone_number.")

        TelegramClient, _, _ = _import_telethon()

        async def _request() -> PendingTelegramCode:
            client = TelegramClient(_session_string(config), api_id, api_hash)
            await client.connect()
            try:
                if await client.is_user_authorized():
                    return PendingTelegramCode(phone_code_hash="", requested_at=time.time())
                sent_code = await client.send_code_request(phone_number)
                return PendingTelegramCode(
                    phone_code_hash=str(sent_code.phone_code_hash),
                    requested_at=time.time(),
                )
            finally:
                await client.disconnect()

        pending = asyncio.run(_request())
        if not pending.phone_code_hash:
            return {"status": "already_authorized", "message": "Sessione Telegram gia' autorizzata."}

        key = self._session_key(config)
        with self._lock:
            self._pending[key] = pending
        return {"status": "code_sent", "message": "Codice Telegram inviato. Inseriscilo nel form di autorizzazione."}

    def complete_sign_in(self, config: AppConfig, code: str, password: str = "") -> dict[str, str]:
        api_id = _parse_api_id(config.telegram.api_id)
        api_hash = config.telegram.api_hash.strip()
        phone_number = config.telegram.phone_number.strip()
        if not api_id or not api_hash or not phone_number:
            raise RuntimeError("Per completare l'autorizzazione servono api_id, api_hash e phone_number.")
        code = code.strip()
        password = password.strip()
        if not code and not password:
            raise RuntimeError("Inserisci il codice Telegram o la password 2FA.")

        key = self._session_key(config)
        with self._lock:
            pending = self._pending.get(key)
        if pending is None and not password:
            raise RuntimeError("Nessun codice pending. Richiedi prima il codice Telegram.")

        TelegramClient, _, SessionPasswordNeededError = _import_telethon()

        async def _complete() -> dict[str, str]:
            client = TelegramClient(_session_string(config), api_id, api_hash)
            await client.connect()
            try:
                if await client.is_user_authorized():
                    return {"status": "already_authorized", "message": "Sessione Telegram gia' autorizzata."}
                try:
                    if code:
                        await client.sign_in(
                            phone=phone_number,
                            code=code,
                            phone_code_hash=pending.phone_code_hash if pending is not None else None,
                        )
                    if password:
                        await client.sign_in(password=password)
                except SessionPasswordNeededError:
                    if not password:
                        raise RuntimeError("Questo account richiede la password 2FA. Inseriscila e riprova.")
                    await client.sign_in(password=password)
                return {"status": "authorized", "message": "Sessione Telegram autorizzata correttamente."}
            finally:
                await client.disconnect()

        result = asyncio.run(_complete())
        if result["status"] in {"authorized", "already_authorized"}:
            with self._lock:
                self._pending.pop(key, None)
        return result

    def has_pending_code(self, config: AppConfig) -> bool:
        with self._lock:
            return self._session_key(config) in self._pending

    def _session_key(self, config: AppConfig) -> str:
        return str(config.telegram.session_path())
