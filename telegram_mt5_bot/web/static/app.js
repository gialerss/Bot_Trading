const bootstrapNode = document.getElementById("bootstrap-data");
const bootstrap = bootstrapNode ? JSON.parse(bootstrapNode.textContent || "{}") : {};

const appState = {
  bootstrap,
  logCursor: bootstrap.log_cursor || 0,
  pollingError: false,
};

const endpoints = {
  saveConfig: "/api/config",
  startBot: "/api/bot/start",
  stopBot: "/api/bot/stop",
  startControlBot: "/api/control-bot/start",
  stopControlBot: "/api/control-bot/stop",
  testMt5: "/api/mt5/test",
  mt5Check: "/api/checks/mt5",
  telegramCheck: "/api/checks/telegram",
  fullCheck: "/api/checks/all",
  sendCode: "/api/telegram/send-code",
  completeAuth: "/api/telegram/authorize",
  status: "/api/status",
  logs: "/api/logs",
  signals: "/api/signals",
};

const fields = Array.from(document.querySelectorAll("[data-path]"));
const signalBoard = document.getElementById("signal-board");
const signalTemplate = document.getElementById("signal-template");
const logConsole = document.getElementById("log-console");
const diagnosticBoard = document.getElementById("diagnostic-board");
const authDialog = document.getElementById("auth-dialog");
const toastStack = document.getElementById("toast-stack");

init();

function init() {
  populateForm(bootstrap.config || {});
  applyStatus(bootstrap.status || {});
  renderLogs(bootstrap.logs || []);
  renderSignals(bootstrap.signals || []);
  renderDiagnostics(bootstrap.diagnostics || {});
  appState.logCursor = computeLastLogId(bootstrap.logs || []);
  setStatusField("log_cursor", `cursor ${appState.logCursor}`);
  bindActions();
  startClock();
  startPolling();
}

function bindActions() {
  document.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const action = button.dataset.action;
      try {
        if (action === "open-auth") {
          authDialog.showModal();
          return;
        }
        if (action === "refresh-status") {
          await Promise.all([refreshStatus(), refreshLogs(), refreshSignals()]);
          toast("Stato aggiornato.");
          return;
        }
        if (action === "save-config") {
          await saveConfig();
          toast("Configurazione salvata.");
          return;
        }
        if (action === "start-bot") {
          await startBot();
          toast("Bot avviato.");
          return;
        }
        if (action === "stop-bot") {
          const result = await postJSON(endpoints.stopBot, {});
          mergeRuntimeResponse(result);
          await refreshLogs();
          toast("Bot fermato.");
          return;
        }
        if (action === "start-control-bot") {
          await saveConfig(false);
          const result = await postJSON(endpoints.startControlBot, {});
          mergeRuntimeResponse(result);
          toast("Bot Telegram di controllo avviato.");
          return;
        }
        if (action === "stop-control-bot") {
          const result = await postJSON(endpoints.stopControlBot, {});
          mergeRuntimeResponse(result);
          toast("Bot Telegram di controllo fermato.");
          return;
        }
        if (action === "test-mt5") {
          await saveConfig(false);
          const result = await postJSON(endpoints.mt5Check, {});
          mergeRuntimeResponse(result);
          toast(result.diagnostics?.summary?.message || "Check MT5 completato.");
          return;
        }
        if (action === "check-telegram") {
          await saveConfig(false);
          const result = await postJSON(endpoints.telegramCheck, {});
          mergeRuntimeResponse(result);
          toast(result.diagnostics?.summary?.message || "Check Telegram completato.");
          return;
        }
        if (action === "check-all") {
          await saveConfig(false);
          const result = await postJSON(endpoints.fullCheck, {});
          mergeRuntimeResponse(result);
          toast(result.diagnostics?.summary?.message || "Check completo completato.");
          return;
        }
        if (action === "send-code") {
          await saveConfig(false);
          const result = await postJSON(endpoints.sendCode, { config: collectConfig() });
          mergeRuntimeResponse(result);
          toast(result.message || "Codice Telegram inviato.");
          return;
        }
      } catch (error) {
        toast(error.message || "Operazione fallita.", true);
      }
    });
  });

  const confirmAuth = document.getElementById("confirm-auth");
  if (confirmAuth) {
    confirmAuth.addEventListener("click", async () => {
      try {
        await saveConfig(false);
        const payload = {
          config: collectConfig(),
          code: document.getElementById("auth-code").value.trim(),
          password: document.getElementById("auth-password").value,
        };
        const result = await postJSON(endpoints.completeAuth, payload);
        mergeRuntimeResponse(result);
        toast(result.message || "Sessione Telegram autorizzata.");
        authDialog.close();
        document.getElementById("auth-code").value = "";
        document.getElementById("auth-password").value = "";
        await refreshLogs();
      } catch (error) {
        toast(error.message || "Autorizzazione non riuscita.", true);
      }
    });
  }
}

function populateForm(config) {
  fields.forEach((field) => {
    const value = getNested(config, field.dataset.path);
    if (field.dataset.type === "bool") {
      field.checked = Boolean(value);
      return;
    }
    field.value = value ?? "";
  });
}

function collectConfig() {
  const config = { telegram: {}, telegram_bot: {}, mt5: {}, trading: {} };
  fields.forEach((field) => {
    const path = field.dataset.path;
    let value;
    if (field.dataset.type === "bool") {
      value = field.checked;
    } else if (field.type === "number") {
      value = field.value === "" ? "" : Number(field.value);
    } else {
      value = field.value;
    }
    setNested(config, path, value);
  });
  return config;
}

async function saveConfig(notify = true) {
  const result = await postJSON(endpoints.saveConfig, { config: collectConfig() });
  if (result.config) {
    appState.bootstrap.config = result.config;
    populateForm(result.config);
  }
  mergeRuntimeResponse(result);
  if (notify && result.message) {
    toast(result.message);
  }
  return result;
}

async function startBot() {
  await saveConfig(false);
  const result = await postJSON(endpoints.startBot, { config: collectConfig() });
  mergeRuntimeResponse(result);
  return result;
}

async function testMt5() {
  await saveConfig(false);
  const result = await postJSON(endpoints.testMt5, { config: collectConfig() });
  mergeRuntimeResponse(result);
  return result;
}

async function refreshStatus() {
  const result = await getJSON(endpoints.status);
  mergeRuntimeResponse(result);
  appState.pollingError = false;
}

async function refreshLogs() {
  const result = await getJSON(`${endpoints.logs}?after=${encodeURIComponent(appState.logCursor)}`);
  mergeRuntimeResponse(result);
}

async function refreshSignals() {
  const result = await getJSON(endpoints.signals);
  mergeRuntimeResponse(result);
}

function mergeRuntimeResponse(result) {
  if (result.status) {
    appState.bootstrap.status = { ...(appState.bootstrap.status || {}), ...result.status };
    applyStatus(appState.bootstrap.status);
  }
  if (result.signals) {
    appState.bootstrap.signals = result.signals;
    renderSignals(result.signals);
  }
  if (result.diagnostics) {
    appState.bootstrap.diagnostics = result.diagnostics;
    renderDiagnostics(result.diagnostics);
  }
  if (result.logs) {
    appendLogs(result.logs);
    appState.logCursor = Math.max(appState.logCursor, computeLastLogId(result.logs));
    setStatusField("log_cursor", `cursor ${appState.logCursor}`);
  }
}

function applyStatus(status) {
  const serviceState = boolish(status.running) ? "running" : "stopped";
  document.body.dataset.serviceState = serviceState;
  setStatusField("service_state", serviceState === "running" ? "In esecuzione" : "Fermo");
  setStatusField("status_note", buildStatusNote(status, serviceState));
  setStatusField("telegram_state", buildTelegramState(status));
  setStatusField("control_bot_state", boolish(status.control_bot_running) ? "Attivo" : "Fermo");
  const platform = getNested(appState.bootstrap.config || {}, "mt5.platform") || "mt5";
  setStatusField("mt5_state", platform === "mt4" ? "MT4 richiede bridge dedicato" : "Bridge pronto per test");
  setStatusField("active_signals_count", String(status.active_signal_count ?? appState.bootstrap.signals?.length ?? 0));
  const signalSnapshot = Number(status.active_signal_count ?? 0) > 0 ? "hot" : "flat";
  setStatusField("signal_snapshot", signalSnapshot);
}

function renderSignals(signals) {
  signalBoard.innerHTML = "";
  if (!signals.length) {
    signalBoard.innerHTML = '<div class="empty-state">Nessun segnale attivo. Quando il worker Telegram apre o aggiorna posizioni, il board mostra simbolo, lato, entry, SL e volume residuo.</div>';
    return;
  }

  signals.forEach((signal) => {
    const fragment = signalTemplate.content.cloneNode(true);
    fragment.querySelector(".signal-symbol").textContent = signal.symbol || signal.broker_symbol || "--";
    const side = String(signal.side || "").toLowerCase();
    const sideNode = fragment.querySelector(".signal-side");
    sideNode.textContent = signal.side || "--";
    if (side === "buy") {
      sideNode.classList.add("buy");
    } else if (side === "sell") {
      sideNode.classList.add("sell");
    } else {
      sideNode.classList.add("neutral");
    }
    fragment.querySelector(".signal-entry").textContent = formatMaybeNumber(signal.entry);
    fragment.querySelector(".signal-sl").textContent = formatMaybeNumber(signal.sl);
    fragment.querySelector(".signal-status").textContent = signal.status || "--";
    fragment.querySelector(".signal-volume").textContent = formatMaybeNumber(signal.remaining_volume_estimate);
    signalBoard.appendChild(fragment);
  });
}

function renderDiagnostics(diagnostics) {
  if (!diagnosticBoard) return;
  const checks = Array.isArray(diagnostics?.checks) ? diagnostics.checks : [];
  const total = Number(diagnostics?.summary?.total || 0);
  const passed = Number(diagnostics?.summary?.passed || 0);
  const summaryLabel = total > 0 ? `${passed}/${total} ok` : "nessun check";
  setStatusField("diagnostic_summary", summaryLabel);
  diagnosticBoard.innerHTML = "";

  if (!checks.length) {
    diagnosticBoard.innerHTML = '<div class="empty-state">Nessun check eseguito. Usa i pulsanti rapidi per verificare Telegram, MT5 o l\'intera configurazione.</div>';
    return;
  }

  checks.forEach((check) => {
    const node = document.createElement("article");
    const stateClass = check.ok ? "ok" : "error";
    node.className = `diagnostic-card ${stateClass}`;
    node.innerHTML = `
      <div class="diagnostic-head">
        <strong>${escapeHtml(check.label || "Check")}</strong>
        <span class="diagnostic-state ${stateClass}">${check.ok ? "OK" : "Errore"}</span>
      </div>
      <p>${escapeHtml(check.detail || "Nessun dettaglio disponibile.")}</p>
    `;
    diagnosticBoard.appendChild(node);
  });
}

function renderLogs(logs) {
  logConsole.innerHTML = "";
  appendLogs(logs);
}

function appendLogs(logs) {
  if (!Array.isArray(logs) || !logs.length) {
    if (!logConsole.children.length) {
      logConsole.innerHTML = '<div class="empty-state">Nessun log disponibile. I nuovi eventi del listener, del parser e del bridge MT5 appariranno qui.</div>';
    }
    return;
  }

  if (logConsole.querySelector(".empty-state")) {
    logConsole.innerHTML = "";
  }

  logs.forEach((entry) => {
    const wrapper = document.createElement("div");
    wrapper.className = "log-line";
    const timestamp = typeof entry === "object" && entry !== null ? (entry.timestamp || entry.time || nowStamp()) : nowStamp();
    const message = typeof entry === "object" && entry !== null ? (entry.message || JSON.stringify(entry)) : String(entry);
    const level = typeof entry === "object" && entry !== null ? String(entry.level || "info").toLowerCase() : "info";
    wrapper.dataset.level = level;
    wrapper.innerHTML = `<span class="log-time">${escapeHtml(timestamp)}</span><span>${escapeHtml(message)}</span>`;
    logConsole.appendChild(wrapper);
  });
  logConsole.scrollTop = logConsole.scrollHeight;
}

function startClock() {
  const clock = document.getElementById("live-clock");
  if (!clock) return;
  const formatter = new Intl.DateTimeFormat("it-IT", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "Europe/Rome",
  });
  const tick = () => {
    clock.textContent = formatter.format(new Date());
  };
  tick();
  window.setInterval(tick, 1000);
}

function startPolling() {
  window.setInterval(async () => {
    try {
      await Promise.all([refreshStatus(), refreshLogs(), refreshSignals()]);
    } catch (error) {
      if (!appState.pollingError) {
        toast(error.message || "Polling runtime non disponibile.", true);
      }
      appState.pollingError = true;
    }
  }, 5000);
}

function toast(message, isError = false) {
  const node = document.createElement("div");
  node.className = `toast${isError ? " error" : ""}`;
  node.textContent = message;
  toastStack.appendChild(node);
  window.setTimeout(() => {
    node.remove();
  }, 3600);
}

async function postJSON(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleResponse(response);
}

async function getJSON(url) {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  return handleResponse(response);
}

async function handleResponse(response) {
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || data.message || `HTTP ${response.status}`);
  }
  return data;
}

function setStatusField(name, value) {
  document.querySelectorAll(`[data-status-field="${name}"]`).forEach((node) => {
    node.textContent = value;
  });
}

function getNested(object, path) {
  return path.split(".").reduce((acc, key) => (acc && key in acc ? acc[key] : undefined), object);
}

function setNested(object, path, value) {
  const keys = path.split(".");
  const last = keys.pop();
  let target = object;
  keys.forEach((key) => {
    if (!(key in target)) target[key] = {};
    target = target[key];
  });
  target[last] = value;
}

function formatMaybeNumber(value) {
  if (value === null || value === undefined || value === "") return "--";
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toLocaleString("it-IT", { maximumFractionDigits: 4 }) : String(value);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function nowStamp() {
  return new Date().toLocaleTimeString("it-IT", { hour12: false });
}

function boolish(value) {
  return value === true || value === "true" || value === 1;
}

function computeLastLogId(logs) {
  if (!Array.isArray(logs) || !logs.length) return 0;
  return logs.reduce((max, entry) => {
    const current = Number(typeof entry === "object" && entry !== null ? entry.id : 0);
    return Number.isFinite(current) ? Math.max(max, current) : max;
  }, 0);
}

function buildTelegramState(status) {
  if (boolish(status.telegram_pending_code)) {
    return "Codice inviato, attendo conferma";
  }
  if (boolish(status.session_file_exists)) {
    return "Sessione locale disponibile";
  }
  return "Sessione non autorizzata";
}

function buildStatusNote(status, serviceState) {
  if (status.last_log && status.last_log.message) {
    return status.last_log.message;
  }
  return serviceState === "running" ? "Listener attivo" : "In attesa";
}
