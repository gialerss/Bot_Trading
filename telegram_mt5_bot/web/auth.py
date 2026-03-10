from __future__ import annotations

import asyncio
import base64
import io
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from telegram_mt5_bot.config import AppConfig
from telegram_mt5_bot.telegram_listener import _import_telethon, _parse_api_id, _session_string, resolve_chat_entity


@dataclass(slots=True)
class PendingTelegramCode:
    phone_code_hash: str
    requested_at: float
    delivery_hint: str = ""


@dataclass(slots=True)
class PendingTelegramQr:
    status: str
    message: str
    url: str = ""
    qr_svg_data_uri: str = ""
    expires_at: float = 0.0


class TelegramAuthManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, PendingTelegramCode] = {}
        self._pending_qr: dict[str, PendingTelegramQr] = {}

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
                    delivery_hint=_sent_code_delivery_hint(sent_code),
                )
            finally:
                await client.disconnect()

        pending = asyncio.run(_request())
        if not pending.phone_code_hash:
            return {"status": "already_authorized", "message": "Sessione Telegram gia' autorizzata."}

        key = self._session_key(config)
        with self._lock:
            self._pending[key] = pending
        hint = f" {pending.delivery_hint}" if pending.delivery_hint else ""
        return {
            "status": "code_sent",
            "message": f"Codice Telegram richiesto.{hint} Inseriscilo nel form di autorizzazione.",
        }

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
                self._pending_qr[key] = PendingTelegramQr(
                    status=result["status"],
                    message=result["message"],
                )
        return result

    def start_qr_login(self, config: AppConfig) -> dict[str, str]:
        api_id = _parse_api_id(config.telegram.api_id)
        api_hash = config.telegram.api_hash.strip()
        if not api_id or not api_hash:
            raise RuntimeError("Config Telegram incompleta: servono api_id e api_hash.")

        key = self._session_key(config)
        with self._lock:
            current = self._pending_qr.get(key)
            if current and current.status in {"starting", "waiting", "password_required"}:
                return self._qr_payload(current)
            self._pending_qr[key] = PendingTelegramQr(
                status="starting",
                message="Preparazione QR code Telegram...",
            )

        ready_event = threading.Event()
        worker = threading.Thread(
            target=self._run_qr_login_worker,
            args=(config, key, ready_event),
            name="telegram-qr-login",
            daemon=True,
        )
        worker.start()
        ready_event.wait(timeout=8)
        return self.qr_login_status(config)

    def qr_login_status(self, config: AppConfig) -> dict[str, str]:
        key = self._session_key(config)
        with self._lock:
            current = self._pending_qr.get(key)
        if current is None:
            return {
                "status": "idle",
                "message": "Nessun login Telegram via QR attivo.",
                "url": "",
                "qr_svg_data_uri": "",
                "expires_at": "",
            }
        return self._qr_payload(current)

    def has_pending_code(self, config: AppConfig) -> bool:
        with self._lock:
            return self._session_key(config) in self._pending

    def _session_key(self, config: AppConfig) -> str:
        return str(config.telegram.session_path())

    def _run_qr_login_worker(self, config: AppConfig, key: str, ready_event: threading.Event) -> None:
        TelegramClient, _, SessionPasswordNeededError = _import_telethon()
        api_id = _parse_api_id(config.telegram.api_id)
        api_hash = config.telegram.api_hash.strip()

        async def _run() -> None:
            client = TelegramClient(_session_string(config), api_id, api_hash)
            await client.connect()
            try:
                if await client.is_user_authorized():
                    self._set_qr_state(
                        key,
                        PendingTelegramQr(
                            status="already_authorized",
                            message="Sessione Telegram gia' autorizzata.",
                        ),
                    )
                    return

                qr_login = await client.qr_login()
                self._set_qr_state(
                    key,
                    PendingTelegramQr(
                        status="waiting",
                        message="Scansiona il QR con Telegram da un telefono gia' loggato oppure conferma il link da Telegram Desktop.",
                        url=qr_login.url,
                        qr_svg_data_uri=_render_qr_data_uri(qr_login.url),
                        expires_at=qr_login.expires.timestamp(),
                    ),
                )
                ready_event.set()
                try:
                    await qr_login.wait()
                    self._set_qr_state(
                        key,
                        PendingTelegramQr(
                            status="authorized",
                            message="Sessione Telegram autorizzata correttamente tramite QR code.",
                        ),
                    )
                except asyncio.TimeoutError:
                    self._set_qr_state(
                        key,
                        PendingTelegramQr(
                            status="expired",
                            message="QR code Telegram scaduto. Generane uno nuovo.",
                        ),
                    )
                except SessionPasswordNeededError:
                    self._set_qr_state(
                        key,
                        PendingTelegramQr(
                            status="password_required",
                            message="QR confermato. Inserisci ora solo la password 2FA per completare il login.",
                        ),
                    )
                except Exception as exc:
                    self._set_qr_state(
                        key,
                        PendingTelegramQr(
                            status="error",
                            message=f"Login Telegram via QR fallito: {exc}",
                        ),
                    )
            finally:
                ready_event.set()
                await client.disconnect()

        try:
            asyncio.run(_run())
        except Exception as exc:
            self._set_qr_state(
                key,
                PendingTelegramQr(
                    status="error",
                    message=f"Login Telegram via QR fallito: {exc}",
                ),
            )
            ready_event.set()

    def _set_qr_state(self, key: str, state: PendingTelegramQr) -> None:
        with self._lock:
            self._pending_qr[key] = state

    def _qr_payload(self, state: PendingTelegramQr) -> dict[str, str]:
        expires_at = ""
        if state.expires_at:
            expires_at = datetime.fromtimestamp(state.expires_at, tz=timezone.utc).isoformat()
        return {
            "status": state.status,
            "message": state.message,
            "url": state.url,
            "qr_svg_data_uri": state.qr_svg_data_uri,
            "expires_at": expires_at,
        }


def _render_qr_data_uri(url: str) -> str:
    try:
        import segno
    except Exception as exc:  # pragma: no cover - depends on local environment
        raise RuntimeError("Modulo QR non disponibile. Installa la dipendenza 'segno'.") from exc

    qr = segno.make(url)
    output = io.BytesIO()
    qr.save(output, kind="svg", scale=6, border=2)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _sent_code_delivery_hint(sent_code: object) -> str:
    sent_type = type(getattr(sent_code, "type", None)).__name__
    if sent_type == "SentCodeTypeApp":
        return "Controlla l'app Telegram gia' collegata a questo numero: Telegram lo sta inviando dentro l'app, non via SMS."
    if sent_type == "SentCodeTypeSms":
        return "Controlla gli SMS del numero configurato."
    if sent_type == "SentCodeTypeCall":
        return "Telegram inviera' il codice tramite chiamata automatica."
    if sent_type == "SentCodeTypeFlashCall":
        return "Telegram usera' una flash call sul numero configurato."
    if sent_type == "SentCodeTypeMissedCall":
        return "Telegram inviera' una chiamata persa sul numero configurato."
    return "Controlla l'app Telegram o il numero configurato per il codice di accesso."
