from __future__ import annotations

import queue
import tkinter as tk
from tkinter import messagebox, scrolledtext, simpledialog, ttk

from telegram_mt5_bot.config import AppConfig, ConfigStore, Mt5Settings, TelegramSettings, TradingSettings
from telegram_mt5_bot.service import BotService
from telegram_mt5_bot.telegram_listener import authorize_session


class BotApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Telegram -> MetaTrader Bot")
        self.geometry("980x760")
        self.minsize(920, 700)

        self._config_store = ConfigStore()
        self._config = self._config_store.load()
        self._service: BotService | None = None
        self._log_queue: queue.Queue[str] = queue.Queue()

        self._build_variables()
        self._build_layout()
        self._load_config_into_form(self._config)
        self.after(250, self._flush_log_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_variables(self) -> None:
        self.api_id_var = tk.StringVar()
        self.api_hash_var = tk.StringVar()
        self.session_name_var = tk.StringVar()
        self.phone_number_var = tk.StringVar()
        self.source_chat_var = tk.StringVar()

        self.terminal_path_var = tk.StringVar()
        self.platform_var = tk.StringVar(value="mt5")
        self.login_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.server_var = tk.StringVar()
        self.portable_var = tk.BooleanVar(value=False)
        self.magic_var = tk.StringVar()
        self.comment_prefix_var = tk.StringVar()
        self.deviation_points_var = tk.StringVar()

        self.default_volume_var = tk.StringVar()
        self.execution_mode_var = tk.StringVar()
        self.max_market_deviation_var = tk.StringVar()
        self.selected_tp_level_var = tk.StringVar(value="1")
        self.allow_pending_var = tk.BooleanVar(value=True)
        self.prevent_duplicate_var = tk.BooleanVar(value=True)
        self.apply_final_tp_var = tk.BooleanVar(value=True)

        self.status_var = tk.StringVar(value="Fermo")

    def _build_layout(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)

        telegram_frame = ttk.Frame(notebook, padding=12)
        mt5_frame = ttk.Frame(notebook, padding=12)
        trading_frame = ttk.Frame(notebook, padding=12)
        logs_frame = ttk.Frame(notebook, padding=12)

        notebook.add(telegram_frame, text="Telegram")
        notebook.add(mt5_frame, text="MetaTrader")
        notebook.add(trading_frame, text="Trading")
        notebook.add(logs_frame, text="Log")

        self._build_telegram_tab(telegram_frame)
        self._build_mt5_tab(mt5_frame)
        self._build_trading_tab(trading_frame)
        self._build_logs_tab(logs_frame)

        footer = ttk.Frame(root, padding=(0, 10, 0, 0))
        footer.pack(fill="x")

        ttk.Label(footer, textvariable=self.status_var).pack(side="left")
        ttk.Button(footer, text="Salva Config", command=self._save_config).pack(side="right", padx=(8, 0))
        ttk.Button(footer, text="Stop Bot", command=self._stop_bot).pack(side="right", padx=(8, 0))
        ttk.Button(footer, text="Avvia Bot", command=self._start_bot).pack(side="right", padx=(8, 0))
        ttk.Button(footer, text="Test MetaTrader", command=self._test_mt5).pack(side="right", padx=(8, 0))
        ttk.Button(footer, text="Autorizza Telegram", command=self._authorize_telegram).pack(side="right")

    def _build_telegram_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        self._add_labeled_entry(parent, 0, "API ID", self.api_id_var)
        self._add_labeled_entry(parent, 1, "API Hash", self.api_hash_var)
        self._add_labeled_entry(parent, 2, "Session Name", self.session_name_var)
        self._add_labeled_entry(parent, 3, "Phone Number", self.phone_number_var)
        self._add_labeled_entry(parent, 4, "Source Chat", self.source_chat_var)

        hint = (
            "Source Chat accetta @username, link interno o ID numerico del canale.\n"
            "Per usare Telethon devi creare api_id/api_hash su my.telegram.org e autorizzare la sessione locale."
        )
        ttk.Label(parent, text=hint, justify="left").grid(row=5, column=0, columnspan=2, sticky="w", pady=(12, 0))

    def _build_mt5_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        ttk.Label(parent, text="Platform").grid(row=0, column=0, sticky="w", pady=4, padx=(0, 12))
        platform = ttk.Combobox(parent, textvariable=self.platform_var, values=["mt4", "mt5"], state="readonly")
        platform.grid(row=0, column=1, sticky="ew", pady=4)
        self._add_labeled_entry(parent, 1, "Terminal Path", self.terminal_path_var)
        self._add_labeled_entry(parent, 2, "Login", self.login_var)
        self._add_labeled_entry(parent, 3, "Password", self.password_var, show="*")
        self._add_labeled_entry(parent, 4, "Server", self.server_var)
        self._add_labeled_entry(parent, 5, "Magic", self.magic_var)
        self._add_labeled_entry(parent, 6, "Comment Prefix", self.comment_prefix_var)
        self._add_labeled_entry(parent, 7, "Deviation Points", self.deviation_points_var)
        ttk.Checkbutton(parent, text="Portable Mode", variable=self.portable_var).grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))

        hint = (
            "MT5 usa il binding Python ufficiale.\n"
            "Per MT4 questo progetto richiede un bridge dedicato con EA MQL4."
        )
        ttk.Label(parent, text=hint, justify="left").grid(row=9, column=0, columnspan=2, sticky="w", pady=(12, 0))

    def _build_trading_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        self._add_labeled_entry(parent, 0, "Default Volume", self.default_volume_var)

        ttk.Label(parent, text="Execution Mode").grid(row=1, column=0, sticky="w", pady=4)
        mode = ttk.Combobox(parent, textvariable=self.execution_mode_var, values=["auto", "market", "pending"], state="readonly")
        mode.grid(row=1, column=1, sticky="ew", pady=4)

        self._add_labeled_entry(parent, 2, "Max Market Deviation (points)", self.max_market_deviation_var)
        ttk.Label(parent, text="TP fallback (legacy)").grid(row=3, column=0, sticky="w", pady=4)
        tp_level = ttk.Combobox(parent, textvariable=self.selected_tp_level_var, values=["1", "2", "3"], state="readonly")
        tp_level.grid(row=3, column=1, sticky="ew", pady=4)

        ttk.Checkbutton(parent, text="Allow Pending Orders", variable=self.allow_pending_var).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Checkbutton(parent, text="Prevent Duplicate Symbol", variable=self.prevent_duplicate_var).grid(row=5, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(parent, text="Apply Each TP To Broker", variable=self.apply_final_tp_var).grid(row=6, column=0, columnspan=2, sticky="w")

        ttk.Label(parent, text="Il bot apre un'operazione per ogni TP presente; questo campo resta solo per compatibilita'.").grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )

        ttk.Label(parent, text="Symbol Map (XAUUSD=broker_symbol)").grid(row=8, column=0, sticky="nw", pady=(12, 4))
        self.symbol_map_text = tk.Text(parent, height=6, width=50)
        self.symbol_map_text.grid(row=8, column=1, sticky="nsew", pady=(12, 4))

        ttk.Label(parent, text="Allowed Symbols (uno per riga)").grid(row=9, column=0, sticky="nw", pady=(8, 4))
        self.allowed_symbols_text = tk.Text(parent, height=6, width=50)
        self.allowed_symbols_text.grid(row=9, column=1, sticky="nsew", pady=(8, 4))

        parent.rowconfigure(8, weight=1)
        parent.rowconfigure(9, weight=1)

    def _build_logs_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        self.log_text = scrolledtext.ScrolledText(parent, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")

    def _add_labeled_entry(self, parent: ttk.Frame, row: int, label: str, variable: tk.StringVar, show: str | None = None) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 12))
        entry = ttk.Entry(parent, textvariable=variable, show=show or "")
        entry.grid(row=row, column=1, sticky="ew", pady=4)

    def _load_config_into_form(self, config: AppConfig) -> None:
        self.api_id_var.set(config.telegram.api_id)
        self.api_hash_var.set(config.telegram.api_hash)
        self.session_name_var.set(config.telegram.session_name)
        self.phone_number_var.set(config.telegram.phone_number)
        self.source_chat_var.set(config.telegram.source_chat)

        self.terminal_path_var.set(config.mt5.terminal_path)
        self.platform_var.set(config.mt5.platform)
        self.login_var.set(config.mt5.login)
        self.password_var.set(config.mt5.password)
        self.server_var.set(config.mt5.server)
        self.portable_var.set(config.mt5.portable)
        self.magic_var.set(str(config.mt5.magic))
        self.comment_prefix_var.set(config.mt5.comment_prefix)
        self.deviation_points_var.set(str(config.mt5.deviation_points))

        self.default_volume_var.set(str(config.trading.default_volume))
        self.execution_mode_var.set(config.trading.execution_mode)
        self.max_market_deviation_var.set(str(config.trading.max_market_deviation_points))
        self.selected_tp_level_var.set(str(config.trading.selected_tp_level))
        self.allow_pending_var.set(config.trading.allow_pending_orders)
        self.prevent_duplicate_var.set(config.trading.prevent_duplicate_symbol)
        self.apply_final_tp_var.set(config.trading.apply_final_tp_to_broker)

        self.symbol_map_text.delete("1.0", tk.END)
        self.symbol_map_text.insert("1.0", config.trading.symbol_map_text)
        self.allowed_symbols_text.delete("1.0", tk.END)
        self.allowed_symbols_text.insert("1.0", config.trading.allowed_symbols_text)

    def _collect_config_from_form(self) -> AppConfig:
        return AppConfig(
            telegram=TelegramSettings(
                api_id=self.api_id_var.get().strip(),
                api_hash=self.api_hash_var.get().strip(),
                session_name=self.session_name_var.get().strip(),
                phone_number=self.phone_number_var.get().strip(),
                source_chat=self.source_chat_var.get().strip(),
            ),
            mt5=Mt5Settings(
                platform=self.platform_var.get().strip().lower(),
                terminal_path=self.terminal_path_var.get().strip(),
                login=self.login_var.get().strip(),
                password=self.password_var.get().strip(),
                server=self.server_var.get().strip(),
                portable=self.portable_var.get(),
                magic=int(self.magic_var.get().strip()),
                comment_prefix=self.comment_prefix_var.get().strip(),
                deviation_points=int(self.deviation_points_var.get().strip()),
            ),
            trading=TradingSettings(
                default_volume=float(self.default_volume_var.get().strip()),
                execution_mode=self.execution_mode_var.get().strip(),
                max_market_deviation_points=int(self.max_market_deviation_var.get().strip()),
                selected_tp_level=int(self.selected_tp_level_var.get().strip()),
                allow_pending_orders=self.allow_pending_var.get(),
                prevent_duplicate_symbol=self.prevent_duplicate_var.get(),
                apply_final_tp_to_broker=self.apply_final_tp_var.get(),
                symbol_map_text=self.symbol_map_text.get("1.0", tk.END).strip(),
                allowed_symbols_text=self.allowed_symbols_text.get("1.0", tk.END).strip(),
            ),
        )

    def _save_config(self) -> AppConfig | None:
        try:
            config = self._collect_config_from_form()
        except ValueError as exc:
            messagebox.showerror("Configurazione non valida", str(exc))
            return None
        self._config = config
        self._config_store.save(self._config)
        self._enqueue_log("Configurazione salvata su config.json.")
        return self._config

    def _authorize_telegram(self) -> None:
        try:
            app_config = self._collect_config_from_form()
            self._config_store.save(app_config)
            authorize_session(app_config, self._prompt_value, self._enqueue_log)
            self._config = app_config
        except Exception as exc:
            messagebox.showerror("Autorizzazione Telegram", str(exc))
            self._enqueue_log(f"Autorizzazione Telegram fallita: {exc}")

    def _test_mt5(self) -> None:
        try:
            app_config = self._collect_config_from_form()
            service = BotService(app_config, self._enqueue_log)
            info = service.healthcheck_mt5()
            self._enqueue_log(f"Healthcheck MetaTrader OK: {info}")
            messagebox.showinfo("Test MetaTrader", "Connessione MetaTrader riuscita. Controlla i log per il dettaglio.")
        except Exception as exc:
            messagebox.showerror("Test MetaTrader", str(exc))
            self._enqueue_log(f"Healthcheck MetaTrader fallito: {exc}")

    def _start_bot(self) -> None:
        if self._service is not None:
            messagebox.showinfo("Bot", "Il bot e' gia' in esecuzione.")
            return
        try:
            saved_config = self._save_config()
            if saved_config is None:
                return
            self._service = BotService(saved_config, self._enqueue_log)
            self._service.start()
            self.status_var.set("In esecuzione")
        except Exception as exc:
            self._service = None
            self.status_var.set("Errore")
            messagebox.showerror("Avvio bot", str(exc))
            self._enqueue_log(f"Avvio bot fallito: {exc}")

    def _stop_bot(self) -> None:
        if self._service is None:
            self.status_var.set("Fermo")
            return
        try:
            self._service.stop()
        finally:
            self._service = None
            self.status_var.set("Fermo")

    def _prompt_value(self, title: str, prompt: str, show: str | None = None) -> str | None:
        return simpledialog.askstring(title, prompt, parent=self, show=show)

    def _enqueue_log(self, message: str) -> None:
        self._log_queue.put(message)

    def _flush_log_queue(self) -> None:
        while True:
            try:
                message = self._log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.configure(state="normal")
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
            self.log_text.configure(state="disabled")
        self.after(250, self._flush_log_queue)

    def _on_close(self) -> None:
        if self._service is not None:
            self._service.stop()
            self._service = None
        self.destroy()
