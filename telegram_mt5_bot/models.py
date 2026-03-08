from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TradeSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class EventKind(str, Enum):
    OPEN = "open"
    TAKE_PROFIT_LEVEL_HIT = "take_profit_level_hit"
    TAKE_PROFIT_HIT = "take_profit_hit"
    STOP_LOSS_HIT = "stop_loss_hit"
    MOVE_SL_BREAK_EVEN = "move_sl_break_even"
    BREAK_EVEN_CLOSED = "break_even_closed"
    TAKE_PROFIT_CLOSED = "take_profit_closed"


@dataclass(slots=True)
class IncomingTelegramMessage:
    chat_id: str
    message_id: int
    text: str
    timestamp: str


@dataclass(slots=True)
class OpenSignalEvent:
    kind: EventKind
    symbol: str
    side: TradeSide
    entry: float
    sl: float
    tps: list[float]
    raw_text: str


@dataclass(slots=True)
class TradeUpdateEvent:
    kind: EventKind
    symbol: str | None
    raw_text: str
    tp_level: int | None = None


ParsedEvent = OpenSignalEvent | TradeUpdateEvent


@dataclass(slots=True)
class ActiveSignalState:
    signal_id: str
    group_id: str
    chat_id: str
    source_message_id: int
    opened_at: str
    symbol: str
    broker_symbol: str
    side: str
    entry: float
    sl: float
    tps: list[float]
    initial_volume: float
    remaining_volume_estimate: float
    order_ticket: int | None = None
    position_ticket: int | None = None
    order_comment: str = ""
    status: str = "open"
    is_pending: bool = False
    assigned_tp_level: int | None = None
    assigned_tp_value: float | None = None
    moved_to_break_even: bool = False
    hit_tp_levels: list[int] = field(default_factory=list)
    last_update_at: str = field(default_factory=lambda: utc_now_iso())
    closed_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "group_id": self.group_id,
            "chat_id": self.chat_id,
            "source_message_id": self.source_message_id,
            "opened_at": self.opened_at,
            "symbol": self.symbol,
            "broker_symbol": self.broker_symbol,
            "side": self.side,
            "entry": self.entry,
            "sl": self.sl,
            "tps": list(self.tps),
            "initial_volume": self.initial_volume,
            "remaining_volume_estimate": self.remaining_volume_estimate,
            "order_ticket": self.order_ticket,
            "position_ticket": self.position_ticket,
            "order_comment": self.order_comment,
            "status": self.status,
            "is_pending": self.is_pending,
            "assigned_tp_level": self.assigned_tp_level,
            "assigned_tp_value": self.assigned_tp_value,
            "moved_to_break_even": self.moved_to_break_even,
            "hit_tp_levels": list(self.hit_tp_levels),
            "last_update_at": self.last_update_at,
            "closed_reason": self.closed_reason,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ActiveSignalState":
        return cls(
            signal_id=str(payload["signal_id"]),
            group_id=str(payload.get("group_id", payload["signal_id"])),
            chat_id=str(payload["chat_id"]),
            source_message_id=int(payload["source_message_id"]),
            opened_at=str(payload["opened_at"]),
            symbol=str(payload["symbol"]),
            broker_symbol=str(payload.get("broker_symbol", payload["symbol"])),
            side=str(payload["side"]),
            entry=float(payload["entry"]),
            sl=float(payload["sl"]),
            tps=[float(value) for value in payload.get("tps", [])],
            initial_volume=float(payload["initial_volume"]),
            remaining_volume_estimate=float(payload.get("remaining_volume_estimate", payload["initial_volume"])),
            order_ticket=_optional_int(payload.get("order_ticket")),
            position_ticket=_optional_int(payload.get("position_ticket")),
            order_comment=str(payload.get("order_comment", "")),
            status=str(payload.get("status", "open")),
            is_pending=bool(payload.get("is_pending", False)),
            assigned_tp_level=_optional_int(payload.get("assigned_tp_level")),
            assigned_tp_value=_optional_float(payload.get("assigned_tp_value")),
            moved_to_break_even=bool(payload.get("moved_to_break_even", False)),
            hit_tp_levels=[int(value) for value in payload.get("hit_tp_levels", [])],
            last_update_at=str(payload.get("last_update_at", utc_now_iso())),
            closed_reason=payload.get("closed_reason"),
        )


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
