from __future__ import annotations

import threading
from pathlib import Path

from telegram_mt5_bot.config import DEFAULT_STATE_PATH, JsonFileStore
from telegram_mt5_bot.models import ActiveSignalState, utc_now_iso


class SignalStateStore:
    def __init__(self, path: Path | str = DEFAULT_STATE_PATH):
        self._store = JsonFileStore(path)
        self._lock = threading.Lock()
        self._signals: dict[str, ActiveSignalState] = {}
        self._load()

    def _load(self) -> None:
        payload = self._store.read()
        signals = payload.get("signals", [])
        self._signals = {
            str(item["signal_id"]): ActiveSignalState.from_dict(item)
            for item in signals
        }

    def _save(self) -> None:
        self._store.write({"signals": [signal.to_dict() for signal in self._signals.values()]})

    def upsert(self, signal: ActiveSignalState) -> None:
        with self._lock:
            signal.last_update_at = utc_now_iso()
            self._signals[signal.signal_id] = signal
            self._save()

    def list_active(self) -> list[ActiveSignalState]:
        with self._lock:
            return [signal for signal in self._signals.values() if signal.status in {"open", "partial", "pending"}]

    def find_active_by_symbol(self, symbol: str) -> list[ActiveSignalState]:
        with self._lock:
            candidates = [signal for signal in self._signals.values() if signal.status in {"open", "partial", "pending"}]
            return [signal for signal in candidates if signal.symbol.upper() == symbol.upper()]

    def find_active_by_group(self, group_id: str) -> list[ActiveSignalState]:
        with self._lock:
            candidates = [signal for signal in self._signals.values() if signal.status in {"open", "partial", "pending"}]
            return [signal for signal in candidates if signal.group_id == group_id]

    def find_latest_active(self, symbol: str | None = None) -> ActiveSignalState | None:
        with self._lock:
            candidates = [signal for signal in self._signals.values() if signal.status in {"open", "partial", "pending"}]
            if symbol:
                candidates = [signal for signal in candidates if signal.symbol.upper() == symbol.upper()]
            if not candidates:
                return None
            return max(candidates, key=lambda signal: (signal.opened_at, signal.source_message_id))

    def mark_closed(self, signal_id: str, reason: str) -> ActiveSignalState | None:
        with self._lock:
            signal = self._signals.get(signal_id)
            if not signal:
                return None
            signal.status = "closed"
            signal.closed_reason = reason
            signal.remaining_volume_estimate = 0.0
            signal.last_update_at = utc_now_iso()
            self._save()
            return signal

    def get(self, signal_id: str) -> ActiveSignalState | None:
        with self._lock:
            return self._signals.get(signal_id)

    def touch_partial(self, signal_id: str, remaining_volume_estimate: float) -> ActiveSignalState | None:
        with self._lock:
            signal = self._signals.get(signal_id)
            if not signal:
                return None
            signal.status = "partial" if remaining_volume_estimate > 0 else "closed"
            signal.remaining_volume_estimate = max(0.0, remaining_volume_estimate)
            if remaining_volume_estimate <= 0:
                signal.closed_reason = signal.closed_reason or "position_closed"
            signal.last_update_at = utc_now_iso()
            self._save()
            return signal

    def all_signals(self) -> list[ActiveSignalState]:
        with self._lock:
            return list(self._signals.values())
