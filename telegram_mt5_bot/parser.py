from __future__ import annotations

import re

from telegram_mt5_bot.models import EventKind, OpenSignalEvent, ParsedEvent, TradeSide, TradeUpdateEvent


_NUMBER_PATTERN = r"(-?\d+(?:[\.,]\d+)?)"
_OPEN_PATTERN = re.compile(r"^(?P<symbol>[A-Z0-9._-]{3,20})\s+(?P<side>BUY|SELL)\b", re.IGNORECASE | re.MULTILINE)
_ENTRY_PATTERN = re.compile(rf"\b(?:Entry|Price)\s*:?\s*{_NUMBER_PATTERN}", re.IGNORECASE)
_SL_PATTERN = re.compile(rf"\bSL\s*:?\s*{_NUMBER_PATTERN}", re.IGNORECASE)
_TP_PATTERN = re.compile(rf"\bTP(?P<level>\d+)\s*:?\s*(?P<value>{_NUMBER_PATTERN})", re.IGNORECASE)
_SYMBOL_ONLY_LINE = re.compile(r"^[A-Z0-9._-]{3,20}$")
_TP_LEVEL_HIT_PATTERN = re.compile(r"\b(?:take\s+profit|tp)\s*(?P<level>\d+)\b", re.IGNORECASE)
_SIDE_SYMBOL_ENTRY_PATTERN = re.compile(
    rf"\b(?P<side>BUY|SELL)\s+(?:(?P<symbol_a>[A-Z0-9._-]{{3,20}})(?:\s+NOW)?|NOW\s+(?P<symbol_b>[A-Z0-9._-]{{3,20}}))(?:\s*@?\s*(?P<entry>{_NUMBER_PATTERN}))?\b",
    re.IGNORECASE,
)


def parse_message(text: str) -> ParsedEvent | None:
    normalized = text.strip()
    if not normalized:
        return None

    open_event = _parse_open_signal(normalized)
    if open_event:
        return open_event

    lowered = normalized.casefold()
    symbol = extract_symbol_from_message(normalized)
    has_positive_marker = "preso" in lowered or "hit" in lowered or "✅" in normalized
    has_negative_marker = "missed" in lowered or ("sl hit" in lowered) or ("stop loss" in lowered and "hit" in lowered)

    if "break even" in lowered and ("chius" in lowered or "closed" in lowered):
        return TradeUpdateEvent(kind=EventKind.BREAK_EVEN_CLOSED, symbol=symbol, raw_text=normalized)

    if "stop loss" in lowered and "break even" in lowered and any(token in lowered for token in {"sposto", "spostiamo", "move"}):
        return TradeUpdateEvent(kind=EventKind.MOVE_SL_BREAK_EVEN, symbol=symbol, raw_text=normalized)

    if "stop loss" in lowered and ("preso" in lowered or "hit" in lowered):
        return TradeUpdateEvent(kind=EventKind.STOP_LOSS_HIT, symbol=symbol, raw_text=normalized)

    if (
        "chiusa in take profit" in lowered
        or "chiudiamo le operazioni" in lowered
        or "chiudiamo manualmente" in lowered
        or "close all trades" in lowered
    ):
        return TradeUpdateEvent(kind=EventKind.TAKE_PROFIT_CLOSED, symbol=symbol, raw_text=normalized)

    tp_level_match = _TP_LEVEL_HIT_PATTERN.search(normalized)
    if tp_level_match and has_positive_marker and not has_negative_marker:
        return TradeUpdateEvent(
            kind=EventKind.TAKE_PROFIT_LEVEL_HIT,
            symbol=symbol,
            raw_text=normalized,
            tp_level=int(tp_level_match.group("level")),
        )

    if ("take profit" in lowered or re.search(r"\btp\b", lowered)) and has_positive_marker and not has_negative_marker:
        return TradeUpdateEvent(kind=EventKind.TAKE_PROFIT_HIT, symbol=symbol, raw_text=normalized)

    return None


def _parse_open_signal(text: str) -> OpenSignalEvent | None:
    entry_match = _ENTRY_PATTERN.search(text)
    sl_match = _SL_PATTERN.search(text)
    tp_matches = list(_TP_PATTERN.finditer(text))
    if not sl_match or not tp_matches:
        return None
    header = _extract_open_header(text)
    if header is None:
        return None
    symbol, side, inline_entry = header
    entry = inline_entry
    if entry is None and entry_match:
        entry = _parse_float(entry_match.group(1))
    if entry is None:
        return None
    sl = _parse_float(sl_match.group(1))

    ordered_tps = sorted(
        (
            (int(match.group("level")), _parse_float(match.group("value")))
            for match in tp_matches
        ),
        key=lambda item: item[0],
    )
    tps = [value for _, value in ordered_tps]

    return OpenSignalEvent(
        kind=EventKind.OPEN,
        symbol=symbol,
        side=side,
        entry=entry,
        sl=sl,
        tps=tps,
        raw_text=text,
    )


def _extract_open_header(text: str) -> tuple[str, TradeSide, float | None] | None:
    open_match = _OPEN_PATTERN.search(text)
    if open_match:
        return (
            open_match.group("symbol").upper(),
            TradeSide(open_match.group("side").upper()),
            None,
        )

    side_match = _SIDE_SYMBOL_ENTRY_PATTERN.search(text)
    if side_match:
        symbol = side_match.group("symbol_a") or side_match.group("symbol_b")
        entry_value = side_match.group("entry")
        return (
            str(symbol).upper(),
            TradeSide(side_match.group("side").upper()),
            _parse_float(entry_value) if entry_value else None,
        )
    return None


def extract_symbol_from_message(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if _SYMBOL_ONLY_LINE.fullmatch(line):
            upper = line.upper()
            if upper not in {"BUY", "SELL", "BREAK", "EVEN"}:
                return upper

    open_match = _OPEN_PATTERN.search(text)
    if open_match:
        return open_match.group("symbol").upper()

    return None


def _parse_float(value: str) -> float:
    return float(value.replace(",", "."))
