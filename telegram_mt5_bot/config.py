from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path("config.json")
DEFAULT_STATE_PATH = Path("runtime_state.json")


@dataclass(slots=True)
class TelegramSettings:
    api_id: str = ""
    api_hash: str = ""
    session_name: str = "telegram_mt5_bot"
    phone_number: str = ""
    source_chat: str = ""

    def session_path(self) -> Path:
        path = Path(self.session_name).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if path.suffix != ".session":
            return path.with_suffix(".session")
        return path


@dataclass(slots=True)
class TelegramBotSettings:
    bot_token: str = ""
    session_name: str = "telegram_control_bot"
    allowed_user_ids_text: str = ""
    allowed_usernames_text: str = ""

    def session_path(self) -> Path:
        path = Path(self.session_name).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if path.suffix != ".session":
            return path.with_suffix(".session")
        return path

    def allowed_user_ids(self) -> set[int]:
        values: set[int] = set()
        for raw_line in self.allowed_user_ids_text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            values.add(int(line))
        return values

    def allowed_usernames(self) -> set[str]:
        values: set[str] = set()
        for raw_line in self.allowed_usernames_text.splitlines():
            line = raw_line.strip().lstrip("@")
            if not line or line.startswith("#"):
                continue
            values.add(line.casefold())
        return values


@dataclass(slots=True)
class Mt5Settings:
    platform: str = "mt5"
    terminal_path: str = ""
    login: str = ""
    password: str = ""
    server: str = ""
    portable: bool = False
    magic: int = 260326
    comment_prefix: str = "tgsignal"
    deviation_points: int = 50


@dataclass(slots=True)
class TradingSettings:
    default_volume: float = 0.01
    execution_mode: str = "auto"
    max_market_deviation_points: int = 80
    selected_tp_level: int = 1
    allow_pending_orders: bool = True
    prevent_duplicate_symbol: bool = True
    apply_final_tp_to_broker: bool = True
    tp1_close_percent: float = 50.0
    tp2_close_percent: float = 25.0
    tp3_close_percent: float = 25.0
    generic_tp_close_percent: float = 100.0
    symbol_map_text: str = ""
    allowed_symbols_text: str = ""

    def symbol_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for raw_line in self.symbol_map_text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            mapping[key.strip().upper()] = value.strip()
        return mapping

    def allowed_symbols(self) -> set[str]:
        values: set[str] = set()
        for raw_line in self.allowed_symbols_text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            values.add(line.upper())
        return values

    def effective_tp_level(self, available_count: int) -> int | None:
        if available_count <= 0:
            return None
        configured = max(1, int(self.selected_tp_level or 1))
        return min(configured, available_count)

    def selected_tp_value(self, tps: list[float]) -> tuple[int | None, float | None]:
        level = self.effective_tp_level(len(tps))
        if level is None:
            return None, None
        return level, float(tps[level - 1])


@dataclass(slots=True)
class AppConfig:
    telegram: TelegramSettings = field(default_factory=TelegramSettings)
    telegram_bot: TelegramBotSettings = field(default_factory=TelegramBotSettings)
    mt5: Mt5Settings = field(default_factory=Mt5Settings)
    trading: TradingSettings = field(default_factory=TradingSettings)

    def resolve_symbol(self, symbol: str) -> str:
        return self.trading.symbol_map().get(symbol.upper(), symbol.upper())

    def is_symbol_allowed(self, symbol: str) -> bool:
        allowed = self.trading.allowed_symbols()
        return not allowed or symbol.upper() in allowed


class ConfigStore:
    def __init__(self, path: Path | str = DEFAULT_CONFIG_PATH):
        self.path = Path(path)

    def load(self) -> AppConfig:
        if not self.path.exists():
            return AppConfig()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return AppConfig(
            telegram=TelegramSettings(**payload.get("telegram", {})),
            telegram_bot=TelegramBotSettings(**payload.get("telegram_bot", {})),
            mt5=Mt5Settings(**payload.get("mt5", {})),
            trading=TradingSettings(**payload.get("trading", {})),
        )

    def save(self, config: AppConfig) -> None:
        self.path.write_text(
            json.dumps(asdict(config), ensure_ascii=True, indent=2),
            encoding="utf-8",
        )


class JsonFileStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def write(self, payload: dict[str, Any]) -> None:
        self.path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
