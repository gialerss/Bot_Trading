from __future__ import annotations

import queue
import threading
from dataclasses import dataclass

from telegram_mt5_bot.config import AppConfig
from telegram_mt5_bot.models import IncomingTelegramMessage
from telegram_mt5_bot.mt5_bridge import MT5Client
from telegram_mt5_bot.processor import SignalProcessor
from telegram_mt5_bot.state import SignalStateStore
from telegram_mt5_bot.telegram_listener import TelegramListener


@dataclass(slots=True)
class RuntimeServices:
    listener: TelegramListener
    worker: threading.Thread
    stop_event: threading.Event


class BotService:
    def __init__(self, config: AppConfig, log_callback):
        self.config = config
        self.log = log_callback
        self._queue: queue.Queue[IncomingTelegramMessage | None] = queue.Queue()
        self._runtime: RuntimeServices | None = None
        self._mt5_client: MT5Client | None = None

    def start(self) -> None:
        if self._runtime is not None:
            raise RuntimeError("Il bot e' gia' in esecuzione.")

        stop_event = threading.Event()
        state_store = SignalStateStore()
        self._mt5_client = MT5Client(self.config, self.log)
        processor = SignalProcessor(self.config, state_store, self._mt5_client, self.log)

        worker = threading.Thread(
            target=self._worker_loop,
            name="signal-worker",
            daemon=True,
            args=(processor, stop_event),
        )
        listener = TelegramListener(
            config=self.config,
            on_message=self._queue.put,
            log_callback=self.log,
        )

        worker.start()
        listener.start()
        self._runtime = RuntimeServices(listener=listener, worker=worker, stop_event=stop_event)
        self.log("Servizio bot avviato.")

    def stop(self) -> None:
        if self._runtime is None:
            return
        self._runtime.stop_event.set()
        self._runtime.listener.stop()
        self._queue.put(None)
        self._runtime.worker.join(timeout=10)
        if self._mt5_client is not None:
            self._mt5_client.disconnect()
        self._runtime = None
        self.log("Servizio bot fermato.")

    def healthcheck_mt5(self) -> str:
        if self._mt5_client is None:
            self._mt5_client = MT5Client(self.config, self.log)
        try:
            return self._mt5_client.healthcheck()
        finally:
            self._mt5_client.disconnect()

    @property
    def is_running(self) -> bool:
        return self._runtime is not None

    def _worker_loop(self, processor: SignalProcessor, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break
            try:
                processor.handle_message(item)
            except Exception as exc:
                self.log(f"Errore durante la gestione del messaggio #{item.message_id}: {exc}")
