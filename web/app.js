const el = {
  loginGate: document.getElementById("login-gate"),
  appShell: document.getElementById("app-shell"),
  loginUsername: document.getElementById("login-username"),
  loginPassword: document.getElementById("login-password"),
  loginSubmit: document.getElementById("login-submit"),
  loginOutput: document.getElementById("login-output"),
  viewerPill: document.getElementById("viewer-pill"),
  logoutButton: document.getElementById("logout-button"),
  releasePill: document.getElementById("release-pill"),
  healthPill: document.getElementById("health-pill"),
  llmPill: document.getElementById("llm-pill"),
  viewButtons: [...document.querySelectorAll("[data-view-button]")],
  viewPanels: [...document.querySelectorAll("[data-view-panel]")],
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
  configSummary: document.getElementById("config-summary"),
  netboxSummary: document.getElementById("netbox-summary"),
  pathsList: document.getElementById("paths-list"),
  performanceSummary: document.getElementById("performance-summary"),
  performanceBreakdown: document.getElementById("performance-breakdown"),
  performanceEndpoints: document.getElementById("performance-endpoints"),
  performanceRecent: document.getElementById("performance-recent"),
  docsNav: document.getElementById("docs-nav"),
  docsMeta: document.getElementById("docs-meta"),
  docsContent: document.getElementById("docs-content"),
  mcpId: document.getElementById("mcp-id"),
  mcpAction: document.getElementById("mcp-action"),
  mcpPayload: document.getElementById("mcp-payload"),
  runMcp: document.getElementById("run-mcp"),
  mcpOutput: document.getElementById("mcp-output"),
  netboxObjectType: document.getElementById("netbox-object-type"),
  netboxQuery: document.getElementById("netbox-query"),
  runNetbox: document.getElementById("run-netbox"),
  netboxOutput: document.getElementById("netbox-output"),
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
  netboxBaseUrl: document.getElementById("netbox-base-url"),
  netboxTokenEnv: document.getElementById("netbox-token-env"),
  netboxToken: document.getElementById("netbox-token"),
  netboxTimeoutSeconds: document.getElementById("netbox-timeout-seconds"),
  netboxCacheTtlSeconds: document.getElementById("netbox-cache-ttl-seconds"),
  saveNetboxSettings: document.getElementById("save-netbox-settings"),
  probeNetbox: document.getElementById("probe-netbox"),
  netboxProbeOutput: document.getElementById("netbox-probe-output"),
  netboxExplorerObjectType: document.getElementById("netbox-explorer-object-type"),
  netboxExplorerQuery: document.getElementById("netbox-explorer-query"),
  netboxExplorerSampleLimit: document.getElementById("netbox-explorer-sample-limit"),
  exploreNetboxFields: document.getElementById("explore-netbox-fields"),
  downloadNetboxBundle: document.getElementById("download-netbox-bundle"),
  netboxExplorerOutput: document.getElementById("netbox-explorer-output"),
  runtimeJson: document.getElementById("runtime-json"),
  saveRuntime: document.getElementById("save-runtime"),
  docsSourcesJson: document.getElementById("docs-sources-json"),
  saveDocsSources: document.getElementById("save-docs-sources"),
  docsSourcesManager: document.getElementById("docs-sources-manager"),
  docsManagerNote: document.getElementById("docs-manager-note"),
  saveDocsManager: document.getElementById("save-docs-manager"),
  filesSourcesJson: document.getElementById("files-sources-json"),
  saveFilesSources: document.getElementById("save-files-sources"),
  filesSourcesManager: document.getElementById("files-sources-manager"),
  filesManagerNote: document.getElementById("files-manager-note"),
  saveFilesManager: document.getElementById("save-files-manager"),
  mcpManager: document.getElementById("mcp-manager"),
  addMcpDocs: document.getElementById("add-mcp-docs"),
  addMcpFiles: document.getElementById("add-mcp-files"),
  addMcpNetbox: document.getElementById("add-mcp-netbox"),
  addMcpRemote: document.getElementById("add-mcp-remote"),
  saveMcpManager: document.getElementById("save-mcp-manager"),
  mcpsJson: document.getElementById("mcps-json"),
  saveMcps: document.getElementById("save-mcps"),
  usersJson: document.getElementById("users-json"),
  saveUsers: document.getElementById("save-users"),
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
  docsSourcesConfig: { sources: [] },
  filesSourcesConfig: { sources: [] },
  performance: null,
  streamBuffer: "",
  activeView: "overview",
  logsLoaded: false,
  adminLoaded: false,
  adminLoading: null,
  session: null,
  mcpsConfig: { mcps: [] },
  usersConfig: { groups: [], users: [] },
  personas: [],
  docsCatalog: [],
  activeDocId: "",
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

function normalizeDocsSources(config) {
  const safeConfig = config && typeof config === "object" ? config : {};
  const sources = Array.isArray(safeConfig.sources) ? safeConfig.sources.filter((item) => item && typeof item === "object") : [];
  return { ...safeConfig, sources };
}

function normalizeMcpsConfig(config) {
  const safeConfig = config && typeof config === "object" ? config : {};
  const mcps = Array.isArray(safeConfig.mcps) ? safeConfig.mcps.filter((item) => item && typeof item === "object") : [];
  return { ...safeConfig, mcps };
}

function normalizeUsersConfig(config) {
  const safeConfig = config && typeof config === "object" ? config : {};
  const groups = Array.isArray(safeConfig.groups) ? safeConfig.groups.filter((item) => item && typeof item === "object") : [];
  const users = Array.isArray(safeConfig.users) ? safeConfig.users.filter((item) => item && typeof item === "object") : [];
  return { ...safeConfig, groups, users };
}

function normalizePersonas(items) {
  return Array.isArray(items) ? items.filter((item) => item && typeof item === "object") : [];
}

function normalizeDocsCatalog(items) {
  return Array.isArray(items) ? items.filter((item) => item && typeof item === "object") : [];
}

function renderDocsCatalog() {
  const items = normalizeDocsCatalog(state.docsCatalog);
  if (!items.length) {
    el.docsNav.innerHTML = "";
    el.docsMeta.innerHTML = "";
    el.docsContent.textContent = "Keine Doku gefunden.";
    return;
  }
  if (!items.some((item) => item.id === state.activeDocId)) {
    state.activeDocId = items[0].id;
  }
  el.docsNav.innerHTML = items
    .map(
      (item) => `<button class="${item.id === state.activeDocId ? "" : "secondary"}" data-doc-id="${escapeHtml(item.id)}">${escapeHtml(item.title || item.id)}</button>`,
    )
    .join("");
  const selected = items.find((item) => item.id === state.activeDocId) || items[0];
  renderKvList(el.docsMeta, [
    { label: "Titel", value: selected.title || selected.id || "-" },
    { label: "Pfad", value: selected.path || "-" },
  ]);
  el.docsContent.textContent = selected.content || "";
}

function defaultMcpByKind(kind) {
  if (kind === "docs") {
    return {
      id: `docs-${Date.now()}`,
      name: "Neue Docs Quelle",
      description: "Lokale Dokumentation",
      kind: "docs",
      enabled: true,
      path: "/srv/http/example-docs",
      patterns: ["README.md", "docs/**/*.md"],
    };
  }
  if (kind === "files") {
    return {
      id: `files-${Date.now()}`,
      name: "Neue Files Quelle",
      description: "Dateibasiertes MCP",
      kind: "files",
      enabled: true,
      roots: [{ id: "workspace", name: "Workspace", path: "/srv/http", patterns: ["**/*.md", "**/*.json", "**/*.py"] }],
    };
  }
  if (kind === "netbox") {
    return {
      id: `netbox-${Date.now()}`,
      name: "Neue NetBox Quelle",
      description: "NetBox API",
      kind: "netbox",
      enabled: true,
      base_url: "https://netbox.example.com/api",
      token_env: "NETBOX_TOKEN",
      cache_ttl_seconds: 45,
      timeout_seconds: 12,
    };
  }
  return {
    id: `remote-${Date.now()}`,
    name: "Neuer Remote MCP",
    description: "Externer MCP via HTTP",
    kind: "remote_http",
    enabled: true,
    base_url: "http://remote-host:8080",
    execute_path: "/execute",
    health_path: "/health",
    bearer_token_env: "REMOTE_MCP_TOKEN",
    timeout_seconds: 15,
  };
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
  return JSON.parse(el.runtimeJson.value || "{}");
}

function ensureRuntimeShape(config) {
  const safeConfig = config && typeof config === "object" ? config : {};
  if (!safeConfig.app || typeof safeConfig.app !== "object") safeConfig.app = {};
  if (!safeConfig.llm || typeof safeConfig.llm !== "object") safeConfig.llm = {};
  if (!safeConfig.chat || typeof safeConfig.chat !== "object") safeConfig.chat = {};
  if (!safeConfig.docs || typeof safeConfig.docs !== "object") safeConfig.docs = {};
  if (!safeConfig.netbox || typeof safeConfig.netbox !== "object") safeConfig.netbox = {};
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

function syncNetboxFormFromRuntime(config) {
  const runtime = ensureRuntimeShape(deepClone(config || {}));
  el.netboxBaseUrl.value = runtime.netbox.base_url || "";
  el.netboxTokenEnv.value = runtime.netbox.token_env || "";
  el.netboxToken.value = runtime.netbox.token || "";
  el.netboxTimeoutSeconds.value = runtime.netbox.timeout_seconds ?? "";
  el.netboxCacheTtlSeconds.value = runtime.netbox.cache_ttl_seconds ?? "";
}

function applyNetboxFormToRuntime(config) {
  const runtime = ensureRuntimeShape(deepClone(config || {}));
  runtime.netbox.base_url = el.netboxBaseUrl.value.trim();
  runtime.netbox.token_env = el.netboxTokenEnv.value.trim();
  runtime.netbox.token = el.netboxToken.value.trim();
  const timeoutSeconds = Number(el.netboxTimeoutSeconds.value);
  if (Number.isFinite(timeoutSeconds) && timeoutSeconds > 0) {
    runtime.netbox.timeout_seconds = timeoutSeconds;
  }
  const cacheTtl = Number(el.netboxCacheTtlSeconds.value);
  if (Number.isFinite(cacheTtl) && cacheTtl > 0) {
    runtime.netbox.cache_ttl_seconds = Math.round(cacheTtl);
  }
  return runtime;
}

function setActiveView(view) {
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
  const response = await fetch(url, options);
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
    throw new Error(data.detail || data.message || response.statusText);
  }
  return data;
}

async function ensureSession() {
  const data = await fetchJson("/api/auth/session");
  state.session = data;
  el.loginGate.hidden = true;
  el.appShell.hidden = false;
  el.viewerPill.textContent = `User: ${data.display_name || data.username} (${data.role}, ${data.persona_id || "default"})`;
  for (const node of document.querySelectorAll(".admin-only")) {
    node.hidden = !data.is_admin;
  }
  renderMcpSelector(data.mcps || []);
  return data;
}

function showLogin(message = "") {
  state.session = null;
  el.appShell.hidden = true;
  el.loginGate.hidden = false;
  el.loginOutput.textContent = message;
}

function renderMcpSelector(mcps = []) {
  const toggleMarkup = mcps
    .map(
      (item) => `<label><input type="checkbox" data-mcp-id="${escapeHtml(item.id)}" checked> ${escapeHtml(item.label || item.id)}</label>`,
    )
    .join("");
  el.mcpSelector.innerHTML = `${toggleMarkup}<label><input id="show-mcp-context-in-chat" type="checkbox" ${el.showMcpContextInChat?.checked !== false ? "checked" : ""}> MCP Kontext im Chat</label>`;
  el.showMcpContextInChat = document.getElementById("show-mcp-context-in-chat");
  el.showMcpContextInChat.addEventListener("change", () => {
    persistUiPreferences();
  });
  loadUiPreferences();
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

  renderKvList(el.netboxSummary, [
    { label: "Base URL", value: data.netbox?.base_url || "-" },
    { label: "Auth", value: data.netbox?.auth_mode || "anonymous" },
    { label: "Token", value: data.netbox?.token_present ? "vorhanden" : "nicht gesetzt" },
    { label: "Probe", value: data.netbox?.status_probe_url || "-" },
  ]);

  renderKvList(el.pathsList, [
    { label: "runtime.json", value: data.paths?.runtime_config || "-" },
    { label: "mcps.local.json", value: data.paths?.mcps_config || "-" },
    { label: "passwd.json", value: data.paths?.passwd || "-" },
    { label: "personas/", value: data.paths?.personas_dir || "-" },
    { label: "docs cache", value: data.paths?.docs_cache_dir || "-" },
    { label: "aktive Persona", value: data.viewer?.persona_id || "-" },
    { label: "Fallback Prompt", value: data.paths?.system_prompt || "-" },
    { label: "Pfad ausserhalb Projekt", value: data.docs?.allow_outside_project ? "erlaubt" : "blockiert" },
    { label: "Service Log", value: data.paths?.service_log_file || "-" },
  ]);
}

function renderPerformance(data) {
  state.performance = data;
  const chat = data?.chat || {};
  const docs = data?.docs || {};
  const netbox = data?.netbox || {};
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
    { label: "Docs Suche", value: String(docs.searches || 0) },
    { label: "Docs Cache", value: formatPercent(docs.cache_hit_rate) },
    { label: "Index Memory Hit", value: formatPercent(docs.index_memory_hit_rate) },
    { label: "NetBox Cache", value: formatPercent(netbox.cache_hit_rate) },
    { label: "Files Cache", value: formatPercent(chat.files_cache_hit_rate) },
    { label: "Avg Docs Zeit", value: formatMs(chat.avg_docs_ms) },
    { label: "Avg LLM Zeit", value: formatMs(chat.avg_llm_ms) },
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

function docsHealthById(sourceId) {
  const items = Array.isArray(state.health?.mcps) ? state.health.mcps : [];
  return items.find((item) => (item.mcp_id || item.id) === sourceId) || null;
}

function syncDocsSourcesEditor(config) {
  el.docsSourcesJson.value = JSON.stringify(config, null, 2);
}

function renderDocsManager() {
  const config = normalizeDocsSources(state.docsSourcesConfig);
  const allowOutside = !!state.config?.docs?.allow_outside_project;
  el.docsManagerNote.textContent = allowOutside
    ? "Absolute Pfade sind aktuell erlaubt. Fuer externe Doku-Pfade wie /opt/... kann direkt gespeichert und importiert werden."
    : "Absolute Pfade ausserhalb des Projekts sind aktuell blockiert. Fuer /opt/... muss docs.allow_outside_project in der Runtime auf true stehen.";

  el.docsSourcesManager.innerHTML = config.sources
    .map((source) => {
      const health = docsHealthById(source.id);
      const statusClass = health?.success ? "ok" : "error";
      const statusLabel = health ? (health.success ? "bereit" : "fehlt") : "unbekannt";
      const indexLabel = health?.data?.index_exists
        ? (health.data?.index_matches_sources ? "aktuell" : "vorhanden, stale")
        : "kein Index";
      return `
        <article class="docs-card" data-source-id="${escapeHtml(source.id)}">
          <div class="docs-card-head">
            <div>
              <h3>${escapeHtml(source.name || source.id)}</h3>
              <p class="muted">${escapeHtml(source.id)}</p>
            </div>
            <span class="status-badge ${statusClass}">${escapeHtml(statusLabel)}</span>
          </div>

          <label>
            Lokaler Pfad
            <input type="text" data-docs-path="${escapeHtml(source.id)}" value="${escapeHtml(source.path || "")}">
          </label>

          <div class="docs-stats">
            <div class="docs-stat">
              <strong>Dateien</strong>
              <span>${escapeHtml(health?.data?.document_count ?? "-")}</span>
            </div>
            <div class="docs-stat">
              <strong>Index</strong>
              <span>${escapeHtml(indexLabel)}</span>
            </div>
            <div class="docs-stat">
              <strong>Index gebaut</strong>
              <span>${escapeHtml(formatDate(health?.data?.index_generated_at))}</span>
            </div>
            <div class="docs-stat">
              <strong>Quelle</strong>
              <span>${escapeHtml(health?.data?.source_path || source.path || "-")}</span>
            </div>
          </div>

          <div class="upload-row">
            <label>
              ZIP Upload
              <input type="file" data-docs-upload="${escapeHtml(source.id)}" accept=".zip,application/zip">
            </label>
            <div class="button-row">
              <button type="button" class="secondary" data-docs-action="upload" data-source-id="${escapeHtml(source.id)}">ZIP importieren</button>
              <button type="button" class="secondary" data-docs-action="reindex" data-source-id="${escapeHtml(source.id)}">Reindex</button>
            </div>
          </div>
        </article>
      `;
    })
    .join("");
}

function docsManagerConfig() {
  const config = normalizeDocsSources(state.docsSourcesConfig);
  const next = deepClone(config);
  for (const source of next.sources) {
    const input = el.docsSourcesManager.querySelector(`[data-docs-path="${source.id}"]`);
    if (input) {
      source.path = input.value.trim();
    }
  }
  return next;
}

function docsConfigFingerprint(config) {
  const sources = normalizeDocsSources(config).sources.map((item) => ({
    id: item.id || "",
    name: item.name || "",
    path: item.path || "",
    patterns: Array.isArray(item.patterns) ? item.patterns : [],
  }));
  return JSON.stringify(sources);
}

function normalizeFilesSources(config) {
  const safeConfig = config && typeof config === "object" ? config : {};
  const sources = Array.isArray(safeConfig.sources) ? safeConfig.sources.filter((item) => item && typeof item === "object") : [];
  return { ...safeConfig, sources };
}

function syncFilesSourcesEditor(config) {
  el.filesSourcesJson.value = JSON.stringify(config, null, 2);
}

function filesHealth() {
  const items = Array.isArray(state.health?.mcps) ? state.health.mcps : [];
  return items.find((item) => (item.mcp_id || item.id) === "files") || null;
}

function renderFilesManager() {
  const config = normalizeFilesSources(state.filesSourcesConfig);
  const allowOutside = !!state.config?.files?.allow_outside_project;
  const health = filesHealth();
  const healthRoots = Array.isArray(health?.data?.roots) ? health.data.roots : [];
  const healthById = Object.fromEntries(healthRoots.map((item) => [item.id, item]));
  el.filesManagerNote.textContent = allowOutside
    ? "Absolute File-Roots sind erlaubt. Damit koennen auch externe MCP- oder Repo-Pfade eingebunden werden."
    : "File-Roots ausserhalb des Projekts sind aktuell blockiert.";

  el.filesSourcesManager.innerHTML = config.sources
    .map((source) => {
      const sourceHealth = healthById[source.id] || null;
      const statusClass = sourceHealth?.exists ? "ok" : "error";
      const statusLabel = sourceHealth?.exists ? "bereit" : "fehlt";
      const patterns = Array.isArray(source.patterns) ? source.patterns.join(", ") : "";
      return `
        <article class="docs-card" data-root-id="${escapeHtml(source.id)}">
          <div class="docs-card-head">
            <div>
              <h3>${escapeHtml(source.name || source.id)}</h3>
              <p class="muted">${escapeHtml(source.id)}</p>
            </div>
            <span class="status-badge ${statusClass}">${escapeHtml(statusLabel)}</span>
          </div>
          <label>
            Lokaler Pfad
            <input type="text" data-files-path="${escapeHtml(source.id)}" value="${escapeHtml(source.path || "")}">
          </label>
          <label>
            Patterns
            <input type="text" data-files-patterns="${escapeHtml(source.id)}" value="${escapeHtml(patterns)}">
          </label>
          <div class="docs-stats">
            <div class="docs-stat">
              <strong>Dateien</strong>
              <span>${escapeHtml(sourceHealth?.file_count ?? "-")}</span>
            </div>
            <div class="docs-stat">
              <strong>Pfad</strong>
              <span>${escapeHtml(sourceHealth?.path || source.path || "-")}</span>
            </div>
          </div>
        </article>
      `;
    })
    .join("");
}

function filesManagerConfig() {
  const config = normalizeFilesSources(state.filesSourcesConfig);
  const next = deepClone(config);
  for (const source of next.sources) {
    const pathInput = el.filesSourcesManager.querySelector(`[data-files-path="${source.id}"]`);
    const patternsInput = el.filesSourcesManager.querySelector(`[data-files-patterns="${source.id}"]`);
    if (pathInput) {
      source.path = pathInput.value.trim();
    }
    if (patternsInput) {
      source.patterns = patternsInput.value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
    }
  }
  return next;
}

function filesConfigFingerprint(config) {
  const sources = normalizeFilesSources(config).sources.map((item) => ({
    id: item.id || "",
    name: item.name || "",
    path: item.path || "",
    patterns: Array.isArray(item.patterns) ? item.patterns : [],
  }));
  return JSON.stringify(sources);
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

function renderMcpManager() {
  const config = normalizeMcpsConfig(state.mcpsConfig);
  el.mcpManager.innerHTML = config.mcps
    .map((item, index) => {
      const roots = Array.isArray(item.roots) ? JSON.stringify(item.roots, null, 2) : "[]";
      const patterns = Array.isArray(item.patterns) ? item.patterns.join(", ") : "";
      return `
        <article class="docs-card mcp-manager-grid" data-mcp-index="${index}">
          <div class="docs-card-head">
            <div>
              <h3>${escapeHtml(item.name || item.id || `MCP ${index + 1}`)}</h3>
              <p class="muted">${escapeHtml(item.kind || "unknown")} / ${escapeHtml(item.id || "-")}</p>
            </div>
            <div class="button-row">
              ${item.kind === "remote_http" ? `<button type="button" class="secondary" data-mcp-action="handshake" data-mcp-id="${escapeHtml(item.id || "")}">Handshake</button>` : ""}
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
          ${item.kind === "docs" ? `
            <label>Pfad<input type="text" data-field="path" value="${escapeHtml(item.path || "")}"></label>
            <label>Patterns<input type="text" data-field="patterns" value="${escapeHtml(patterns)}"></label>
          ` : ""}
          ${item.kind === "files" ? `
            <label>Roots JSON<textarea data-field="roots" rows="8">${escapeHtml(roots)}</textarea></label>
          ` : ""}
          ${item.kind === "netbox" ? `
            <div class="panel-grid">
              <label>Base URL<input type="text" data-field="base_url" value="${escapeHtml(item.base_url || "")}"></label>
              <label>Token Env<input type="text" data-field="token_env" value="${escapeHtml(item.token_env || "")}"></label>
            </div>
            <div class="panel-grid">
              <label>Timeout<input type="text" data-field="timeout_seconds" value="${escapeHtml(item.timeout_seconds ?? "")}"></label>
              <label>Cache TTL<input type="text" data-field="cache_ttl_seconds" value="${escapeHtml(item.cache_ttl_seconds ?? "")}"></label>
            </div>
          ` : ""}
          ${item.kind === "remote_http" ? `
            <div class="panel-grid">
              <label>Base URL<input type="text" data-field="base_url" value="${escapeHtml(item.base_url || "")}"></label>
              <label>Execute Path<input type="text" data-field="execute_path" value="${escapeHtml(item.execute_path || "/execute")}"></label>
            </div>
            <div class="panel-grid">
              <label>Health Path<input type="text" data-field="health_path" value="${escapeHtml(item.health_path || "/health")}"></label>
              <label>Bearer Token Env<input type="text" data-field="bearer_token_env" value="${escapeHtml(item.bearer_token_env || "")}"></label>
            </div>
            <label>Timeout<input type="text" data-field="timeout_seconds" value="${escapeHtml(item.timeout_seconds ?? "")}"></label>
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
    if (kind === "docs") {
      item.path = card.querySelector('[data-field="path"]').value.trim();
      item.patterns = card.querySelector('[data-field="patterns"]').value.split(",").map((value) => value.trim()).filter(Boolean);
    } else if (kind === "files") {
      item.roots = JSON.parse(card.querySelector('[data-field="roots"]').value || "[]");
    } else if (kind === "netbox") {
      item.base_url = card.querySelector('[data-field="base_url"]').value.trim();
      item.token_env = card.querySelector('[data-field="token_env"]').value.trim();
      item.timeout_seconds = Number(card.querySelector('[data-field="timeout_seconds"]').value || 0) || 12;
      item.cache_ttl_seconds = Number(card.querySelector('[data-field="cache_ttl_seconds"]').value || 0) || 45;
    } else if (kind === "remote_http") {
      item.base_url = card.querySelector('[data-field="base_url"]').value.trim();
      item.execute_path = card.querySelector('[data-field="execute_path"]').value.trim() || "/execute";
      item.health_path = card.querySelector('[data-field="health_path"]').value.trim() || "/health";
      item.bearer_token_env = card.querySelector('[data-field="bearer_token_env"]').value.trim();
      item.timeout_seconds = Number(card.querySelector('[data-field="timeout_seconds"]').value || 0) || 15;
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
  if (state.session?.is_admin && state.adminLoaded) {
    renderDocsManager();
    renderFilesManager();
    renderMcpManager();
    syncPersonaEditor();
  }
}

async function loadDocsCatalog() {
  const data = await fetchJson("/api/docs");
  state.docsCatalog = normalizeDocsCatalog(data.items || []);
  renderDocsCatalog();
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
    const [runtime, docsSources, filesSources, mcpsConfig, usersConfig, systemPrompt, personas] = await Promise.all([
      fetchJson("/api/admin/runtime"),
      fetchJson("/api/admin/docs-sources"),
      fetchJson("/api/admin/files-sources"),
      fetchJson("/api/admin/mcps"),
      fetchJson("/api/admin/users"),
      fetchJson("/api/admin/system-prompt"),
      fetchJson("/api/admin/personas"),
    ]);
    state.docsSourcesConfig = normalizeDocsSources(docsSources.config || { sources: [] });
    state.filesSourcesConfig = normalizeFilesSources(filesSources.config || { sources: [] });
    state.mcpsConfig = normalizeMcpsConfig(mcpsConfig.config || { mcps: [] });
    state.usersConfig = normalizeUsersConfig(usersConfig.config || { groups: [], users: [] });
    state.personas = normalizePersonas(personas.items || []);
    el.runtimeJson.value = JSON.stringify(runtime.config || {}, null, 2);
    syncLlmFormFromRuntime(runtime.config || {});
    syncNetboxFormFromRuntime(runtime.config || {});
    syncDocsSourcesEditor(state.docsSourcesConfig);
    syncFilesSourcesEditor(state.filesSourcesConfig);
    el.mcpsJson.value = JSON.stringify(state.mcpsConfig, null, 2);
    el.usersJson.value = JSON.stringify(state.usersConfig, null, 2);
    el.systemPrompt.value = systemPrompt.prompt || "";
    renderDocsManager();
    renderFilesManager();
    renderMcpManager();
    syncPersonaEditor();
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
  if (state.session?.is_admin && state.adminLoaded) {
    renderDocsManager();
    renderFilesManager();
  }
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

async function persistDocsSourcesConfig(config, { reloadAdmin = true, silent = false } = {}) {
  const safeConfig = normalizeDocsSources(config);
  const data = await fetchJson("/api/admin/docs-sources", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sources: safeConfig.sources }),
  });
  state.docsSourcesConfig = safeConfig;
  syncDocsSourcesEditor(safeConfig);
  if (!silent) {
    el.controlOutput.textContent = JSON.stringify(data, null, 2);
  }
  await refreshAppState({ reloadAdmin });
  return data;
}

async function persistFilesSourcesConfig(config, { reloadAdmin = true, silent = false } = {}) {
  const safeConfig = normalizeFilesSources(config);
  const data = await fetchJson("/api/admin/files-sources", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sources: safeConfig.sources }),
  });
  state.filesSourcesConfig = safeConfig;
  syncFilesSourcesEditor(safeConfig);
  if (!silent) {
    el.controlOutput.textContent = JSON.stringify(data, null, 2);
  }
  await refreshAppState({ reloadAdmin });
  return data;
}

async function saveDocsManager({ silent = false } = {}) {
  const nextConfig = docsManagerConfig();
  if (docsConfigFingerprint(nextConfig) === docsConfigFingerprint(state.docsSourcesConfig)) {
    syncDocsSourcesEditor(nextConfig);
    if (!silent) {
      el.controlOutput.textContent = JSON.stringify({ success: true, message: "Docs-Pfade unveraendert." }, null, 2);
    }
    return;
  }
  await persistDocsSourcesConfig(nextConfig, { reloadAdmin: true, silent });
}

async function saveFilesManager({ silent = false } = {}) {
  const nextConfig = filesManagerConfig();
  if (filesConfigFingerprint(nextConfig) === filesConfigFingerprint(state.filesSourcesConfig)) {
    syncFilesSourcesEditor(nextConfig);
    if (!silent) {
      el.controlOutput.textContent = JSON.stringify({ success: true, message: "File-Roots unveraendert." }, null, 2);
    }
    return;
  }
  await persistFilesSourcesConfig(nextConfig, { reloadAdmin: true, silent });
}

async function uploadDocsArchive(sourceId) {
  const fileInput = el.docsSourcesManager.querySelector(`[data-docs-upload="${sourceId}"]`);
  if (!fileInput?.files?.length) {
    throw new Error("Bitte zuerst eine ZIP-Datei auswaehlen.");
  }
  await saveDocsManager({ silent: true });
  const formData = new FormData();
  formData.append("archive", fileInput.files[0]);
  formData.append("reindex", "true");
  const data = await fetchJson(`/api/admin/docs-sources/${sourceId}/upload`, {
    method: "POST",
    body: formData,
  });
  fileInput.value = "";
  el.controlOutput.textContent = JSON.stringify(data, null, 2);
  await refreshAppState({ reloadAdmin: true });
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

async function runNetboxQuickQuery() {
  const target = (state.session?.mcps || []).find((item) => item.kind === "netbox");
  if (!target) {
    el.netboxOutput.textContent = "Kein erlaubtes NetBox-MCP fuer diesen User.";
    return;
  }
  try {
    const data = await runMcp(target.id, "get_objects", {
      object_type: el.netboxObjectType.value,
      filters: {
        q: el.netboxQuery.value,
        limit: 10,
      },
    });
    el.netboxOutput.textContent = JSON.stringify(data, null, 2);
    setActiveView("tools");
    await loadPerformance();
  } catch (error) {
    el.netboxOutput.textContent = String(error.message || error);
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

async function saveNetboxSettings() {
  let config = {};
  try {
    config = parseRuntimeConfig();
  } catch (error) {
    el.controlOutput.textContent = `Runtime JSON ungueltig: ${error.message}`;
    return;
  }
  const nextConfig = applyNetboxFormToRuntime(config);
  el.runtimeJson.value = JSON.stringify(nextConfig, null, 2);
  await saveRuntimeConfig();
}

async function probeNetboxConfig() {
  const timeoutSeconds = Number(el.netboxTimeoutSeconds.value);
  const data = await fetchJson("/api/admin/netbox-probe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      base_url: el.netboxBaseUrl.value.trim() || null,
      token: el.netboxToken.value.trim() || null,
      token_env: el.netboxTokenEnv.value.trim() || null,
      timeout_seconds: Number.isFinite(timeoutSeconds) && timeoutSeconds > 0 ? timeoutSeconds : null,
    }),
  });
  el.netboxProbeOutput.textContent = JSON.stringify(data, null, 2);
}

async function loadNetboxFieldExplorer() {
  const sampleLimit = Number(el.netboxExplorerSampleLimit.value);
  const data = await fetchJson("/api/admin/netbox-explorer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      object_type: el.netboxExplorerObjectType.value,
      query: el.netboxExplorerQuery.value.trim(),
      sample_limit: Number.isFinite(sampleLimit) && sampleLimit > 0 ? Math.round(sampleLimit) : 1,
    }),
  });
  el.netboxExplorerOutput.textContent = JSON.stringify(data, null, 2);
}

async function downloadNetboxBundle() {
  const sampleLimit = Number(el.netboxExplorerSampleLimit.value);
  const payload = {
    object_type: el.netboxExplorerObjectType.value,
    query: el.netboxExplorerQuery.value.trim(),
    sample_limit: Number.isFinite(sampleLimit) && sampleLimit > 0 ? Math.round(sampleLimit) : 1,
  };
  const response = await fetch("/api/admin/netbox-bundle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || "netbox_bundle_failed");
  }
  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename=\"?([^\";]+)\"?/i);
  const filename = match?.[1] || "netbox-mcp-bundle.zip";
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
  el.netboxExplorerOutput.textContent = JSON.stringify(
    {
      success: true,
      message: "Diagnose-Bundle heruntergeladen.",
      filename,
      object_type: payload.object_type,
      query: payload.query,
      sample_limit: payload.sample_limit,
    },
    null,
    2,
  );
}

async function saveDocsSourcesRaw() {
  let config = {};
  try {
    config = JSON.parse(el.docsSourcesJson.value || "{}");
  } catch (error) {
    el.controlOutput.textContent = `Docs Sources JSON ungueltig: ${error.message}`;
    return;
  }
  state.docsSourcesConfig = normalizeDocsSources(config);
  await persistDocsSourcesConfig(state.docsSourcesConfig, { reloadAdmin: true, silent: false });
}

async function saveFilesSourcesRaw() {
  let config = {};
  try {
    config = JSON.parse(el.filesSourcesJson.value || "{}");
  } catch (error) {
    el.controlOutput.textContent = `Files Sources JSON ungueltig: ${error.message}`;
    return;
  }
  state.filesSourcesConfig = normalizeFilesSources(config);
  await persistFilesSourcesConfig(state.filesSourcesConfig, { reloadAdmin: true, silent: false });
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
el.runNetbox.addEventListener("click", runNetboxQuickQuery);

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

el.saveNetboxSettings.addEventListener("click", async () => {
  try {
    await saveNetboxSettings();
  } catch (error) {
    el.controlOutput.textContent = String(error.message || error);
  }
});

el.probeNetbox.addEventListener("click", async () => {
  try {
    await probeNetboxConfig();
  } catch (error) {
    el.netboxProbeOutput.textContent = String(error.message || error);
  }
});

el.exploreNetboxFields.addEventListener("click", async () => {
  try {
    await loadNetboxFieldExplorer();
  } catch (error) {
    el.netboxExplorerOutput.textContent = String(error.message || error);
  }
});

el.downloadNetboxBundle.addEventListener("click", async () => {
  try {
    await downloadNetboxBundle();
  } catch (error) {
    el.netboxExplorerOutput.textContent = String(error.message || error);
  }
});

el.saveDocsSources.addEventListener("click", async () => {
  try {
    await saveDocsSourcesRaw();
  } catch (error) {
    el.controlOutput.textContent = String(error.message || error);
  }
});

el.saveDocsManager.addEventListener("click", async () => {
  try {
    await saveDocsManager();
  } catch (error) {
    el.controlOutput.textContent = String(error.message || error);
  }
});

el.saveFilesManager.addEventListener("click", async () => {
  try {
    await saveFilesManager();
  } catch (error) {
    el.controlOutput.textContent = String(error.message || error);
  }
});

el.docsSourcesManager.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-docs-action]");
  if (!button) return;
  const sourceId = button.dataset.sourceId;
  const action = button.dataset.docsAction;
  try {
    if (action === "upload") {
      await uploadDocsArchive(sourceId);
      return;
    }
    if (action === "reindex") {
      await saveDocsManager({ silent: true });
      const data = await runMcp(sourceId, "reindex", {});
      el.controlOutput.textContent = JSON.stringify(data, null, 2);
      await refreshAppState({ reloadAdmin: true });
    }
  } catch (error) {
    el.controlOutput.textContent = String(error.message || error);
  }
});

el.saveSystemPrompt.addEventListener("click", async () => {
  try {
    await saveSystemPrompt();
  } catch (error) {
    el.controlOutput.textContent = String(error.message || error);
  }
});

el.saveFilesSources.addEventListener("click", async () => {
  try {
    await saveFilesSourcesRaw();
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

for (const [button, kind] of [
  [el.addMcpDocs, "docs"],
  [el.addMcpFiles, "files"],
  [el.addMcpNetbox, "netbox"],
  [el.addMcpRemote, "remote_http"],
]) {
  button.addEventListener("click", () => {
    state.mcpsConfig = normalizeMcpsConfig(state.mcpsConfig);
    state.mcpsConfig.mcps.push(defaultMcpByKind(kind));
    el.mcpsJson.value = JSON.stringify(state.mcpsConfig, null, 2);
    renderMcpManager();
  });
}

el.saveUsers.addEventListener("click", async () => {
  try {
    await saveUsersRaw();
  } catch (error) {
    el.controlOutput.textContent = String(error.message || error);
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
  const handshakeButton = event.target.closest('button[data-mcp-action="handshake"]');
  if (handshakeButton) {
    try {
      await saveMcpManager();
      await handshakeRemoteMcp(handshakeButton.dataset.mcpId);
    } catch (error) {
      el.controlOutput.textContent = String(error.message || error);
    }
  }
});

el.docsNav.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-doc-id]");
  if (!button) return;
  state.activeDocId = button.dataset.docId;
  renderDocsCatalog();
});

(async function bootstrap() {
  try {
    loadUiPreferences();
    await ensureSession();
    setActiveView("overview");
    await loadConfig();
    await loadDocsCatalog();
    await refreshHealth();
    await loadPerformance();
    if (state.session?.is_admin) {
      await loadAdminEditors();
    }
  } catch (error) {
    showLogin("");
  }
})();
