const el = {
  loginGate: document.getElementById("login-gate"),
  loginForm: document.getElementById("login-form"),
  setupForm: document.getElementById("setup-form"),
  appShell: document.getElementById("app-shell"),
  loginUsername: document.getElementById("login-username"),
  loginPassword: document.getElementById("login-password"),
  loginSubmit: document.getElementById("login-submit"),
  setupUsername: document.getElementById("setup-username"),
  setupDisplayName: document.getElementById("setup-display-name"),
  setupPassword: document.getElementById("setup-password"),
  setupPasswordConfirm: document.getElementById("setup-password-confirm"),
  setupSubmit: document.getElementById("setup-submit"),
  loginOutput: document.getElementById("login-output"),
  changePasswordCurrent: document.getElementById("change-password-current"),
  changePasswordNew: document.getElementById("change-password-new"),
  changePasswordConfirm: document.getElementById("change-password-confirm"),
  changePasswordSubmit: document.getElementById("change-password-submit"),
  changePasswordOutput: document.getElementById("change-password-output"),
  viewerPill: document.getElementById("viewer-pill"),
  logoutButton: document.getElementById("logout-button"),
  releasePill: document.getElementById("release-pill"),
  healthPill: document.getElementById("health-pill"),
  llmPill: document.getElementById("llm-pill"),
  viewButtons: [...document.querySelectorAll("[data-view-button]")],
  viewPanels: [...document.querySelectorAll("[data-view-panel]")],
  roleSummary: document.getElementById("role-summary"),
  sessionId: document.getElementById("session-id"),
  mcpSelector: document.getElementById("mcp-selector"),
  showMcpContextInChat: document.getElementById("show-mcp-context-in-chat"),
  chatOutput: document.getElementById("chat-output"),
  chatInput: document.getElementById("chat-input"),
  sendChat: document.getElementById("send-chat"),
  clearChat: document.getElementById("clear-chat"),
  citations: document.getElementById("citations"),
  mcpDebug: document.getElementById("mcp-debug"),
  refreshHealth: document.getElementById("refresh-health"),
  mcpCards: document.getElementById("mcp-cards"),
  platformSummary: document.getElementById("platform-summary"),
  platformChecks: document.getElementById("platform-checks"),
  platformCommands: document.getElementById("platform-commands"),
  configSummary: document.getElementById("config-summary"),
  pathsList: document.getElementById("paths-list"),
  performanceSummary: document.getElementById("performance-summary"),
  performanceBreakdown: document.getElementById("performance-breakdown"),
  performanceEndpoints: document.getElementById("performance-endpoints"),
  performanceRecent: document.getElementById("performance-recent"),
  mcpId: document.getElementById("mcp-id"),
  mcpAction: document.getElementById("mcp-action"),
  mcpPayload: document.getElementById("mcp-payload"),
  runMcp: document.getElementById("run-mcp"),
  mcpOutput: document.getElementById("mcp-output"),
  reloadRuntime: document.getElementById("reload-runtime"),
  restartApp: document.getElementById("restart-app"),
  shutdownApp: document.getElementById("shutdown-app"),
  controlOutput: document.getElementById("control-output"),
  llmBaseUrl: document.getElementById("llm-base-url"),
  llmModel: document.getElementById("llm-model"),
  llmFallbackModel: document.getElementById("llm-fallback-model"),
  llmTimeoutSeconds: document.getElementById("llm-timeout-seconds"),
  llmMaxTokens: document.getElementById("llm-max-tokens"),
  probeLlm: document.getElementById("probe-llm"),
  llmProbeOutput: document.getElementById("llm-probe-output"),
  saveLlmSettings: document.getElementById("save-llm-settings"),
  runtimeJson: document.getElementById("runtime-json"),
  saveRuntime: document.getElementById("save-runtime"),
  mcpManager: document.getElementById("mcp-manager"),
  addMcpRemote: document.getElementById("add-mcp-remote"),
  saveMcpManager: document.getElementById("save-mcp-manager"),
  mcpsJson: document.getElementById("mcps-json"),
  saveMcps: document.getElementById("save-mcps"),
  guideId: document.getElementById("guide-id"),
  guideName: document.getElementById("guide-name"),
  guideDescription: document.getElementById("guide-description"),
  guideProtocol: document.getElementById("guide-protocol"),
  guideModule: document.getElementById("guide-module"),
  guideBaseUrl: document.getElementById("guide-base-url"),
  guideExecutePath: document.getElementById("guide-execute-path"),
  guideHealthPath: document.getElementById("guide-health-path"),
  guideTimeoutSeconds: document.getElementById("guide-timeout-seconds"),
  guideBearerTokenEnv: document.getElementById("guide-bearer-token-env"),
  guideWorkingDir: document.getElementById("guide-working-dir"),
  guideStartCommand: document.getElementById("guide-start-command"),
  guideStatusCommand: document.getElementById("guide-status-command"),
  guideStopCommand: document.getElementById("guide-stop-command"),
  guideValidate: document.getElementById("guide-validate"),
  guideHealth: document.getElementById("guide-health"),
  guideHandshake: document.getElementById("guide-handshake"),
  guideStatusCommandRun: document.getElementById("guide-run-status-command"),
  guideStartCommandRun: document.getElementById("guide-start-command-run"),
  guideStopCommandRun: document.getElementById("guide-stop-command-run"),
  guideAdopt: document.getElementById("guide-adopt"),
  guideChecks: document.getElementById("guide-checks"),
  guideHints: document.getElementById("guide-hints"),
  guideOutput: document.getElementById("guide-output"),
  usersJson: document.getElementById("users-json"),
  saveUsers: document.getElementById("save-users"),
  passwordResetUsername: document.getElementById("password-reset-username"),
  passwordResetNew: document.getElementById("password-reset-new"),
  passwordResetConfirm: document.getElementById("password-reset-confirm"),
  passwordResetSubmit: document.getElementById("password-reset-submit"),
  passwordResetOutput: document.getElementById("password-reset-output"),
  personaId: document.getElementById("persona-id"),
  personaContent: document.getElementById("persona-content"),
  savePersona: document.getElementById("save-persona"),
  systemPrompt: document.getElementById("system-prompt"),
  saveSystemPrompt: document.getElementById("save-system-prompt"),
  logFile: document.getElementById("log-file"),
  logLines: document.getElementById("log-lines"),
  refreshLogs: document.getElementById("refresh-logs"),
  logOutput: document.getElementById("log-output"),
};

const state = {
  config: null,
  health: null,
  performance: null,
  streamBuffer: "",
  activeView: "overview",
  logsLoaded: false,
  adminLoaded: false,
  adminLoading: null,
  session: null,
  setupRequired: false,
  mcpsConfig: { mcps: [] },
  usersConfig: { groups: [], users: [] },
  personas: [],
  guideLastDraft: null,
};

const SHOW_MCP_CONTEXT_IN_CHAT_KEY = "mono.showMcpContextInChat";

function setChat(text) {
  el.chatOutput.textContent = text;
  el.chatOutput.scrollTop = el.chatOutput.scrollHeight;
}

function appendChat(text) {
  state.streamBuffer += text;
  setChat(state.streamBuffer);
}

function resetChat() {
  state.streamBuffer = "";
  setChat("");
}

function loadUiPreferences() {
  const saved = window.localStorage.getItem(SHOW_MCP_CONTEXT_IN_CHAT_KEY);
  el.showMcpContextInChat.checked = saved === null ? true : saved === "1";
}

function persistUiPreferences() {
  window.localStorage.setItem(SHOW_MCP_CONTEXT_IN_CHAT_KEY, el.showMcpContextInChat.checked ? "1" : "0");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function normalizeMcpsConfig(config) {
  const safeConfig = config && typeof config === "object" ? config : {};
  const mcps = Array.isArray(safeConfig.mcps)
    ? safeConfig.mcps
        .filter((item) => item && typeof item === "object")
        .map((item) => {
          const clone = deepClone(item);
          delete clone.token_present;
          delete clone.bearer_token_present;
          return clone;
        })
    : [];
  return { ...safeConfig, mcps };
}

function normalizeUsersConfig(config) {
  const safeConfig = config && typeof config === "object" ? config : {};
  const groups = Array.isArray(safeConfig.groups) ? safeConfig.groups.filter((item) => item && typeof item === "object") : [];
  const users = Array.isArray(safeConfig.users)
    ? safeConfig.users
        .filter((item) => item && typeof item === "object")
        .map((item) => {
          const clone = deepClone(item);
          delete clone.password;
          delete clone.password_set;
          delete clone.password_scheme;
          delete clone.password_modern;
          return clone;
        })
    : [];
  return { groups, users };
}

function sanitizeRuntimeConfig(config) {
  const safeConfig = deepClone(config && typeof config === "object" ? config : {});
  if (safeConfig.llm && typeof safeConfig.llm === "object") {
    delete safeConfig.llm.api_key_present;
  }
  return safeConfig;
}

function normalizePersonas(items) {
  return Array.isArray(items) ? items.filter((item) => item && typeof item === "object") : [];
}

function defaultMcpByKind(kind) {
  return {
    id: `remote-${Date.now()}`,
    name: "Neuer Remote MCP",
    description: "Externer MCP via HTTP",
    kind: "remote_http",
    enabled: true,
    protocol: "standard_v1",
    module: "",
    base_url: "http://remote-host:8080",
    execute_path: "/execute",
    health_path: "/health",
    bearer_token_env: "REMOTE_MCP_TOKEN",
    timeout_seconds: 15,
    working_dir: "",
    start_command: [],
    stop_command: [],
    status_command: [],
  };
}

function parseCommandJson(value, fieldName) {
  let parsed = [];
  try {
    parsed = JSON.parse(value || "[]");
  } catch (error) {
    throw new Error(`${fieldName} JSON ungueltig: ${error.message}`);
  }
  if (!Array.isArray(parsed)) {
    throw new Error(`${fieldName} muss ein JSON-Array sein.`);
  }
  return parsed;
}

function collectGuideDraft() {
  return {
    id: el.guideId.value.trim(),
    name: el.guideName.value.trim() || el.guideId.value.trim() || "Neuer Remote MCP",
    description: el.guideDescription.value.trim() || "Externer MCP via HTTP",
    kind: "remote_http",
    enabled: true,
    protocol: el.guideProtocol.value.trim() || "standard_v1",
    module: el.guideModule.value.trim().toLowerCase(),
    base_url: el.guideBaseUrl.value.trim(),
    execute_path: el.guideExecutePath.value.trim() || "/execute",
    health_path: el.guideHealthPath.value.trim() || "/health",
    bearer_token_env: el.guideBearerTokenEnv.value.trim(),
    timeout_seconds: Number(el.guideTimeoutSeconds.value || 15) || 15,
    working_dir: el.guideWorkingDir.value.trim(),
    start_command: parseCommandJson(el.guideStartCommand.value, "Start Command"),
    status_command: parseCommandJson(el.guideStatusCommand.value, "Status Command"),
    stop_command: parseCommandJson(el.guideStopCommand.value, "Stop Command"),
  };
}

function syncGuideFromMcp(item) {
  if (!item || typeof item !== "object") return;
  el.guideId.value = item.id || "";
  el.guideName.value = item.name || "";
  el.guideDescription.value = item.description || "";
  el.guideProtocol.value = item.protocol || "standard_v1";
  el.guideModule.value = item.module || "";
  el.guideBaseUrl.value = item.base_url || "";
  el.guideExecutePath.value = item.execute_path || "/execute";
  el.guideHealthPath.value = item.health_path || "/health";
  el.guideTimeoutSeconds.value = item.timeout_seconds ?? 15;
  el.guideBearerTokenEnv.value = item.bearer_token_env || "";
  el.guideWorkingDir.value = item.working_dir || "";
  el.guideStartCommand.value = JSON.stringify(item.start_command || [], null, 2);
  el.guideStatusCommand.value = JSON.stringify(item.status_command || [], null, 2);
  el.guideStopCommand.value = JSON.stringify(item.stop_command || [], null, 2);
}

function renderGuideMeta(target, rows = [], fallbackLabel = "Status", fallbackValue = "Keine Daten") {
  renderKvList(target, rows.length ? rows : [{ label: fallbackLabel, value: fallbackValue }]);
}

function upsertGuideDraftIntoManager(draft) {
  state.mcpsConfig = normalizeMcpsConfig(state.mcpsConfig);
  const index = state.mcpsConfig.mcps.findIndex((item) => item.id === draft.id);
  if (index >= 0) {
    state.mcpsConfig.mcps[index] = deepClone(draft);
  } else {
    state.mcpsConfig.mcps.push(deepClone(draft));
  }
  el.mcpsJson.value = JSON.stringify(state.mcpsConfig, null, 2);
  renderMcpManager();
}

function formatDate(value) {
  if (!value && value !== 0) return "-";
  if (typeof value === "number" && Number.isFinite(value)) {
    return new Date(value * 1000).toLocaleString("de-DE");
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("de-DE");
}

function formatMs(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number) || number <= 0) return "-";
  return `${Math.round(number)} ms`;
}

function formatPercent(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return "-";
  return `${number.toFixed(1)} %`;
}

function parseRuntimeConfig() {
  return sanitizeRuntimeConfig(JSON.parse(el.runtimeJson.value || "{}"));
}

function ensureRuntimeShape(config) {
  const safeConfig = config && typeof config === "object" ? config : {};
  if (!safeConfig.app || typeof safeConfig.app !== "object") safeConfig.app = {};
  if (!safeConfig.llm || typeof safeConfig.llm !== "object") safeConfig.llm = {};
  if (!safeConfig.chat || typeof safeConfig.chat !== "object") safeConfig.chat = {};
  return safeConfig;
}

function syncLlmFormFromRuntime(config) {
  const runtime = ensureRuntimeShape(deepClone(config || {}));
  el.llmBaseUrl.value = runtime.llm.base_url || "";
  el.llmModel.value = runtime.llm.model || "";
  el.llmFallbackModel.value = runtime.llm.fallback_model || "";
  el.llmTimeoutSeconds.value = runtime.llm.timeout_seconds ?? "";
  el.llmMaxTokens.value = runtime.llm.max_tokens ?? "";
}

function applyLlmFormToRuntime(config) {
  const runtime = ensureRuntimeShape(deepClone(config || {}));
  runtime.llm.base_url = el.llmBaseUrl.value.trim();
  runtime.llm.model = el.llmModel.value.trim();
  runtime.llm.fallback_model = el.llmFallbackModel.value.trim();
  const timeoutSeconds = Number(el.llmTimeoutSeconds.value);
  if (Number.isFinite(timeoutSeconds) && timeoutSeconds > 0) {
    runtime.llm.timeout_seconds = timeoutSeconds;
  }
  const maxTokens = Number(el.llmMaxTokens.value);
  if (Number.isFinite(maxTokens) && maxTokens > 0) {
    runtime.llm.max_tokens = Math.round(maxTokens);
  }
  return runtime;
}

function setActiveView(view) {
  if (!state.session?.is_admin && (view === "config" || view === "logs")) {
    view = "overview";
  }
  state.activeView = view;
  for (const button of el.viewButtons) {
    button.classList.toggle("active", button.dataset.viewButton === view);
  }
  for (const panel of el.viewPanels) {
    panel.classList.toggle("active", panel.dataset.viewPanel === view);
  }
  if (view === "logs" && !state.logsLoaded) {
    loadLogs().catch((error) => {
      el.logOutput.textContent = String(error.message || error);
    });
  }
  if (view === "config" && !state.adminLoaded) {
    loadAdminEditors().catch((error) => {
      el.controlOutput.textContent = String(error.message || error);
    });
  }
}

function selectedMcpIds() {
  return [...el.mcpSelector.querySelectorAll("input[data-mcp-id]:checked")].map((input) => input.dataset.mcpId);
}

async function fetchJson(url, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});
  if ((method === "POST" || method === "PUT" || method === "PATCH" || method === "DELETE") && state.session?.csrf_token) {
    headers.set("x-csrf-token", state.session.csrf_token);
  }
  const response = await fetch(url, { ...options, headers });
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  if (!response.ok) {
    if (response.status === 401) {
      showLogin("Anmeldung erforderlich.");
    }
    if (response.status === 503 && data.detail === "setup_required") {
      showSetup("Initiales Admin-Konto anlegen.");
    }
    throw new Error(data.detail || data.message || response.statusText);
  }
  return data;
}

async function ensureSession() {
  const data = await fetchJson("/api/auth/session");
  if (!data.authenticated) {
    if (data.setup_required) {
      showSetup("Initiales Admin-Konto anlegen.");
      return data;
    }
    showLogin("Anmeldung erforderlich.");
    return data;
  }
  state.session = data;
  state.setupRequired = false;
  el.loginGate.hidden = true;
  el.appShell.hidden = false;
  el.viewerPill.textContent = `User: ${data.display_name || data.username} (${data.role}, ${data.persona_id || "default"})`;
  for (const node of document.querySelectorAll(".admin-only")) {
    node.hidden = !data.is_admin;
  }
  renderRoleSummary(data);
  renderMcpSelector(data.mcps || []);
  return data;
}

function showLogin(message = "") {
  state.session = null;
  state.setupRequired = false;
  el.appShell.hidden = true;
  el.loginGate.hidden = false;
  el.loginForm.hidden = false;
  el.setupForm.hidden = true;
  el.loginOutput.textContent = message;
}

function showSetup(message = "") {
  state.session = null;
  state.setupRequired = true;
  el.appShell.hidden = true;
  el.loginGate.hidden = false;
  el.loginForm.hidden = true;
  el.setupForm.hidden = false;
  el.loginOutput.textContent = message;
}

function renderMcpSelector(mcps = []) {
  const toggleMarkup = mcps
    .map(
      (item) => `<label><input type="checkbox" data-mcp-id="${escapeHtml(item.id)}" checked> ${escapeHtml(item.label || item.id)}</label>`,
    )
    .join("");
  const emptyHint = mcps.length
    ? ""
    : `<span class="scope-hint">Diesem Benutzer sind aktuell keine MCPs zugewiesen.</span>`;
  el.mcpSelector.innerHTML = `${toggleMarkup}${emptyHint}<label><input id="show-mcp-context-in-chat" type="checkbox" ${el.showMcpContextInChat?.checked !== false ? "checked" : ""}> MCP Kontext im Chat</label>`;
  el.showMcpContextInChat = document.getElementById("show-mcp-context-in-chat");
  el.showMcpContextInChat.addEventListener("change", () => {
    persistUiPreferences();
  });
  loadUiPreferences();
}

function renderRoleSummary(session) {
  if (!el.roleSummary) return;
  const allowedCount = Array.isArray(session?.mcps) ? session.mcps.length : 0;
  const label = session?.is_admin
    ? `Admin-Modus aktiv. Volle Konfiguration, Logs und MCP-Steuerung sind freigeschaltet. Sichtbare MCPs: ${allowedCount}.`
    : `User-Modus aktiv. Sichtbar sind nur freigegebene MCPs, keine Admin-Konfiguration. Freigegebene MCPs: ${allowedCount}.`;
  el.roleSummary.hidden = false;
  el.roleSummary.innerHTML = `<strong>${escapeHtml(label)}</strong>`;
}

function renderCitations(items = []) {
  el.citations.innerHTML = "";
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = item;
    el.citations.appendChild(li);
  }
}

function summarizeResultRow(row) {
  if (!row || typeof row !== "object") return "";
  const parts = [];
  const preferredKeys = ["name", "display", "display_name", "path", "root_name", "address", "cidr", "fqdn", "device", "site", "status", "role"];
  for (const key of preferredKeys) {
    const value = row[key];
    if (typeof value === "string" && value.trim()) {
      parts.push(value.trim());
      if (parts.length >= 3) break;
      continue;
    }
    if (value && typeof value === "object") {
      if (typeof value.display === "string" && value.display.trim()) {
        parts.push(`${key}: ${value.display.trim()}`);
      } else if (typeof value.name === "string" && value.name.trim()) {
        parts.push(`${key}: ${value.name.trim()}`);
      }
      if (parts.length >= 3) break;
    }
  }
  if (!parts.length && typeof row.id !== "undefined") {
    parts.push(`id=${row.id}`);
  }
  return parts.join(" | ");
}

function formatMcpResultsForChat(results = []) {
  const blocks = [];
  for (const item of results) {
    if (!item || typeof item !== "object") continue;
    const title = item.mcp_id || "mcp";
    const action = item.action || "result";
    const data = item.data || {};
    if (Array.isArray(data.results) && data.results.length) {
      const lines = data.results.slice(0, 5).map((row, index) => {
        const summary = summarizeResultRow(row);
        return summary ? `${index + 1}. ${summary}` : `${index + 1}. Treffer`;
      });
      blocks.push(`[${title}:${action}]\n${lines.join("\n")}`);
      continue;
    }
    if (data.object && typeof data.object === "object") {
      const summary = summarizeResultRow(data.object);
      if (summary) {
        blocks.push(`[${title}:${action}]\n1. ${summary}`);
      }
    }
  }
  if (!blocks.length) return "";
  return `\n\n--- MCP Kontext ---\n${blocks.join("\n\n")}`;
}

function renderKvList(target, rows = []) {
  target.innerHTML = rows
    .map(
      (row) => `
        <div class="kv-row">
          <strong>${escapeHtml(row.label)}</strong>
          <div class="kv-value">${escapeHtml(row.value)}</div>
        </div>
      `,
    )
    .join("");
}

function renderConfigSummary(data) {
  const cards = [
    { label: "App", value: data.app_name || "-" },
    { label: "Release", value: `${data.release?.release || "-"}${data.release?.commit ? ` @ ${data.release.commit}` : ""}` },
    { label: "LLM Modell", value: data.llm?.model || "-" },
    { label: "MCPs", value: String((data.mcps || []).length) },
  ];
  el.configSummary.innerHTML = cards
    .map(
      (item) => `
        <article class="summary-card">
          <strong>${escapeHtml(item.label)}</strong>
          <span>${escapeHtml(item.value)}</span>
        </article>
      `,
    )
    .join("");

  renderKvList(el.pathsList, [
    { label: "runtime.json", value: data.paths?.runtime_config || "-" },
    { label: "mcps.local.json", value: data.paths?.mcps_config || "-" },
    { label: "passwd.json", value: data.paths?.passwd || "-" },
    { label: "personas/", value: data.paths?.personas_dir || "-" },
    { label: "aktive Persona", value: data.viewer?.persona_id || "-" },
    { label: "Fallback Prompt", value: data.paths?.system_prompt || "-" },
    { label: "Service Log", value: data.paths?.service_log_file || "-" },
  ]);
}

function platformQuickstart(platform = {}) {
  const family = platform.family || "other";
  if (family === "ubuntu") {
    return [
      "cd /srv/http/woddi-ai-control",
      "./check",
      "./scripts/ubuntu-first-setup.sh",
      "./woddi-ai-control service status",
    ].join("\n");
  }
  if (family === "arch") {
    return [
      "cd /srv/http/woddi-ai-control",
      "./check",
      "./scripts/arch-first-setup.sh",
      "./woddi-ai-control service status",
    ].join("\n");
  }
  return [
    "cd /srv/http/woddi-ai-control",
    "./check",
    "python -m venv .venv",
    "./woddi-ai-control start",
  ].join("\n");
}

function renderPlatformSummary(platform = {}) {
  if (!el.platformSummary || !el.platformChecks || !el.platformCommands) return;
  const cards = [
    { label: "Distribution", value: platform.pretty_name || "-" },
    { label: "Family", value: platform.family || "-" },
    { label: "Paketmanager", value: platform.package_manager || "-" },
    { label: "Python", value: platform.python || "-" },
  ];
  el.platformSummary.innerHTML = cards
    .map(
      (item) => `
        <article class="summary-card">
          <strong>${escapeHtml(item.label)}</strong>
          <span>${escapeHtml(item.value)}</span>
        </article>
      `,
    )
    .join("");
  renderKvList(el.platformChecks, [
    { label: "check", value: platform.has_check_script ? "./check vorhanden" : "./check fehlt" },
    { label: "Setup", value: platform.setup_hint || "-" },
    { label: "systemctl", value: platform.has_systemctl ? "vorhanden" : "fehlt" },
    { label: "git / curl", value: `${platform.has_git ? "git ok" : "git fehlt"} / ${platform.has_curl ? "curl ok" : "curl fehlt"}` },
  ]);
  el.platformCommands.textContent = platformQuickstart(platform);
}

function renderPerformance(data) {
  state.performance = data;
  const chat = data?.chat || {};
  const topEndpoint = data?.top_endpoint || null;
  const endpointRows = Array.isArray(data?.endpoints) ? data.endpoints.slice(0, 4) : [];
  const recentRows = Array.isArray(data?.recent) ? data.recent : [];

  const cards = [
    { label: "Chats / 30m", value: String(chat.total || 0) },
    { label: "Avg Chat", value: formatMs(chat.avg_total_ms) },
    { label: "Avg TTFT", value: formatMs(chat.avg_first_token_ms) },
    { label: "LLM Cache", value: formatPercent(chat.llm_cache_hit_rate) },
  ];
  el.performanceSummary.innerHTML = cards
    .map(
      (item) => `
        <article class="summary-card">
          <strong>${escapeHtml(item.label)}</strong>
          <span>${escapeHtml(item.value)}</span>
        </article>
      `,
    )
    .join("");

  renderKvList(el.performanceBreakdown, [
    { label: "MCP Kontext", value: formatMs(chat.avg_context_ms) },
    { label: "MCP Calls", value: String(chat.mcp_calls || 0) },
    { label: "MCP Fehler", value: String(chat.mcp_errors || 0) },
    { label: "Avg LLM Zeit", value: formatMs(chat.avg_llm_ms) },
    { label: "Avg Gesamt", value: formatMs(chat.avg_total_ms) },
  ]);

  renderKvList(
    el.performanceEndpoints,
    endpointRows.length
      ? endpointRows.map((row) => ({
          label: row.name,
          value: `${formatMs(row.avg_ms)} avg / ${formatMs(row.p95_ms)} p95 / ${row.count}x`,
        }))
      : [{ label: "Endpoints", value: "Noch keine Daten" }],
  );

  el.performanceRecent.textContent = recentRows.length
    ? recentRows
        .map((row) => {
          const timestamp = formatDate(row.timestamp_utc);
          const status = row.ok ? "ok" : "error";
          return `[${timestamp}] ${row.category}/${row.name} ${status} ${row.summary}`;
        })
        .join("\n")
    : "Noch keine Performance-Daten vorhanden.";

  if (topEndpoint) {
    const current = el.performanceBreakdown.innerHTML;
    el.performanceBreakdown.innerHTML =
      current +
      `
        <div class="kv-row">
          <strong>${escapeHtml("Langsamster Endpoint")}</strong>
          <div class="kv-value">${escapeHtml(`${topEndpoint.name} | ${formatMs(topEndpoint.avg_ms)} avg | ${formatMs(topEndpoint.p95_ms)} p95`)}</div>
        </div>
      `;
  }
}

function syncPersonaEditor() {
  const personas = normalizePersonas(state.personas);
  el.personaId.innerHTML = personas.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name || item.id)}</option>`).join("");
  const preferred = state.session?.persona_id || personas[0]?.id || "";
  if (!personas.some((item) => item.id === el.personaId.value)) {
    el.personaId.value = preferred;
  }
  const selected = personas.find((item) => item.id === el.personaId.value) || personas[0] || null;
  el.personaContent.value = selected?.content || "";
}

function syncPasswordResetUsers() {
  const users = Array.isArray(state.usersConfig?.users) ? state.usersConfig.users : [];
  if (!el.passwordResetUsername) return;
  el.passwordResetUsername.innerHTML = users
    .map((item) => `<option value="${escapeHtml(item.username)}">${escapeHtml(item.display_name || item.username)}</option>`)
    .join("");
  if (!users.some((item) => item.username === el.passwordResetUsername.value)) {
    el.passwordResetUsername.value = users[0]?.username || "";
  }
}

function renderMcpManager() {
  const config = normalizeMcpsConfig(state.mcpsConfig);
  el.mcpManager.innerHTML = config.mcps
    .map((item, index) => {
      return `
        <article class="docs-card mcp-manager-grid" data-mcp-index="${index}">
          <div class="docs-card-head">
            <div>
              <h3>${escapeHtml(item.name || item.id || `MCP ${index + 1}`)}</h3>
              <p class="muted">${escapeHtml(item.kind || "unknown")} / ${escapeHtml(item.id || "-")}</p>
            </div>
            <div class="button-row">
              ${item.kind === "remote_http" ? `<button type="button" class="secondary" data-mcp-action="status" data-mcp-id="${escapeHtml(item.id || "")}">Status</button>` : ""}
              ${item.kind === "remote_http" ? `<button type="button" class="secondary" data-mcp-action="start" data-mcp-id="${escapeHtml(item.id || "")}">Start</button>` : ""}
              ${item.kind === "remote_http" ? `<button type="button" class="secondary" data-mcp-action="stop" data-mcp-id="${escapeHtml(item.id || "")}">Stop</button>` : ""}
              ${item.kind === "remote_http" ? `<button type="button" class="secondary" data-mcp-action="handshake" data-mcp-id="${escapeHtml(item.id || "")}">Handshake</button>` : ""}
              ${item.kind === "remote_http" ? `<button type="button" class="secondary" data-mcp-action="guide" data-mcp-index="${index}">In Guide laden</button>` : ""}
              <button type="button" class="secondary" data-mcp-action="remove" data-mcp-index="${index}">Entfernen</button>
            </div>
          </div>
          <div class="panel-grid">
            <label>ID<input type="text" data-field="id" value="${escapeHtml(item.id || "")}"></label>
            <label>Name<input type="text" data-field="name" value="${escapeHtml(item.name || "")}"></label>
          </div>
          <div class="panel-grid">
            <label>Kind<input type="text" data-field="kind" value="${escapeHtml(item.kind || "")}" readonly></label>
            <label>Aktiv<input type="text" data-field="enabled" value="${item.enabled === false ? "false" : "true"}"></label>
          </div>
          <label>Beschreibung<input type="text" data-field="description" value="${escapeHtml(item.description || "")}"></label>
          ${item.kind === "remote_http" ? `
            <div class="panel-grid">
              <label>Protokoll
                <select data-field="protocol">
                  <option value="standard_v1" ${item.protocol === "satellite_execute_v1" ? "" : "selected"}>Standard MCP</option>
                  <option value="satellite_execute_v1" ${item.protocol === "satellite_execute_v1" ? "selected" : ""}>Satellite Execute</option>
                </select>
              </label>
              <label>Modul<input type="text" data-field="module" value="${escapeHtml(item.module || "")}"></label>
            </div>
            <div class="panel-grid">
              <label>Base URL<input type="text" data-field="base_url" value="${escapeHtml(item.base_url || "")}"></label>
              <label>Execute Path<input type="text" data-field="execute_path" value="${escapeHtml(item.execute_path || "/execute")}"></label>
            </div>
            <div class="panel-grid">
              <label>Health Path<input type="text" data-field="health_path" value="${escapeHtml(item.health_path || "/health")}"></label>
              <label>Bearer Token Env<input type="text" data-field="bearer_token_env" value="${escapeHtml(item.bearer_token_env || "")}"></label>
            </div>
            <div class="panel-grid">
              <label>Timeout<input type="text" data-field="timeout_seconds" value="${escapeHtml(item.timeout_seconds ?? "")}"></label>
              <label>Working Dir<input type="text" data-field="working_dir" value="${escapeHtml(item.working_dir || "")}"></label>
            </div>
            <label>Start Command JSON<textarea data-field="start_command" rows="3">${escapeHtml(JSON.stringify(item.start_command || [], null, 2))}</textarea></label>
            <label>Stop Command JSON<textarea data-field="stop_command" rows="3">${escapeHtml(JSON.stringify(item.stop_command || [], null, 2))}</textarea></label>
            <label>Status Command JSON<textarea data-field="status_command" rows="3">${escapeHtml(JSON.stringify(item.status_command || [], null, 2))}</textarea></label>
          ` : ""}
        </article>
      `;
    })
    .join("");
}

function collectMcpManagerConfig() {
  const cards = [...el.mcpManager.querySelectorAll("[data-mcp-index]")];
  const mcps = cards.map((card) => {
    const kind = card.querySelector('[data-field="kind"]').value.trim();
    const item = {
      id: card.querySelector('[data-field="id"]').value.trim(),
      name: card.querySelector('[data-field="name"]').value.trim(),
      description: card.querySelector('[data-field="description"]').value.trim(),
      kind,
      enabled: card.querySelector('[data-field="enabled"]').value.trim().toLowerCase() !== "false",
    };
    if (kind === "remote_http") {
      item.protocol = card.querySelector('[data-field="protocol"]').value.trim() || "standard_v1";
      item.module = card.querySelector('[data-field="module"]').value.trim().toLowerCase();
      item.base_url = card.querySelector('[data-field="base_url"]').value.trim();
      item.execute_path = card.querySelector('[data-field="execute_path"]').value.trim() || "/execute";
      item.health_path = card.querySelector('[data-field="health_path"]').value.trim() || "/health";
      item.bearer_token_env = card.querySelector('[data-field="bearer_token_env"]').value.trim();
      item.timeout_seconds = Number(card.querySelector('[data-field="timeout_seconds"]').value || 0) || 15;
      item.working_dir = card.querySelector('[data-field="working_dir"]').value.trim();
      item.start_command = JSON.parse(card.querySelector('[data-field="start_command"]').value || "[]");
      item.stop_command = JSON.parse(card.querySelector('[data-field="stop_command"]').value || "[]");
      item.status_command = JSON.parse(card.querySelector('[data-field="status_command"]').value || "[]");
    }
    return item;
  });
  return normalizeMcpsConfig({ mcps });
}

async function loadConfig() {
  const data = await fetchJson("/api/config");
  state.config = data;
  state.personas = normalizePersonas(data.personas || state.personas);
  const release = data.release?.release || "-";
  const commit = data.release?.commit ? ` @ ${data.release.commit}` : "";
  el.releasePill.textContent = `Release: ${release}${commit}`;
  el.llmPill.textContent = data.llm?.base_url ? `LLM: ${data.llm.model} @ ${data.llm.base_url}` : `LLM: ${data.llm?.model || "-"}`;
  el.mcpId.innerHTML = "";
  for (const item of data.mcps) {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = `${item.label} (${item.id})`;
    el.mcpId.appendChild(option);
  }
  renderConfigSummary(data);
  renderPlatformSummary(data.platform || {});
  if (state.session?.is_admin && state.adminLoaded) {
    renderMcpManager();
    syncPersonaEditor();
  }
}

async function loadAdminEditors(force = false) {
  if (!state.session?.is_admin) {
    state.adminLoaded = false;
    return;
  }
  if (state.adminLoading && !force) {
    return state.adminLoading;
  }
  const loader = (async () => {
    const [runtime, mcpsConfig, usersConfig, systemPrompt, personas] = await Promise.all([
      fetchJson("/api/admin/runtime"),
      fetchJson("/api/admin/mcps"),
      fetchJson("/api/admin/users"),
      fetchJson("/api/admin/system-prompt"),
      fetchJson("/api/admin/personas"),
    ]);
    state.mcpsConfig = normalizeMcpsConfig(mcpsConfig.config || { mcps: [] });
    state.usersConfig = normalizeUsersConfig(usersConfig.config || { groups: [], users: [] });
    state.personas = normalizePersonas(personas.items || []);
    const runtimeConfig = sanitizeRuntimeConfig(runtime.config || {});
    el.runtimeJson.value = JSON.stringify(runtimeConfig, null, 2);
    syncLlmFormFromRuntime(runtimeConfig);
    el.mcpsJson.value = JSON.stringify(state.mcpsConfig, null, 2);
    el.usersJson.value = JSON.stringify(state.usersConfig, null, 2);
    el.systemPrompt.value = systemPrompt.prompt || "";
    renderMcpManager();
    syncPersonaEditor();
    syncPasswordResetUsers();
    state.adminLoaded = true;
  })();
  state.adminLoading = loader;
  try {
    await loader;
  } finally {
    state.adminLoading = null;
  }
}

function cardMarkup(item) {
  const statusLabel = item.success ? "bereit" : "fehler";
  const statusClass = item.success ? "ok" : "error";
  const sourceHint = item.data?.source_path || item.data?.probe_url || item.base_url || "";
  const extraButton =
    item.kind === "documentation"
      ? `<button data-action="reindex" data-id="${escapeHtml(item.mcp_id || item.id)}" class="secondary">Reindex</button>`
      : "";
  return `
    <article class="mcp-card">
      <div class="mcp-card-head">
        <h3>${escapeHtml(item.label || item.mcp_id || item.id)}</h3>
        <span class="status-badge ${statusClass}">${statusLabel}</span>
      </div>
      <p>${escapeHtml(item.message || item.description || "")}</p>
      <p class="muted">${escapeHtml(sourceHint)}</p>
      <div class="card-actions">
        <button data-action="health" data-id="${escapeHtml(item.mcp_id || item.id)}" class="secondary">Health</button>
        ${extraButton}
      </div>
    </article>
  `;
}

async function refreshHealth() {
  const data = await fetchJson("/health");
  state.health = data;
  el.healthPill.textContent = `Health: ${data.status}`;
  const allowedIds = new Set((state.session?.mcps || []).map((item) => item.id));
  const visible = data.mcps.filter((item) => allowedIds.size === 0 || allowedIds.has(item.mcp_id || item.id));
  el.mcpCards.innerHTML = visible.map(cardMarkup).join("");
}

async function loadPerformance() {
  if (!state.session?.is_admin) {
    el.performanceSummary.innerHTML = "";
    el.performanceBreakdown.innerHTML = "";
    el.performanceEndpoints.innerHTML = "";
    el.performanceRecent.textContent = "Nur fuer Admin sichtbar.";
    return;
  }
  const data = await fetchJson("/api/admin/performance");
  renderPerformance(data);
}

async function loadLogs() {
  if (!state.session?.is_admin) return;
  const params = new URLSearchParams({
    file: el.logFile.value,
    lines: el.logLines.value,
  });
  const data = await fetchJson(`/api/admin/logs?${params.toString()}`);
  state.logsLoaded = true;
  el.logOutput.textContent = data.content || "Keine Log-Zeilen vorhanden.";
}

async function runMcp(id, action, payload) {
  return fetchJson(`/api/mcp/${id}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, payload }),
  });
}

async function refreshAppState({ reloadAdmin = false } = {}) {
  await loadConfig();
  await refreshHealth();
  await loadPerformance();
  if (reloadAdmin && state.session?.is_admin) {
    await loadAdminEditors(true);
  }
  state.logsLoaded = false;
}

async function submitDirectMcp() {
  let payload = {};
  try {
    payload = JSON.parse(el.mcpPayload.value || "{}");
  } catch (error) {
    el.mcpOutput.textContent = `Payload JSON ungueltig: ${error.message}`;
    return;
  }
  try {
    const data = await runMcp(el.mcpId.value, el.mcpAction.value, payload);
    el.mcpOutput.textContent = JSON.stringify(data, null, 2);
    setActiveView("tools");
    await loadPerformance();
  } catch (error) {
    el.mcpOutput.textContent = String(error.message || error);
    setActiveView("tools");
  }
}

async function saveRuntimeConfig() {
  let config = {};
  try {
    config = parseRuntimeConfig();
  } catch (error) {
    el.controlOutput.textContent = `Runtime JSON ungueltig: ${error.message}`;
    return;
  }
  const data = await fetchJson("/api/admin/runtime", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config }),
  });
  el.controlOutput.textContent = JSON.stringify(data, null, 2);
  await refreshAppState({ reloadAdmin: true });
}

async function saveLlmSettings() {
  let config = {};
  try {
    config = parseRuntimeConfig();
  } catch (error) {
    el.controlOutput.textContent = `Runtime JSON ungueltig: ${error.message}`;
    return;
  }
  const nextConfig = applyLlmFormToRuntime(config);
  el.runtimeJson.value = JSON.stringify(nextConfig, null, 2);
  await saveRuntimeConfig();
}

async function probeLlm() {
  const baseUrl = el.llmBaseUrl.value.trim();
  const timeoutSeconds = Number(el.llmTimeoutSeconds.value);
  const data = await fetchJson("/api/admin/llm-probe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      base_url: baseUrl || null,
      timeout_seconds: Number.isFinite(timeoutSeconds) && timeoutSeconds > 0 ? timeoutSeconds : null,
    }),
  });
  el.llmProbeOutput.textContent = JSON.stringify(data, null, 2);
}

async function saveMcpsRaw() {
  let config = {};
  try {
    config = JSON.parse(el.mcpsJson.value || "{}");
  } catch (error) {
    el.controlOutput.textContent = `MCP JSON ungueltig: ${error.message}`;
    return;
  }
  state.mcpsConfig = normalizeMcpsConfig(config);
  const data = await fetchJson("/api/admin/mcps", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mcps: state.mcpsConfig.mcps }),
  });
  el.controlOutput.textContent = JSON.stringify(data, null, 2);
  await refreshAppState({ reloadAdmin: true });
}

async function saveMcpManager() {
  state.mcpsConfig = collectMcpManagerConfig();
  el.mcpsJson.value = JSON.stringify(state.mcpsConfig, null, 2);
  await saveMcpsRaw();
}

async function runGuideAction(action) {
  const draft = collectGuideDraft();
  const data = await fetchJson("/api/admin/mcp-guide/probe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, draft }),
  });
  state.guideLastDraft = deepClone(draft);
  const checks = Array.isArray(data.checks)
    ? data.checks.map((item) => ({
        label: item.label || item.id || "Check",
        value: `${item.ok ? "ok" : "warn"}${item.detail ? ` | ${item.detail}` : ""}`,
      }))
    : [];
  const hints = Array.isArray(data.hints)
    ? data.hints.map((item, index) => ({
        label: `Hinweis ${index + 1}`,
        value: item,
      }))
    : [];
  renderGuideMeta(el.guideChecks, checks, "Checks", "Noch keine Guide-Checks");
  renderGuideMeta(el.guideHints, hints, "Hinweise", "Noch keine Hinweise");
  el.guideOutput.textContent = JSON.stringify(data, null, 2);
}

async function saveUsersRaw() {
  let config = {};
  try {
    config = JSON.parse(el.usersJson.value || "{}");
  } catch (error) {
    el.controlOutput.textContent = `User JSON ungueltig: ${error.message}`;
    return;
  }
  state.usersConfig = normalizeUsersConfig(config);
  const data = await fetchJson("/api/admin/users", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ groups: state.usersConfig.groups || [], users: state.usersConfig.users }),
  });
  el.controlOutput.textContent = JSON.stringify(data, null, 2);
  await refreshAppState({ reloadAdmin: true });
  syncPasswordResetUsers();
}

async function changeOwnPassword() {
  if (el.changePasswordNew.value !== el.changePasswordConfirm.value) {
    throw new Error("Neue Passwoerter stimmen nicht ueberein.");
  }
  const data = await fetchJson("/api/auth/password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      current_password: el.changePasswordCurrent.value,
      new_password: el.changePasswordNew.value,
      new_password_confirm: el.changePasswordConfirm.value,
    }),
  });
  el.changePasswordCurrent.value = "";
  el.changePasswordNew.value = "";
  el.changePasswordConfirm.value = "";
  el.changePasswordOutput.textContent = JSON.stringify(data, null, 2);
}

async function resetUserPassword() {
  if (el.passwordResetNew.value !== el.passwordResetConfirm.value) {
    throw new Error("Neue Passwoerter stimmen nicht ueberein.");
  }
  const username = el.passwordResetUsername.value.trim();
  if (!username) {
    throw new Error("Kein Benutzer ausgewaehlt.");
  }
  const data = await fetchJson(`/api/admin/users/${encodeURIComponent(username)}/password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      new_password: el.passwordResetNew.value,
      new_password_confirm: el.passwordResetConfirm.value,
    }),
  });
  el.passwordResetNew.value = "";
  el.passwordResetConfirm.value = "";
  el.passwordResetOutput.textContent = JSON.stringify(data, null, 2);
}

async function bootstrapAdminAccount() {
  if (el.setupPassword.value !== el.setupPasswordConfirm.value) {
    throw new Error("Passwoerter stimmen nicht ueberein.");
  }
  await fetchJson("/api/setup/bootstrap", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: el.setupUsername.value.trim(),
      display_name: el.setupDisplayName.value.trim() || el.setupUsername.value.trim(),
      password: el.setupPassword.value,
      password_confirm: el.setupPasswordConfirm.value,
    }),
  });
  el.setupPassword.value = "";
  el.setupPasswordConfirm.value = "";
  await ensureSession();
  setActiveView("overview");
  await refreshAppState({ reloadAdmin: true });
  el.loginOutput.textContent = "";
}

async function savePersona() {
  const personaId = el.personaId.value.trim();
  if (!personaId) {
    throw new Error("Keine Persona ausgewaehlt.");
  }
  const data = await fetchJson(`/api/admin/personas/${encodeURIComponent(personaId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content: el.personaContent.value }),
  });
  el.controlOutput.textContent = JSON.stringify(data, null, 2);
  await loadAdminEditors(true);
}

async function handshakeRemoteMcp(mcpId) {
  const data = await fetchJson(`/api/admin/mcps/${encodeURIComponent(mcpId)}/handshake`, {
    method: "POST",
  });
  el.controlOutput.textContent = JSON.stringify(data, null, 2);
  await refreshHealth();
}

async function controlRemoteMcp(mcpId, action) {
  const data = await fetchJson(`/api/admin/mcps/${encodeURIComponent(mcpId)}/control/${encodeURIComponent(action)}`, {
    method: "POST",
  });
  el.controlOutput.textContent = JSON.stringify(data, null, 2);
  await refreshHealth();
}

async function saveSystemPrompt() {
  const data = await fetchJson("/api/admin/system-prompt", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt: el.systemPrompt.value }),
  });
  el.controlOutput.textContent = JSON.stringify(data, null, 2);
  state.logsLoaded = false;
}

async function postControl(url) {
  const data = await fetchJson(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ delay_seconds: 0.8 }),
  });
  el.controlOutput.textContent = JSON.stringify(data, null, 2);
  state.logsLoaded = false;
}

async function streamChat() {
  const payload = {
    message: el.chatInput.value.trim(),
    session_id: el.sessionId.value.trim() || "woddi-ai-control-session",
    metadata: { selected_mcp_ids: selectedMcpIds() },
  };
  if (!payload.message) return;

  resetChat();
  renderCitations([]);
  el.mcpDebug.textContent = "stream startet...";

  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok || !response.body) {
    const text = await response.text();
    throw new Error(text || "stream_failed");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let meta = null;
  let donePayload = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let splitIndex;
    while ((splitIndex = buffer.indexOf("\n\n")) >= 0) {
      const rawEvent = buffer.slice(0, splitIndex);
      buffer = buffer.slice(splitIndex + 2);
      const lines = rawEvent.split("\n");
      let eventName = "message";
      let data = "";
      for (const line of lines) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      const payloadObj = JSON.parse(data);
      if (eventName === "chunk") appendChat(payloadObj.text || "");
      if (eventName === "meta") meta = payloadObj;
      if (eventName === "done") donePayload = payloadObj;
      if (eventName === "error") throw new Error(payloadObj.message || "stream_error");
    }
  }

  if (meta?.citations) renderCitations(meta.citations);
  if (donePayload?.mcp_results) {
    el.mcpDebug.textContent = JSON.stringify(donePayload.mcp_results, null, 2);
    if (el.showMcpContextInChat.checked) {
      const contextSummary = formatMcpResultsForChat(donePayload.mcp_results);
      if (contextSummary) appendChat(contextSummary);
    }
  }
}

el.sendChat.addEventListener("click", async () => {
  try {
    await streamChat();
    await loadPerformance();
  } catch (error) {
    el.mcpDebug.textContent = String(error.message || error);
  }
});

el.loginSubmit.addEventListener("click", async () => {
  try {
    await fetchJson("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: el.loginUsername.value.trim(), password: el.loginPassword.value }),
    });
    el.loginPassword.value = "";
    await ensureSession();
    setActiveView("overview");
    await refreshAppState({ reloadAdmin: true });
    el.loginOutput.textContent = "";
  } catch (error) {
    el.loginOutput.textContent = String(error.message || error);
  }
});

el.setupSubmit.addEventListener("click", async () => {
  try {
    await bootstrapAdminAccount();
  } catch (error) {
    el.loginOutput.textContent = String(error.message || error);
  }
});

el.changePasswordSubmit.addEventListener("click", async () => {
  try {
    await changeOwnPassword();
  } catch (error) {
    el.changePasswordOutput.textContent = String(error.message || error);
  }
});

el.logoutButton.addEventListener("click", async () => {
  try {
    await fetchJson("/api/auth/logout", { method: "POST" });
  } catch (_error) {
    // ignore logout transport errors and still reset the UI
  }
  showLogin("Abgemeldet.");
});

el.chatInput.addEventListener("keydown", async (event) => {
  if (!(event.ctrlKey || event.metaKey) || event.key !== "Enter") {
    return;
  }
  event.preventDefault();
  try {
    await streamChat();
    await loadPerformance();
  } catch (error) {
    el.mcpDebug.textContent = String(error.message || error);
  }
});

el.clearChat.addEventListener("click", () => {
  resetChat();
  renderCitations([]);
  el.mcpDebug.textContent = "";
});

for (const button of el.viewButtons) {
  button.addEventListener("click", () => {
    setActiveView(button.dataset.viewButton);
  });
}

el.refreshHealth.addEventListener("click", async () => {
  try {
    await refreshHealth();
    await loadPerformance();
  } catch (error) {
    el.mcpDebug.textContent = String(error.message || error);
  }
});

el.refreshLogs.addEventListener("click", async () => {
  try {
    await loadLogs();
  } catch (error) {
    el.logOutput.textContent = String(error.message || error);
  }
});

el.logFile.addEventListener("change", async () => {
  try {
    await loadLogs();
  } catch (error) {
    el.logOutput.textContent = String(error.message || error);
  }
});

el.logLines.addEventListener("change", async () => {
  try {
    await loadLogs();
  } catch (error) {
    el.logOutput.textContent = String(error.message || error);
  }
});

el.runMcp.addEventListener("click", submitDirectMcp);
el.saveRuntime.addEventListener("click", async () => {
  try {
    await saveRuntimeConfig();
  } catch (error) {
    el.controlOutput.textContent = String(error.message || error);
  }
});

el.saveLlmSettings.addEventListener("click", async () => {
  try {
    await saveLlmSettings();
  } catch (error) {
    el.controlOutput.textContent = String(error.message || error);
  }
});

el.probeLlm.addEventListener("click", async () => {
  try {
    await probeLlm();
  } catch (error) {
    el.llmProbeOutput.textContent = String(error.message || error);
  }
});

el.saveSystemPrompt.addEventListener("click", async () => {
  try {
    await saveSystemPrompt();
  } catch (error) {
    el.controlOutput.textContent = String(error.message || error);
  }
});

el.saveMcps.addEventListener("click", async () => {
  try {
    await saveMcpsRaw();
  } catch (error) {
    el.controlOutput.textContent = String(error.message || error);
  }
});

el.saveMcpManager.addEventListener("click", async () => {
  try {
    await saveMcpManager();
  } catch (error) {
    el.controlOutput.textContent = String(error.message || error);
  }
});

el.guideValidate.addEventListener("click", async () => {
  try {
    await runGuideAction("validate");
  } catch (error) {
    el.guideOutput.textContent = String(error.message || error);
  }
});

el.guideHealth.addEventListener("click", async () => {
  try {
    await runGuideAction("health");
  } catch (error) {
    el.guideOutput.textContent = String(error.message || error);
  }
});

el.guideHandshake.addEventListener("click", async () => {
  try {
    await runGuideAction("handshake");
  } catch (error) {
    el.guideOutput.textContent = String(error.message || error);
  }
});

el.guideStatusCommandRun.addEventListener("click", async () => {
  try {
    await runGuideAction("status");
  } catch (error) {
    el.guideOutput.textContent = String(error.message || error);
  }
});

el.guideStartCommandRun.addEventListener("click", async () => {
  try {
    await runGuideAction("start");
  } catch (error) {
    el.guideOutput.textContent = String(error.message || error);
  }
});

el.guideStopCommandRun.addEventListener("click", async () => {
  try {
    await runGuideAction("stop");
  } catch (error) {
    el.guideOutput.textContent = String(error.message || error);
  }
});

el.guideAdopt.addEventListener("click", async () => {
  try {
    const data = await fetchJson("/api/admin/mcp-guide/probe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "validate", draft: collectGuideDraft() }),
    });
    upsertGuideDraftIntoManager(data.draft || collectGuideDraft());
    el.guideOutput.textContent = JSON.stringify({ success: true, message: "Guide-Draft validiert und in MCP-Manager uebernommen.", id: data.draft?.id || "" }, null, 2);
  } catch (error) {
    el.guideOutput.textContent = String(error.message || error);
  }
});

for (const [button, kind] of [[el.addMcpRemote, "remote_http"]]) {
  if (!button) continue;
  button.addEventListener("click", () => {
    state.mcpsConfig = normalizeMcpsConfig(state.mcpsConfig);
    const draft = defaultMcpByKind(kind);
    state.mcpsConfig.mcps.push(draft);
    el.mcpsJson.value = JSON.stringify(state.mcpsConfig, null, 2);
    renderMcpManager();
    syncGuideFromMcp(draft);
  });
}

el.saveUsers.addEventListener("click", async () => {
  try {
    await saveUsersRaw();
  } catch (error) {
    el.controlOutput.textContent = String(error.message || error);
  }
});

el.passwordResetSubmit.addEventListener("click", async () => {
  try {
    await resetUserPassword();
  } catch (error) {
    el.passwordResetOutput.textContent = String(error.message || error);
  }
});

el.personaId.addEventListener("change", () => {
  syncPersonaEditor();
});

el.savePersona.addEventListener("click", async () => {
  try {
    await savePersona();
  } catch (error) {
    el.controlOutput.textContent = String(error.message || error);
  }
});

el.reloadRuntime.addEventListener("click", async () => {
  try {
    const data = await fetchJson("/api/admin/reload", { method: "POST" });
    el.controlOutput.textContent = JSON.stringify(data, null, 2);
    await refreshAppState({ reloadAdmin: true });
  } catch (error) {
    el.controlOutput.textContent = String(error.message || error);
  }
});

el.restartApp.addEventListener("click", async () => {
  try {
    await postControl("/api/admin/control/restart");
  } catch (error) {
    el.controlOutput.textContent = String(error.message || error);
  }
});

el.shutdownApp.addEventListener("click", async () => {
  try {
    await postControl("/api/admin/control/shutdown");
  } catch (error) {
    el.controlOutput.textContent = String(error.message || error);
  }
});

el.mcpCards.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-id]");
  if (!button) return;
  const { id, action } = button.dataset;
  try {
    const data = await runMcp(id, action, {});
    el.mcpOutput.textContent = JSON.stringify(data, null, 2);
    setActiveView("tools");
    await refreshHealth();
    await loadPerformance();
  } catch (error) {
    el.mcpOutput.textContent = String(error.message || error);
    setActiveView("tools");
  }
});

el.mcpManager.addEventListener("click", async (event) => {
  const removeButton = event.target.closest('button[data-mcp-action="remove"]');
  if (removeButton) {
    const index = Number(removeButton.dataset.mcpIndex);
    state.mcpsConfig.mcps.splice(index, 1);
    el.mcpsJson.value = JSON.stringify(state.mcpsConfig, null, 2);
    renderMcpManager();
    return;
  }
  const guideButton = event.target.closest('button[data-mcp-action="guide"]');
  if (guideButton) {
    const index = Number(guideButton.dataset.mcpIndex);
    const item = state.mcpsConfig?.mcps?.[index];
    syncGuideFromMcp(item);
    el.guideOutput.textContent = JSON.stringify({ success: true, message: "MCP in Guide geladen.", id: item?.id || "" }, null, 2);
    return;
  }
  const handshakeButton = event.target.closest('button[data-mcp-action="handshake"]');
  if (handshakeButton) {
    try {
      await saveMcpManager();
      await handshakeRemoteMcp(handshakeButton.dataset.mcpId);
    } catch (error) {
      el.controlOutput.textContent = String(error.message || error);
    }
  }
  const controlButton = event.target.closest('button[data-mcp-action="start"], button[data-mcp-action="stop"], button[data-mcp-action="status"]');
  if (controlButton) {
    try {
      await saveMcpManager();
      await controlRemoteMcp(controlButton.dataset.mcpId, controlButton.dataset.mcpAction);
    } catch (error) {
      el.controlOutput.textContent = String(error.message || error);
    }
  }
});

(async function bootstrap() {
  try {
    loadUiPreferences();
    const session = await ensureSession();
    if (!session?.authenticated) {
      return;
    }
    setActiveView("overview");
    await loadConfig();
    await refreshHealth();
    await loadPerformance();
    if (state.session?.is_admin) {
      await loadAdminEditors();
    }
  } catch (error) {
    if (state.setupRequired) {
      showSetup("");
      return;
    }
    showLogin("");
  }
})();
