from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from telegram_mt5_bot.config import AppConfig, strip_format_chars
from telegram_mt5_bot.models import ActiveSignalState, OpenSignalEvent, TradeSide


@dataclass(slots=True)
class OrderPlacementResult:
    order_ticket: int | None
    position_ticket: int | None
    is_pending: bool
    requested_price: float
    requested_volume: float
    order_comment: str


class MT5Client:
    def __init__(self, config: AppConfig, log_callback):
        self.config = config
        self.log = log_callback
        self._mt5 = None
        self._connected = False

    def connect(self) -> None:
        if self._connected:
            return
        platform = (self.config.mt5.platform or "mt5").strip().lower()
        if platform == "mt4":
            raise RuntimeError(
                "MT4 richiede un bridge dedicato (EA MQL4 + socket/file bridge). "
                "Il progetto oggi esegue ordini reali solo con il binding ufficiale MetaTrader5."
            )
        if platform != "mt5":
            raise RuntimeError(f"Piattaforma MetaTrader non supportata: {platform}")
        mt5 = self._import_mt5()
        init_kwargs: dict[str, Any] = {}
        if self.config.mt5.terminal_path:
            init_kwargs["path"] = self.config.mt5.terminal_path
        if self.config.mt5.portable:
            init_kwargs["portable"] = True
        if self.config.mt5.login:
            sanitized_login = strip_format_chars(self.config.mt5.login).strip()
            try:
                init_kwargs["login"] = int(sanitized_login)
            except ValueError as exc:
                raise RuntimeError(f"MT5 login non valido: {self.config.mt5.login!r}") from exc
            if self.config.mt5.password:
                init_kwargs["password"] = self.config.mt5.password
            if self.config.mt5.server:
                init_kwargs["server"] = self.config.mt5.server

        if not mt5.initialize(**init_kwargs):
            raise RuntimeError(f"MT5 initialize fallita: {self._last_error(mt5)}")

        self._mt5 = mt5
        self._connected = True
        self.log("Connessione MT5 attiva.")

    def disconnect(self) -> None:
        if self._mt5 and self._connected:
            self._mt5.shutdown()
        self._connected = False
        self._mt5 = None

    def healthcheck(self) -> str:
        self.connect()
        terminal_info = self._mt5.terminal_info()
        if not terminal_info:
            raise RuntimeError(f"MT5 terminal_info non disponibile: {self._last_error(self._mt5)}")
        account_info = self._mt5.account_info()
        if not account_info:
            return f"TerminalInfo={terminal_info}"
        return f"TerminalInfo={terminal_info}; AccountInfo={account_info}"

    def place_signal(
        self,
        signal: OpenSignalEvent,
        broker_symbol: str,
        signal_id: str,
        volume: float,
        broker_tp: float | None = None,
    ) -> OrderPlacementResult:
        self.connect()
        symbol_info = self._ensure_symbol(broker_symbol)
        tick = self._mt5.symbol_info_tick(broker_symbol)
        if tick is None:
            raise RuntimeError(f"Tick non disponibile per {broker_symbol}")

        order_type, action, request_price = self._decide_execution(
            side=signal.side,
            entry=signal.entry,
            symbol_info=symbol_info,
            tick=tick,
        )
        normalized_volume = self._normalize_volume(symbol_info, volume)
        if normalized_volume <= 0:
            raise RuntimeError(f"Volume non valido dopo normalizzazione: {volume}")

        comment = self._build_comment(signal_id)
        request = {
            "action": action,
            "symbol": broker_symbol,
            "volume": normalized_volume,
            "type": order_type,
            "price": request_price,
            "sl": signal.sl,
            "magic": self.config.mt5.magic,
            "comment": comment,
            "type_time": self._mt5.ORDER_TIME_GTC,
            "type_filling": self._preferred_filling(symbol_info),
        }
        if self.config.trading.apply_final_tp_to_broker and broker_tp is not None:
            request["tp"] = float(broker_tp)

        result = self._mt5.order_send(request)
        self._ensure_trade_success(result, {self._mt5.TRADE_RETCODE_DONE, getattr(self._mt5, "TRADE_RETCODE_PLACED", None)})

        order_ticket = self._optional_int(getattr(result, "order", None))
        position_ticket = None
        is_pending = action == self._mt5.TRADE_ACTION_PENDING
        if not is_pending:
            position = self._find_matching_position(broker_symbol, comment)
            if position is not None:
                position_ticket = int(position.ticket)
            elif order_ticket is not None:
                position_ticket = order_ticket

        return OrderPlacementResult(
            order_ticket=order_ticket,
            position_ticket=position_ticket,
            is_pending=is_pending,
            requested_price=float(request_price),
            requested_volume=normalized_volume,
            order_comment=comment,
        )

    def sync_signal(self, signal: ActiveSignalState) -> ActiveSignalState:
        self.connect()
        if signal.position_ticket is not None:
            position = self._get_position(signal.position_ticket)
            if position is not None:
                signal.is_pending = False
                signal.remaining_volume_estimate = float(position.volume)
                return signal

        if signal.order_ticket is not None:
            order = self._get_order(signal.order_ticket)
            if order is not None:
                signal.is_pending = True
                return signal

        position = self._find_matching_position(signal.broker_symbol, signal.order_comment)
        if position is not None:
            signal.position_ticket = int(position.ticket)
            signal.is_pending = False
            signal.remaining_volume_estimate = float(position.volume)
            return signal

        order = self._find_matching_order(signal.broker_symbol, signal.order_comment)
        if order is not None:
            signal.order_ticket = int(order.ticket)
            signal.is_pending = True
        return signal

    def signal_exists(self, signal: ActiveSignalState) -> bool:
        self.connect()
        self.sync_signal(signal)
        if signal.is_pending:
            if signal.order_ticket is not None and self._get_order(signal.order_ticket) is not None:
                return True
            return self._find_matching_order(signal.broker_symbol, signal.order_comment) is not None
        if signal.position_ticket is not None and self._get_position(signal.position_ticket) is not None:
            return True
        return self._find_matching_position(signal.broker_symbol, signal.order_comment) is not None

    def close_volume(self, signal: ActiveSignalState, volume: float) -> float:
        self.connect()
        self.sync_signal(signal)
        if signal.is_pending:
            raise RuntimeError("La posizione e' ancora pending: non posso chiudere parzialmente.")

        position = self._resolve_position(signal)
        if position is None:
            return 0.0

        symbol_info = self._ensure_symbol(signal.broker_symbol)
        current_volume = float(position.volume)
        close_volume = min(volume, current_volume)
        close_volume = self._normalize_volume(symbol_info, close_volume, floor=True)
        if close_volume <= 0:
            if current_volume <= (symbol_info.volume_min or 0.0) + 1e-9:
                close_volume = current_volume
            else:
                return 0.0

        tick = self._mt5.symbol_info_tick(signal.broker_symbol)
        if tick is None:
            raise RuntimeError(f"Tick non disponibile per {signal.broker_symbol}")

        request = {
            "action": self._mt5.TRADE_ACTION_DEAL,
            "symbol": signal.broker_symbol,
            "position": int(position.ticket),
            "volume": close_volume,
            "type": self._mt5.ORDER_TYPE_SELL if signal.side == TradeSide.BUY.value else self._mt5.ORDER_TYPE_BUY,
            "price": float(tick.bid if signal.side == TradeSide.BUY.value else tick.ask),
            "deviation": self.config.mt5.deviation_points,
            "magic": self.config.mt5.magic,
            "comment": signal.order_comment,
            "type_time": self._mt5.ORDER_TIME_GTC,
            "type_filling": self._preferred_filling(symbol_info),
        }

        result = self._mt5.order_send(request)
        self._ensure_trade_success(result, {self._mt5.TRADE_RETCODE_DONE, getattr(self._mt5, "TRADE_RETCODE_DONE_PARTIAL", None)})

        refreshed_position = self._get_position(int(position.ticket))
        remaining = float(refreshed_position.volume) if refreshed_position is not None else 0.0
        closed = max(0.0, current_volume - remaining)
        signal.remaining_volume_estimate = remaining
        if remaining <= 0:
            signal.status = "closed"
        else:
            signal.status = "partial"
        return closed

    def close_all(self, signal: ActiveSignalState) -> float:
        self.connect()
        self.sync_signal(signal)
        if signal.is_pending and signal.order_ticket is not None:
            order = self._get_order(signal.order_ticket)
            if order is not None:
                request = {
                    "action": self._mt5.TRADE_ACTION_REMOVE,
                    "order": int(order.ticket),
                    "comment": signal.order_comment,
                }
                result = self._mt5.order_send(request)
                self._ensure_trade_success(result, {self._mt5.TRADE_RETCODE_DONE})
            signal.remaining_volume_estimate = 0.0
            signal.status = "closed"
            return 0.0

        position = self._resolve_position(signal)
        if position is None:
            signal.remaining_volume_estimate = 0.0
            signal.status = "closed"
            return 0.0

        return self.close_volume(signal, float(position.volume))

    def move_stop_to_break_even(self, signal: ActiveSignalState) -> None:
        self.connect()
        self.sync_signal(signal)
        if signal.is_pending and signal.order_ticket is not None:
            order = self._get_order(signal.order_ticket)
            if order is None:
                return
            request = {
                "action": self._mt5.TRADE_ACTION_MODIFY,
                "order": int(order.ticket),
                "price": float(order.price_open),
                "sl": signal.entry,
                "tp": float(getattr(order, "tp", 0.0) or 0.0),
                "comment": signal.order_comment,
            }
            result = self._mt5.order_send(request)
            self._ensure_trade_success(result, {self._mt5.TRADE_RETCODE_DONE})
            return

        position = self._resolve_position(signal)
        if position is None:
            return
        request = {
            "action": self._mt5.TRADE_ACTION_SLTP,
            "position": int(position.ticket),
            "symbol": signal.broker_symbol,
            "sl": signal.entry,
            "tp": float(getattr(position, "tp", 0.0) or 0.0),
        }
        result = self._mt5.order_send(request)
        self._ensure_trade_success(result, {self._mt5.TRADE_RETCODE_DONE})

    def _resolve_position(self, signal: ActiveSignalState):
        if signal.position_ticket is not None:
            position = self._get_position(signal.position_ticket)
            if position is not None:
                return position
        return self._find_matching_position(signal.broker_symbol, signal.order_comment)

    def _decide_execution(self, side: TradeSide, entry: float, symbol_info, tick) -> tuple[int, int, float]:
        market_price = float(tick.ask if side == TradeSide.BUY else tick.bid)
        point = float(symbol_info.point or 0.0) or 0.00001
        distance_points = abs(market_price - entry) / point
        mode = self.config.trading.execution_mode.lower().strip()

        if mode == "market":
            return self._market_decision(side, market_price)

        if mode == "pending":
            if not self.config.trading.allow_pending_orders:
                raise RuntimeError("La modalita' pending richiede allow_pending_orders=true")
            return self._pending_decision(side, entry, market_price)

        if distance_points <= self.config.trading.max_market_deviation_points:
            return self._market_decision(side, market_price)

        if self.config.trading.allow_pending_orders:
            return self._pending_decision(side, entry, market_price)

        return self._market_decision(side, market_price)

    def _market_decision(self, side: TradeSide, market_price: float) -> tuple[int, int, float]:
        if side == TradeSide.BUY:
            return self._mt5.ORDER_TYPE_BUY, self._mt5.TRADE_ACTION_DEAL, market_price
        return self._mt5.ORDER_TYPE_SELL, self._mt5.TRADE_ACTION_DEAL, market_price

    def _pending_decision(self, side: TradeSide, entry: float, market_price: float) -> tuple[int, int, float]:
        if side == TradeSide.BUY:
            order_type = self._mt5.ORDER_TYPE_BUY_LIMIT if entry < market_price else self._mt5.ORDER_TYPE_BUY_STOP
        else:
            order_type = self._mt5.ORDER_TYPE_SELL_LIMIT if entry > market_price else self._mt5.ORDER_TYPE_SELL_STOP
        return order_type, self._mt5.TRADE_ACTION_PENDING, entry

    def _ensure_symbol(self, symbol: str):
        info = self._mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"Simbolo MT5 non trovato: {symbol}")
        if not getattr(info, "visible", True):
            if not self._mt5.symbol_select(symbol, True):
                raise RuntimeError(f"Impossibile attivare il simbolo {symbol}")
            info = self._mt5.symbol_info(symbol)
            if info is None:
                raise RuntimeError(f"Simbolo MT5 non disponibile dopo symbol_select: {symbol}")
        return info

    def _preferred_filling(self, symbol_info) -> int:
        filling_mode = getattr(symbol_info, "filling_mode", None)
        allowed = {
            getattr(self._mt5, "ORDER_FILLING_FOK", 0),
            getattr(self._mt5, "ORDER_FILLING_IOC", 1),
            getattr(self._mt5, "ORDER_FILLING_RETURN", 2),
        }
        if filling_mode in allowed:
            return int(filling_mode)
        return getattr(self._mt5, "ORDER_FILLING_RETURN", getattr(self._mt5, "ORDER_FILLING_IOC", 1))

    def _find_matching_position(self, symbol: str, comment: str):
        positions = self._mt5.positions_get(symbol=symbol) or []
        matches = [
            position
            for position in positions
            if int(getattr(position, "magic", 0)) == int(self.config.mt5.magic)
            and str(getattr(position, "comment", "")) == comment
        ]
        if not matches:
            return None
        return max(matches, key=lambda item: getattr(item, "time_msc", getattr(item, "time", 0)))

    def _find_matching_order(self, symbol: str, comment: str):
        orders = self._mt5.orders_get(symbol=symbol) or []
        matches = [
            order
            for order in orders
            if int(getattr(order, "magic", 0)) == int(self.config.mt5.magic)
            and str(getattr(order, "comment", "")) == comment
        ]
        if not matches:
            return None
        return max(matches, key=lambda item: getattr(item, "time_setup_msc", getattr(item, "time_setup", 0)))

    def _get_position(self, ticket: int):
        positions = self._mt5.positions_get(ticket=ticket) or []
        return positions[0] if positions else None

    def _get_order(self, ticket: int):
        orders = self._mt5.orders_get(ticket=ticket) or []
        return orders[0] if orders else None

    def _normalize_volume(self, symbol_info, volume: float, floor: bool = False) -> float:
        step = float(getattr(symbol_info, "volume_step", 0.01) or 0.01)
        min_volume = float(getattr(symbol_info, "volume_min", step) or step)
        max_volume = float(getattr(symbol_info, "volume_max", volume) or volume)

        if floor:
            steps = math.floor((volume / step) + 1e-9)
        else:
            steps = round(volume / step)

        normalized = steps * step
        if volume > 0 and normalized <= 0:
            normalized = min_volume
        normalized = min(max(normalized, min_volume if volume > 0 else 0.0), max_volume)
        decimals = max(0, self._volume_decimals(step))
        return round(normalized, decimals)

    def _volume_decimals(self, step: float) -> int:
        text = f"{step:.8f}".rstrip("0")
        if "." not in text:
            return 0
        return len(text.split(".", 1)[1])

    def _build_comment(self, signal_id: str) -> str:
        prefix = (self.config.mt5.comment_prefix or "tgsignal").strip() or "tgsignal"
        short_id = signal_id[-12:]
        comment = f"{prefix}:{short_id}"
        return comment[:31]

    def _ensure_trade_success(self, result, allowed_retcodes: set[int | None]) -> None:
        if result is None:
            raise RuntimeError(f"MT5 order_send ha restituito None: {self._last_error(self._mt5)}")
        retcode = getattr(result, "retcode", None)
        allowed = {code for code in allowed_retcodes if code is not None}
        if retcode not in allowed:
            payload = result._asdict() if hasattr(result, "_asdict") else repr(result)
            raise RuntimeError(f"Operazione MT5 fallita: retcode={retcode}, dettaglio={payload}")

    def _last_error(self, mt5_module) -> str:
        error = mt5_module.last_error()
        if isinstance(error, tuple):
            return f"{error[0]} {error[1]}"
        return str(error)

    def _import_mt5(self):
        try:
            import MetaTrader5 as mt5  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on local environment
            raise RuntimeError(
                "Modulo MetaTrader5 non disponibile. Installa il pacchetto MetaTrader5 nello stesso Python del terminale MT5."
            ) from exc
        return mt5

    def _optional_int(self, value: Any) -> int | None:
        if value in (None, 0, ""):
            return None
        return int(value)
