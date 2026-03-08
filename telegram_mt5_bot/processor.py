from __future__ import annotations

from telegram_mt5_bot.config import AppConfig
from telegram_mt5_bot.models import ActiveSignalState, EventKind, IncomingTelegramMessage, OpenSignalEvent, TradeUpdateEvent
from telegram_mt5_bot.mt5_bridge import MT5Client
from telegram_mt5_bot.parser import parse_message
from telegram_mt5_bot.state import SignalStateStore


class SignalProcessor:
    def __init__(self, config: AppConfig, state_store: SignalStateStore, mt5_client: MT5Client, log_callback):
        self.config = config
        self.state_store = state_store
        self.mt5 = mt5_client
        self.log = log_callback

    def handle_message(self, incoming: IncomingTelegramMessage) -> None:
        event = parse_message(incoming.text)
        if event is None:
            self.log(f"Messaggio ignorato #{incoming.message_id}: nessun pattern utile.")
            return

        if isinstance(event, OpenSignalEvent):
            self._handle_open_signal(incoming, event)
            return

        self._handle_trade_update(event)

    def _handle_open_signal(self, incoming: IncomingTelegramMessage, event: OpenSignalEvent) -> None:
        if not self.config.is_symbol_allowed(event.symbol):
            self.log(f"Segnale {event.symbol} ignorato: simbolo non ammesso in configurazione.")
            return

        active_same_symbol = self.state_store.find_active_by_symbol(event.symbol)
        if active_same_symbol and self.config.trading.prevent_duplicate_symbol:
            if any(self.mt5.signal_exists(signal) for signal in active_same_symbol):
                self.log(
                    f"Segnale {event.symbol} ignorato: esiste gia' una posizione attiva/pending per questo simbolo."
                )
                return
            for stale_signal in active_same_symbol:
                stale_signal.status = "closed"
                stale_signal.remaining_volume_estimate = 0.0
                stale_signal.closed_reason = "not_found_on_mt5"
                self.state_store.upsert(stale_signal)

        group_id = f"{incoming.chat_id}-{incoming.message_id}"
        broker_symbol = self.config.resolve_symbol(event.symbol)
        placements: list[tuple[int, ActiveSignalState]] = []

        for level, tp_value in enumerate(event.tps, start=1):
            signal_id = f"{group_id}-tp{level}"
            placement = self.mt5.place_signal(
                signal=event,
                broker_symbol=broker_symbol,
                signal_id=signal_id,
                volume=self.config.trading.default_volume,
                broker_tp=tp_value,
            )

            state = ActiveSignalState(
                signal_id=signal_id,
                group_id=group_id,
                chat_id=incoming.chat_id,
                source_message_id=incoming.message_id,
                opened_at=incoming.timestamp,
                symbol=event.symbol,
                broker_symbol=broker_symbol,
                side=event.side.value,
                entry=event.entry,
                sl=event.sl,
                tps=event.tps,
                initial_volume=placement.requested_volume,
                remaining_volume_estimate=placement.requested_volume,
                order_ticket=placement.order_ticket,
                position_ticket=placement.position_ticket,
                order_comment=placement.order_comment,
                status="pending" if placement.is_pending else "open",
                is_pending=placement.is_pending,
                assigned_tp_level=level,
                assigned_tp_value=tp_value,
            )
            self.state_store.upsert(state)
            placements.append((level, state))

        status = "pending" if all(state.is_pending for _, state in placements) else "a mercato"
        opened_levels = ", ".join(f"TP{level}" for level, _ in placements)
        self.log(
            f"Aperto segnale {event.symbol} {event.side.value} su {broker_symbol}: create {len(placements)} operazioni ({opened_levels}), stato {status}."
        )

    def _handle_trade_update(self, event: TradeUpdateEvent) -> None:
        signal = self._resolve_target_signal(event)
        if signal is None:
            self.log(f"Aggiornamento ignorato ({event.kind.value}): nessun segnale attivo compatibile.")
            return

        targets = self._sync_active_group(signal.group_id)
        if not targets:
            self.log(f"Aggiornamento ignorato ({event.kind.value}): nessuna posizione residua trovata su MT5 per {signal.symbol}.")
            return

        if event.kind == EventKind.MOVE_SL_BREAK_EVEN:
            for target in targets:
                self.mt5.move_stop_to_break_even(target)
                target.moved_to_break_even = True
                self.state_store.upsert(target)
            self.log(f"Stop Loss spostato a break even per {signal.symbol} su {len(targets)} operazioni.")
            return

        if event.kind == EventKind.TAKE_PROFIT_LEVEL_HIT:
            if event.tp_level is None:
                self.log(f"TP senza livello per {signal.symbol}: messaggio ignorato.")
                return
            target = next((item for item in targets if item.assigned_tp_level == event.tp_level), None)
            if target is None:
                self.log(f"TP{event.tp_level} ignorato per {signal.symbol}: nessuna operazione attiva assegnata a questo livello.")
                return
            if event.tp_level in target.hit_tp_levels:
                self.log(f"TP{event.tp_level} gia' registrato per {signal.symbol}: duplicato ignorato.")
                return
            closed_volume = self.mt5.close_all(target)
            target.hit_tp_levels.append(event.tp_level)
            target.hit_tp_levels.sort()
            target.remaining_volume_estimate = 0.0
            target.status = "closed"
            target.closed_reason = f"tp{event.tp_level}"
            self.state_store.upsert(target)
            self.log(
                f"TP{event.tp_level} registrato per {signal.symbol}: volume chiuso {closed_volume:.4f}, operazione TP{event.tp_level} chiusa."
            )
            return

        if event.kind == EventKind.TAKE_PROFIT_HIT:
            closed_volume = self._close_group(targets, "generic_take_profit")
            self.log(
                f"Take Profit registrato per {signal.symbol}: volume chiuso {closed_volume:.4f}, gruppo chiuso."
            )
            return

        if event.kind == EventKind.TAKE_PROFIT_CLOSED:
            self._close_group(targets, "take_profit_closed")
            self.log(f"Operazioni residue chiuse in take profit per {signal.symbol}.")
            return

        if event.kind == EventKind.STOP_LOSS_HIT:
            self._close_group(targets, "stop_loss_hit")
            self.log(f"Operazioni chiuse/azzerate per stop loss su {signal.symbol}.")
            return

        if event.kind == EventKind.BREAK_EVEN_CLOSED:
            self._close_group(targets, "break_even_closed")
            self.log(f"Operazioni chiuse a break even per {signal.symbol}.")
            return

    def _resolve_target_signal(self, event: TradeUpdateEvent) -> ActiveSignalState | None:
        signal = self.state_store.find_latest_active(event.symbol) if event.symbol else None
        if signal is not None:
            return signal
        fallback = self.state_store.find_latest_active()
        if fallback is not None and event.symbol is None:
            self.log(
                f"Aggiornamento {event.kind.value} senza simbolo: applico l'azione all'ultimo segnale attivo {fallback.symbol}."
            )
        return fallback

    def _sync_active_group(self, group_id: str) -> list[ActiveSignalState]:
        active_targets: list[ActiveSignalState] = []
        for signal in self.state_store.find_active_by_group(group_id):
            self.mt5.sync_signal(signal)
            if not self.mt5.signal_exists(signal):
                signal.status = "closed"
                signal.remaining_volume_estimate = 0.0
                signal.closed_reason = signal.closed_reason or "not_found_on_mt5"
                self.state_store.upsert(signal)
                continue
            self.state_store.upsert(signal)
            active_targets.append(signal)
        return active_targets

    def _close_group(self, targets: list[ActiveSignalState], reason: str) -> float:
        closed_volume = 0.0
        for target in targets:
            closed_volume += self.mt5.close_all(target)
            target.remaining_volume_estimate = 0.0
            target.status = "closed"
            target.closed_reason = reason
            self.state_store.upsert(target)
        return closed_volume
