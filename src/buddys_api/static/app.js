const SESSION_STORAGE_KEY = "buddysAccessToken";
const VOICE_UNSUPPORTED_COPY = "Voice capture is not available in this browser.";
const UNRECOGNIZED_COPY = "I heard this but could not structure it yet";
const DEFAULT_CAPTURE_EMPTY = "No confirmed state yet.";
const DEFAULT_PENDING_EMPTY = "No pending proposals.";
const DEFAULT_QUERY_EMPTY = "No state-memory query yet.";
const BUDDYS_BOOTSTRAP = window.BUDDYS_BOOTSTRAP || { inviteRequired: false };
const PROVIDER_SETTINGS_DEFAULT = {
  providerId: "minimax-openai",
  displayName: "MiniMax OpenAI Compatible",
  defaultModel: "MiniMax-M3",
  configured: false,
  status: "unconfigured",
  loaded: false,
  errorMessage: "",
};

const state = {
  auth: {
    accessToken: null,
    user: null,
  },
  workspace: {
    buddyId: null,
    buddies: [],
    agents: [],
    confirmedItems: [],
    pendingProposals: [],
    latestQuery: null,
    proactiveHint: null,
    summary: {},
    traces: [],
    costSummary: {},
    stateRevision: 0,
  },
  ui: {
    selectedProposalId: null,
    detailsOpen: false,
    dismissedHintKey: null,
    proactiveHint: null,
    provider: { ...PROVIDER_SETTINGS_DEFAULT },
    photo: {
      base64: null,
      mediaType: null,
      previewUrl: null,
      fileName: null,
    },
    voice: {
      transcript: "",
      status: "idle",
      supported: false,
      recording: false,
    },
  },
};

const $ = (id) => document.getElementById(id);

function isAuthenticated() {
  return Boolean(state.auth.accessToken && state.auth.user);
}

function authHeaders(extraHeaders = {}) {
  const headers = { ...extraHeaders };
  if (state.auth.accessToken) {
    headers.Authorization = `Bearer ${state.auth.accessToken}`;
  }
  return headers;
}

async function requestJson(url, options = {}) {
  const headers = options.body !== undefined ? { "content-type": "application/json" } : {};
  const response = await fetch(url, {
    ...options,
    headers: authHeaders({ ...headers, ...(options.headers || {}) }),
  });
  if (response.status === 204) {
    return null;
  }
  const text = await response.text();
  const payload = text ? safeJson(text) : null;
  if (!response.ok) {
    const detailCode = payload?.detail?.code;
    const detailText = payload?.detail?.message || detailCode || payload?.detail;
    const error = new Error(detailText || `${response.status} ${url}`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

function safeJson(text) {
  try {
    return JSON.parse(text);
  } catch (error) {
    return { detail: text };
  }
}

function setAuthStatus(message, tone = "muted") {
  const node = $("authStatus");
  node.textContent = message;
  node.dataset.tone = tone;
}

function setWorkspaceStatus(message) {
  $("stateMemoryWorkspaceStatus").textContent = message;
}

function formatQuantity(quantity, unit) {
  if (quantity === null || quantity === undefined) {
    return unit || "-";
  }
  const normalized = Number.isInteger(quantity) ? String(quantity) : String(quantity);
  return `${normalized}${unit || ""}`;
}

function money(value) {
  return `¥${value.toFixed(4)}`;
}

function costEventCny(costSummary) {
  const usd =
    (costSummary.model_cost_usd || 0) + (costSummary.tool_cost_usd || 0) + (costSummary.log_cost_usd || 0);
  return usd * 7.25;
}

function renderTextList(targetId, items, emptyText, formatter) {
  const list = $(targetId);
  list.replaceChildren();
  if (!items.length) {
    const emptyItem = document.createElement("li");
    emptyItem.textContent = emptyText;
    list.appendChild(emptyItem);
    return;
  }
  items.forEach((item) => {
    const listItem = document.createElement("li");
    listItem.textContent = formatter(item);
    list.appendChild(listItem);
  });
}

function appendLine(container, text, className = "") {
  const line = document.createElement("span");
  if (className) {
    line.className = className;
  }
  line.textContent = text;
  container.appendChild(line);
}

function selectedBuddy() {
  return state.workspace.buddies.find((buddy) => buddy.buddy_id === state.workspace.buddyId) || null;
}

function selectedProposal() {
  return (
    state.workspace.pendingProposals.find((proposal) => proposal.proposal_id === state.ui.selectedProposalId) || null
  );
}

function saveSession(accessToken, user) {
  state.auth.accessToken = accessToken;
  state.auth.user = user;
  localStorage.setItem(SESSION_STORAGE_KEY, accessToken);
}

function clearSession() {
  state.auth.accessToken = null;
  state.auth.user = null;
  state.workspace.buddyId = null;
  state.workspace.buddies = [];
  state.workspace.agents = [];
  state.workspace.confirmedItems = [];
  state.workspace.pendingProposals = [];
  state.workspace.latestQuery = null;
  state.workspace.proactiveHint = null;
  state.workspace.summary = {};
  state.workspace.traces = [];
  state.workspace.costSummary = {};
  state.workspace.stateRevision = 0;
  state.ui.selectedProposalId = null;
  state.ui.detailsOpen = false;
  state.ui.dismissedHintKey = null;
  state.ui.proactiveHint = null;
  state.ui.provider = { ...PROVIDER_SETTINGS_DEFAULT };
  state.ui.photo = { base64: null, mediaType: null, previewUrl: null, fileName: null };
  state.ui.voice = { transcript: "", status: "idle", supported: voiceRecognitionSupported(), recording: false };
  localStorage.removeItem(SESSION_STORAGE_KEY);
  $("authPasswordInput").value = "";
  $("authDisplayNameInput").value = "";
  $("authInviteCodeInput").value = "";
  renderExperienceShell();
}

function syncAuthControls() {
  const signedIn = isAuthenticated();
  const hasBuddy = Boolean(state.workspace.buddyId);
  const hasPhoto = Boolean(state.ui.photo.base64);
  const hasVoiceTranscript = Boolean(state.ui.voice.transcript.trim());
  const providerSettingsUnavailable = state.ui.provider.status === "unavailable";
  const canSaveProviderSettings =
    signedIn &&
    state.ui.provider.status !== "unavailable" &&
    Boolean(state.ui.provider.providerId);
  $("authRegisterButton").disabled = signedIn;
  $("authLoginButton").disabled = signedIn;
  $("authLogoutButton").disabled = !signedIn;
  $("authBuddySelect").disabled = !signedIn || !state.workspace.buddies.length;
  $("createMyBuddyButton").disabled = !signedIn || hasBuddy;
  $("captureTextInput").disabled = !hasBuddy;
  $("captureSubmitButton").disabled = !hasBuddy;
  $("photoFileInput").disabled = !hasBuddy;
  $("clearPhotoSelectionButton").disabled = !hasBuddy || !hasPhoto;
  $("submitPhotoCaptureButton").disabled = !hasBuddy || !hasPhoto;
  $("voiceTranscriptInput").disabled = !hasBuddy;
  $("startVoiceCaptureButton").disabled = !hasBuddy || !state.ui.voice.supported || state.ui.voice.recording;
  $("retryVoiceCaptureButton").disabled = !hasBuddy || state.ui.voice.recording;
  $("submitVoiceTranscriptButton").disabled = !hasBuddy || !hasVoiceTranscript;
  $("queryTextInput").disabled = !hasBuddy;
  $("querySubmitButton").disabled = !hasBuddy;
  $("proposalCorrectionInput").disabled = !hasBuddy || !selectedProposal();
  $("submitCorrectionButton").disabled = !hasBuddy || !selectedProposal();
  $("providerDisplayNameInput").disabled = !signedIn;
  $("providerModelInput").disabled = !signedIn;
  $("saveProviderSettingsButton").disabled = providerSettingsUnavailable || !canSaveProviderSettings;
}

function renderAuthRail() {
  if (!isAuthenticated()) {
    setAuthStatus(
      BUDDYS_BOOTSTRAP.inviteRequired
        ? "Signed out. Registration is invite-only right now."
        : "Signed out. Login to use state memory.",
    );
  }
  $("authInviteCodeInput").placeholder = BUDDYS_BOOTSTRAP.inviteRequired
    ? "Invite code required"
    : "Optional unless invite-only is enabled";

  const select = $("authBuddySelect");
  select.replaceChildren();
  if (!state.workspace.buddies.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = isAuthenticated() ? "No Buddy yet" : "Login to see your Buddy";
    select.appendChild(option);
  } else {
    state.workspace.buddies.forEach((buddy) => {
      const option = document.createElement("option");
      option.value = buddy.buddy_id;
      option.textContent = `${buddy.name} · ${buddy.space_id}`;
      select.appendChild(option);
    });
    select.value = state.workspace.buddyId || state.workspace.buddies[0].buddy_id;
  }

  syncAuthControls();
}

function renderBuddyHero() {
  const buddy = selectedBuddy();
  if (!buddy) {
    $("buddyGreeting").textContent = "Buddy is ready to learn your space";
    $("buddyNameHeading").textContent = "My Buddy";
    $("buddySummaryLine").textContent =
      "Tell Buddy what you bought or used, then ask what is still at home.";
    $("overviewTitle").textContent = "My Buddy";
    $("buddySpace").textContent = "Home";
    $("buddyState").textContent = isAuthenticated() ? "awaiting setup" : "signed out";
    return;
  }
  $("buddyGreeting").textContent = `Hi, I am watching ${buddy.space_id} for you.`;
  $("buddyNameHeading").textContent = buddy.name;
  $("buddySummaryLine").textContent = "Capture changes, review them once, then ask with evidence.";
  $("overviewTitle").textContent = buddy.name;
  $("buddySpace").textContent = buddy.space_id;
  $("buddyState").textContent = buddy.status;
}

function renderConfirmedState() {
  const summary = state.workspace.summary || {};
  $("stateMemoryConfirmedCount").textContent = String(
    summary.confirmed_item_count || state.workspace.confirmedItems.length || 0,
  );
  $("stateMemoryPendingCount").textContent = String(
    summary.pending_proposal_count || state.workspace.pendingProposals.length || 0,
  );
  $("stateMemoryLastUpdated").textContent = summary.last_state_change_at || "-";

  if (!isAuthenticated()) {
    setWorkspaceStatus("Login and select a Buddy before submitting state-memory actions.");
  } else if (!state.workspace.buddyId) {
    setWorkspaceStatus("Create your first Buddy to unlock capture, query, and proposal review.");
  } else {
    setWorkspaceStatus(`Workspace revision ${state.workspace.stateRevision}.`);
  }

  renderTextList("stateMemoryConfirmedList", state.workspace.confirmedItems, DEFAULT_CAPTURE_EMPTY, (item) => {
    return `${item.name} · ${formatQuantity(item.quantity, item.unit)} · ${item.status}`;
  });
}

function renderCaptureComposer() {
  $("captureTextInput").placeholder = "例如：我买了五个鸡蛋和一瓶牛奶";
  $("voiceUnsupportedCopy").textContent = state.ui.voice.supported ? "" : VOICE_UNSUPPORTED_COPY;
  $("voiceCaptureStatus").textContent = voiceStatusCopy();
  $("voiceTranscriptInput").value = state.ui.voice.transcript;
  $("photoSelectionStatus").textContent = state.ui.photo.fileName
    ? `Selected photo: ${state.ui.photo.fileName}`
    : "No photo selected.";
  $("photoPreviewImage").hidden = !state.ui.photo.previewUrl;
  if (state.ui.photo.previewUrl) {
    $("photoPreviewImage").src = state.ui.photo.previewUrl;
  } else {
    $("photoPreviewImage").removeAttribute("src");
  }
  syncAuthControls();
}

function renderProviderSettings() {
  const provider = state.ui.provider;
  $("providerSettingsPanel").dataset.status = provider.status || "signed_out";
  $("providerDisplayNameInput").value = provider.displayName;
  $("providerModelInput").value = provider.defaultModel;
  $("providerSecretNotice").dataset.tone = provider.status === "unavailable" ? "error" : provider.configured ? "ok" : "muted";

  if (!isAuthenticated()) {
    $("providerStatusBadge").textContent = "Signed out";
    $("providerSettingsStatus").textContent = "Login to configure provider settings.";
    syncAuthControls();
    return;
  }

  if (provider.status === "unavailable") {
    $("providerStatusBadge").textContent = "Unavailable";
    $("providerSettingsStatus").textContent = provider.errorMessage || "Provider settings are temporarily unavailable.";
  } else if (!provider.loaded) {
    $("providerStatusBadge").textContent = "Loading";
    $("providerSettingsStatus").textContent = "Loading provider settings...";
  } else if (provider.configured) {
    $("providerStatusBadge").textContent = "Configured";
    $("providerSettingsStatus").textContent = `${provider.displayName} is configured for this account.`;
  } else {
    $("providerStatusBadge").textContent = "Unconfigured";
    $("providerSettingsStatus").textContent = "No account-level provider override yet. Save safe metadata to configure one.";
  }
  syncAuthControls();
}

function formatAgentRole(role) {
  return (
    {
      "runtime": "Runtime",
      "hardware_simulator": "Hardware simulator",
      "cost_agent": "Cost agent",
      "verifier": "Verifier",
      "doc_progress": "Doc progress",
      "adapter": "Adapter",
    }[role] || role
  );
}

function whitelistAgentSummary(agent) {
  return {
    agent_id: agent.agent_id,
    name: agent.name,
    role: agent.role,
    status: agent.status,
    version: agent.version,
    last_seen: agent.last_seen,
  };
}

function renderAgentManagement() {
  const list = $("agentManagementList");
  list.replaceChildren();

  if (!isAuthenticated()) {
    $("agentManagementStatus").textContent = "Login to view agent summaries.";
    const emptyItem = document.createElement("li");
    emptyItem.textContent = "No agent summaries yet.";
    list.appendChild(emptyItem);
    return;
  }

  const agents = state.workspace.agents || [];
  $("agentManagementStatus").textContent = agents.length
    ? `${agents.length} agent summaries for this account.`
    : "No agent summaries yet.";

  if (!agents.length) {
    const emptyItem = document.createElement("li");
    emptyItem.textContent = "No agent summaries yet.";
    list.appendChild(emptyItem);
    return;
  }

  agents.forEach((agent) => {
    const item = document.createElement("li");
    appendLine(item, `${agent.name} · ${formatAgentRole(agent.role)} · ${agent.status}`);
    appendLine(item, `Version: ${agent.version || "-"}`, "evidence-line");
    appendLine(item, `Heartbeat: ${agent.last_seen || "Never"}`, "evidence-line");
    list.appendChild(item);
  });
}

function voiceRecognitionSupported() {
  return Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
}

function voiceStatusCopy() {
  if (state.ui.voice.recording) {
    return "Listening for one short pantry update...";
  }
  if (state.ui.voice.status === "captured") {
    return "Voice transcript ready for review.";
  }
  if (state.ui.voice.status === "error") {
    return "Voice capture failed. Retry or type the transcript manually.";
  }
  return "Voice transcript is idle.";
}

function clearPhotoSelection() {
  state.ui.photo = { base64: null, mediaType: null, previewUrl: null, fileName: null };
  $("photoFileInput").value = "";
  renderCaptureComposer();
}

function handlePhotoSelected(event) {
  const file = event.target.files?.[0];
  if (!file) {
    clearPhotoSelection();
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    const result = String(reader.result || "");
    const [, mediaType = "", base64 = ""] = result.match(/^data:(.*?);base64,(.*)$/) || [];
    state.ui.photo = {
      base64,
      mediaType,
      previewUrl: result,
      fileName: file.name,
    };
    renderCaptureComposer();
  };
  reader.onerror = () => {
    clearPhotoSelection();
    setWorkspaceStatus("Photo preview failed. Choose another image.");
  };
  reader.readAsDataURL(file);
}

function startVoiceCapture() {
  const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognitionCtor) {
    state.ui.voice.supported = false;
    state.ui.voice.status = "error";
    renderCaptureComposer();
    return;
  }
  const recognition = new SpeechRecognitionCtor();
  recognition.lang = "zh-CN";
  recognition.continuous = false;
  recognition.interimResults = false;
  state.ui.voice.supported = true;
  state.ui.voice.recording = true;
  state.ui.voice.status = "recording";
  renderCaptureComposer();
  recognition.onresult = (event) => {
    const transcript = Array.from(event.results || [])
      .flatMap((result) => Array.from(result))
      .map((item) => item.transcript || "")
      .join("")
      .trim();
    state.ui.voice.transcript = transcript;
    state.ui.voice.recording = false;
    state.ui.voice.status = transcript ? "captured" : "idle";
    renderCaptureComposer();
  };
  recognition.onerror = () => {
    state.ui.voice.recording = false;
    state.ui.voice.status = "error";
    renderCaptureComposer();
  };
  recognition.onend = () => {
    state.ui.voice.recording = false;
    renderCaptureComposer();
  };
  recognition.start();
}

function retryVoiceCapture() {
  state.ui.voice.transcript = "";
  state.ui.voice.status = "idle";
  renderCaptureComposer();
  if (state.ui.voice.supported) {
    startVoiceCapture();
  }
}

function renderUnrecognizedList(parent, proposal) {
  if (!proposal.unrecognized?.length) {
    return;
  }
  const block = document.createElement("div");
  block.className = "unrecognized-block";
  const title = document.createElement("strong");
  title.textContent = UNRECOGNIZED_COPY;
  const list = document.createElement("ul");
  list.className = "inline-list";
  proposal.unrecognized.forEach((segment) => {
    const item = document.createElement("li");
    item.textContent = segment;
    list.appendChild(item);
  });
  block.appendChild(title);
  block.appendChild(list);
  parent.appendChild(block);
}

function renderProposalInbox() {
  renderTextList("stateMemoryPendingList", state.workspace.pendingProposals, DEFAULT_PENDING_EMPTY, (proposal) => {
    return `${proposal.content} · ${proposal.source}`;
  });

  const list = $("proposalReviewList");
  list.replaceChildren();
  if (!state.workspace.pendingProposals.length) {
    const emptyItem = document.createElement("li");
    emptyItem.textContent = "No proposal selected for review.";
    list.appendChild(emptyItem);
    $("proposalCorrectionInput").value = "";
    state.ui.selectedProposalId = null;
    syncAuthControls();
    return;
  }

  state.workspace.pendingProposals.forEach((proposal) => {
    const item = document.createElement("li");
    item.className = "proposal-card";

    const title = document.createElement("strong");
    title.textContent = proposal.content;
    item.appendChild(title);

    const meta = document.createElement("p");
    meta.className = "support-copy";
    meta.textContent = `${proposal.source} · ${proposal.deltas.length} structured item(s)`;
    item.appendChild(meta);

    renderUnrecognizedList(item, proposal);

    const actions = document.createElement("div");
    actions.className = "button-row";

    const selectButton = document.createElement("button");
    selectButton.type = "button";
    selectButton.className = "ghost-button";
    selectButton.textContent = "Edit correction";
    selectButton.addEventListener("click", () => {
      state.ui.selectedProposalId = proposal.proposal_id;
      $("proposalCorrectionInput").value = JSON.stringify(proposal.deltas, null, 2);
      setWorkspaceStatus(`Loaded correction draft for ${proposal.content}.`);
      syncAuthControls();
    });

    const confirmButton = document.createElement("button");
    confirmButton.type = "button";
    confirmButton.className = "primary-button";
    confirmButton.textContent = "Confirm";
    confirmButton.addEventListener("click", () => confirmProposal(proposal.proposal_id));

    const rejectButton = document.createElement("button");
    rejectButton.type = "button";
    rejectButton.className = "secondary-button";
    rejectButton.textContent = "Reject";
    rejectButton.addEventListener("click", () => rejectProposal(proposal.proposal_id));

    actions.appendChild(selectButton);
    actions.appendChild(confirmButton);
    actions.appendChild(rejectButton);
    item.appendChild(actions);
    list.appendChild(item);
  });

  if (!selectedProposal()) {
    const firstProposal = state.workspace.pendingProposals[0];
    state.ui.selectedProposalId = firstProposal.proposal_id;
    $("proposalCorrectionInput").value = JSON.stringify(firstProposal.deltas, null, 2);
  }
  syncAuthControls();
}

function renderLatestAnswer() {
  const latestQuery = state.workspace.latestQuery;
  if (!latestQuery) {
    $("stateMemoryQuerySummary").textContent = DEFAULT_QUERY_EMPTY;
    $("stateMemoryQueryMeta").textContent = "Evidence will appear here once a state-memory query has been asked.";
    renderTextList("stateMemoryEvidenceList", [], "No evidence items captured.", () => "");
    return;
  }
  $("stateMemoryQuerySummary").textContent = latestQuery.summary;
  $("stateMemoryQueryMeta").textContent = latestQuery.missing_items?.length
    ? `${latestQuery.question} · missing ${latestQuery.missing_items.join(" / ")}`
    : `${latestQuery.question} · evidence ready`;
  renderTextList(
    "stateMemoryEvidenceList",
    latestQuery.evidence_items || [],
    latestQuery.evidence_item_ids?.length ? "Evidence item details unavailable." : "No evidence items captured.",
    (item) =>
      `${item.name} · ${formatQuantity(item.quantity, item.unit)} · ${item.status} · ${item.source} · ${item.last_seen_at}`,
  );
}

function currentProactiveHint() {
  const hint = state.workspace.proactiveHint;
  if (!hint) {
    return null;
  }
  const hintKey = `${hint.kind}:${hint.basis?.item_names?.join(",") || ""}:${hint.message}`;
  if (state.ui.dismissedHintKey === hintKey) {
    return null;
  }
  return { ...hint, hintKey };
}

function renderProactiveMemoryCard() {
  const hint = currentProactiveHint();
  $("proactiveMemoryCard").hidden = !hint;
  $("dismissProactiveHintButton").disabled = !hint;
  if (!hint) {
    return;
  }
  $("proactiveTitle").textContent = "Buddy noticed";
  $("proactiveMessage").textContent = hint.message;
  $("proactiveBasis").textContent = `Based on ${hint.basis.item_names.join(" / ")}`;
}

function dismissProactiveHint() {
  const hint = currentProactiveHint();
  if (!hint) {
    return;
  }
  state.ui.dismissedHintKey = hint.hintKey;
  renderProactiveMemoryCard();
}

function renderAnswerBasisPanel() {
  const latestQuery = state.workspace.latestQuery;
  const list = $("answerBasisEvidenceList");
  list.replaceChildren();

  if (!latestQuery) {
    $("answerBasisQuestion").textContent = "No current answer basis.";
    $("answerBasisSummary").textContent = "Ask Buddy something to inspect evidence details.";
    const emptyItem = document.createElement("li");
    emptyItem.textContent = "No answer evidence yet.";
    list.appendChild(emptyItem);
    return;
  }

  $("answerBasisQuestion").textContent = `${latestQuery.question} · ${latestQuery.answer_type}`;
  $("answerBasisSummary").textContent = latestQuery.missing_items?.length
    ? `${latestQuery.summary} Missing: ${latestQuery.missing_items.join(" / ")}`
    : latestQuery.summary;

  if (!(latestQuery.evidence_items || []).length) {
    const emptyItem = document.createElement("li");
    emptyItem.textContent = "No answer evidence yet.";
    list.appendChild(emptyItem);
    return;
  }

  latestQuery.evidence_items.forEach((item) => {
    const entry = document.createElement("li");
    appendLine(entry, `${item.name} · ${formatQuantity(item.quantity, item.unit)} · ${item.status}`);
    appendLine(entry, `Source: ${item.source}`, "evidence-line");
    appendLine(entry, `Last seen: ${item.last_seen_at}`, "evidence-line");
    list.appendChild(entry);
  });
}

function renderDetailsDrawer() {
  $("detailsDrawer").open = state.ui.detailsOpen;
  renderAnswerBasisPanel();

  const timelineItems = state.workspace.traces.slice(-5).map((trace) => {
    const status = trace.tool_result_status || trace.permission_policy_result || "captured";
    return `${trace.created_at} · ${status}`;
  });
  renderTextList("traceTimeline", timelineItems, "Waiting for state-memory activity.", (item) => item);

  $("runtimeHealth").textContent = state.workspace.buddyId ? "runtime ok" : "awaiting workspace";
  $("tokenUsage").textContent = String(state.workspace.costSummary.total_tokens || 0);
  $("modelCost").textContent = money(costEventCny(state.workspace.costSummary || {}));
  $("monthCost").textContent = `month cost ${money(costEventCny(state.workspace.costSummary || {}))}`;
}

function renderExperienceShell() {
  renderAuthRail();
  renderBuddyHero();
  renderConfirmedState();
  renderCaptureComposer();
  renderProposalInbox();
  renderLatestAnswer();
  renderProviderSettings();
  renderAgentManagement();
  renderProactiveMemoryCard();
  renderDetailsDrawer();
}

function toggleDetailsDrawer(forceOpen) {
  state.ui.detailsOpen = typeof forceOpen === "boolean" ? forceOpen : !state.ui.detailsOpen;
  renderDetailsDrawer();
}

async function restoreSession() {
  const accessToken = localStorage.getItem(SESSION_STORAGE_KEY);
  if (!accessToken) {
    renderExperienceShell();
    return;
  }
  state.auth.accessToken = accessToken;
  try {
    state.auth.user = await requestJson("/auth/me");
    setAuthStatus(`Signed in as ${state.auth.user.email}`, "ok");
    await loadAuthWorkspace();
  } catch (error) {
    clearSession();
    setAuthStatus("Stored session expired. Please login again.", "error");
    await loadSyncSnapshot();
  }
}

function authPayload() {
  return {
    email: $("authEmailInput").value.trim(),
    password: $("authPasswordInput").value,
    display_name: $("authDisplayNameInput").value.trim() || null,
    invite_code: $("authInviteCodeInput").value.trim() || null,
  };
}

async function registerAuth() {
  const payload = authPayload();
  if (!payload.email || !payload.password) {
    setAuthStatus("Email and password are required for registration.", "error");
    return;
  }
  if (BUDDYS_BOOTSTRAP.inviteRequired && !payload.invite_code) {
    setAuthStatus("Invite code is required for registration.", "error");
    return;
  }
  try {
    const result = await requestJson("/auth/register", {
      method: "POST",
      headers: {},
      body: JSON.stringify(payload),
    });
    saveSession(result.access_token, result.user);
    $("authPasswordInput").value = "";
    setAuthStatus(`Signed in as ${result.user.email}`, "ok");
    await loadAuthWorkspace();
  } catch (error) {
    setAuthStatus(`Register failed: ${error.message}`, "error");
  }
}

async function loginAuth() {
  const payload = authPayload();
  if (!payload.email || !payload.password) {
    setAuthStatus("Email and password are required for login.", "error");
    return;
  }
  try {
    const result = await requestJson("/auth/login", {
      method: "POST",
      headers: {},
      body: JSON.stringify({ email: payload.email, password: payload.password }),
    });
    saveSession(result.access_token, result.user);
    $("authPasswordInput").value = "";
    setAuthStatus(`Signed in as ${result.user.email}`, "ok");
    await loadAuthWorkspace();
  } catch (error) {
    setAuthStatus(`Login failed: ${error.message}`, "error");
  }
}

async function logoutAuth() {
  if (!state.auth.accessToken) {
    return;
  }
  try {
    await requestJson("/auth/logout", { method: "POST" });
  } catch (error) {
    // Ignore transport errors and clear local state anyway.
  }
  clearSession();
  setAuthStatus(
    BUDDYS_BOOTSTRAP.inviteRequired
      ? "Signed out. Registration is invite-only right now."
      : "Signed out. Login to use state memory.",
  );
  await loadSyncSnapshot();
}

async function loadAuthBuddies() {
  if (!state.auth.user) {
    state.workspace.buddies = [];
    state.workspace.buddyId = null;
    return;
  }
  const result = await requestJson("/me/buddies");
  state.workspace.buddies = result.buddies || [];
  if (!state.workspace.buddies.length) {
    state.workspace.buddyId = null;
    return;
  }
  if (!state.workspace.buddyId || !state.workspace.buddies.some((buddy) => buddy.buddy_id === state.workspace.buddyId)) {
    state.workspace.buddyId = state.workspace.buddies[0].buddy_id;
  }
}

async function createMyBuddy() {
  if (!state.auth.user) {
    setAuthStatus("Login before creating a Buddy.", "error");
    return;
  }
  try {
    const buddy = await requestJson("/me/buddies", {
      method: "POST",
      body: JSON.stringify({ name: "My Buddy", space_id: "home" }),
    });
    state.workspace.buddyId = buddy.buddy_id;
    setAuthStatus(`Buddy created for ${state.auth.user.email}`, "ok");
    await loadAuthWorkspace();
  } catch (error) {
    setAuthStatus(`Create Buddy failed: ${error.message}`, "error");
  }
}

async function loadAuthWorkspace() {
  await loadAuthBuddies();
  try {
    await loadProviderSettings();
  } catch (error) {
    handleProviderSettingsLoadFailure(error);
  }
  await loadSyncSnapshot();
}

async function loadProviderSettings() {
  if (!isAuthenticated()) {
    state.ui.provider = { ...PROVIDER_SETTINGS_DEFAULT };
    renderProviderSettings();
    return;
  }
  const payload = await requestJson("/providers", { headers: {} });
  const config = (payload.configs || []).find((item) => item.provider_type === "openai_compatible") || null;
  state.ui.provider = {
    ...PROVIDER_SETTINGS_DEFAULT,
    providerId: config?.provider_id || PROVIDER_SETTINGS_DEFAULT.providerId,
    displayName: config?.display_name || PROVIDER_SETTINGS_DEFAULT.displayName,
    defaultModel: config?.default_model || PROVIDER_SETTINGS_DEFAULT.defaultModel,
    configured: Boolean(config?.configured),
    status: config?.configured ? "configured" : "unconfigured",
    loaded: true,
    errorMessage: "",
  };
  renderProviderSettings();
}

function handleProviderSettingsLoadFailure(error) {
  state.ui.provider = {
    ...state.ui.provider,
    providerId: null,
    loaded: true,
    configured: false,
    status: "unavailable",
    errorMessage: `Provider settings are temporarily unavailable: ${error.message}`,
  };
  renderProviderSettings();
}

async function saveProviderSettings() {
  if (!isAuthenticated()) {
    setAuthStatus("Login before saving provider settings.", "error");
    return;
  }
  if (state.ui.provider.status === "unavailable" || !state.ui.provider.providerId) {
    $("providerSettingsStatus").textContent = "Provider settings are temporarily unavailable. Retry before saving.";
    syncAuthControls();
    return;
  }
  const displayName = $("providerDisplayNameInput").value.trim();
  const defaultModel = $("providerModelInput").value.trim();
  if (!displayName || !defaultModel) {
    $("providerSettingsStatus").textContent = "Display name and model are required.";
    return;
  }
  try {
    const result = await requestJson("/providers", {
      method: "POST",
      body: JSON.stringify({
        provider_id: state.ui.provider.providerId,
        display_name: displayName,
        provider_type: "openai_compatible",
        base_url: "https://api.minimax.io/v1",
        api_key_env_var: "OPENAI_API_KEY",
        default_model: defaultModel,
      }),
    });
    state.ui.provider = {
      ...PROVIDER_SETTINGS_DEFAULT,
      providerId: result.provider_id,
      displayName: result.display_name,
      defaultModel: result.default_model,
      configured: Boolean(result.configured),
      status: result.configured ? "configured" : "unconfigured",
      loaded: true,
      errorMessage: "",
    };
    $("providerSettingsStatus").textContent = result.configured
      ? `${result.display_name} is configured for this account.`
      : `${result.display_name} saved. Waiting for server-side OPENAI_API_KEY.`;
    renderProviderSettings();
  } catch (error) {
    $("providerSettingsStatus").textContent = `Provider settings failed: ${error.message}`;
  }
}

function projectWorkspace(snapshot) {
  if (!isAuthenticated()) {
    state.workspace.stateRevision = 0;
    state.workspace.buddies = [];
    state.workspace.buddyId = null;
    state.workspace.agents = [];
    state.workspace.confirmedItems = [];
    state.workspace.pendingProposals = [];
    state.workspace.latestQuery = null;
    state.workspace.proactiveHint = null;
    state.workspace.summary = {};
    state.workspace.traces = [];
    state.workspace.costSummary = {};
    state.ui.proactiveHint = null;
  } else {
    state.workspace.stateRevision = snapshot.state_revision || 0;
    state.workspace.buddies = snapshot.buddies || [];
    state.workspace.agents = (snapshot.agents || []).map(whitelistAgentSummary);
    if (state.workspace.buddies.length && !state.workspace.buddyId) {
      state.workspace.buddyId = state.workspace.buddies[0].buddy_id;
    }

    const buddyId = state.workspace.buddyId;
    const stateMemory = snapshot.state_memory || {};
    state.workspace.confirmedItems = buddyId ? stateMemory.items_by_buddy?.[buddyId] || [] : [];
    state.workspace.pendingProposals = buddyId ? stateMemory.pending_proposals_by_buddy?.[buddyId] || [] : [];
    state.workspace.latestQuery = buddyId ? stateMemory.latest_query_by_buddy?.[buddyId] || null : null;
    state.workspace.proactiveHint = buddyId ? stateMemory.proactive_hint_by_buddy?.[buddyId] || null : null;
    state.workspace.summary = buddyId ? stateMemory.summary_by_buddy?.[buddyId] || {} : {};
    state.workspace.traces = snapshot.traces || [];
    state.workspace.costSummary = snapshot.cost_summary || {};
    state.ui.proactiveHint = state.workspace.proactiveHint;
  }

  if (state.ui.selectedProposalId) {
    const stillPresent = state.workspace.pendingProposals.some(
      (proposal) => proposal.proposal_id === state.ui.selectedProposalId,
    );
    if (!stillPresent) {
      state.ui.selectedProposalId = null;
    }
  }
}

async function loadSyncSnapshot() {
  const snapshot = await requestJson("/sync/snapshot", { headers: {} });
  projectWorkspace(snapshot);
  renderExperienceShell();
}

async function submitCapture() {
  if (!state.workspace.buddyId) {
    setWorkspaceStatus("Create or select a Buddy before capture.");
    return;
  }
  const content = $("captureTextInput").value.trim();
  if (!content) {
    setWorkspaceStatus("Capture content is required.");
    return;
  }
  try {
    const response = await requestJson(
      `/me/buddies/${state.workspace.buddyId}/state-memory/captures/conversation`,
      {
        method: "POST",
        body: JSON.stringify({ content }),
      },
    );
    $("captureTextInput").value = "";
    state.ui.selectedProposalId = response.proposal.proposal_id;
    $("proposalCorrectionInput").value = JSON.stringify(response.proposal.deltas, null, 2);
    setWorkspaceStatus(`Capture saved as pending proposal: ${response.proposal.content}`);
    await loadSyncSnapshot();
  } catch (error) {
    setWorkspaceStatus(`Capture failed: ${error.message}`);
  }
}

async function submitPhotoCapture() {
  if (!state.workspace.buddyId || !state.ui.photo.base64 || !state.ui.photo.mediaType) {
    setWorkspaceStatus("Choose one photo before saving a photo update.");
    return;
  }
  try {
    const response = await requestJson(`/me/buddies/${state.workspace.buddyId}/state-memory/captures/photo`, {
      method: "POST",
      body: JSON.stringify({
        content: $("captureTextInput").value.trim() || null,
        image_base64: state.ui.photo.base64,
        image_media_type: state.ui.photo.mediaType,
      }),
    });
    clearPhotoSelection();
    state.ui.selectedProposalId = response.proposal.proposal_id;
    $("proposalCorrectionInput").value = JSON.stringify(response.proposal.deltas, null, 2);
    setWorkspaceStatus(`Photo saved as pending proposal: ${response.proposal.content}`);
    await loadSyncSnapshot();
  } catch (error) {
    setWorkspaceStatus(`Photo capture failed: ${error.message}`);
  }
}

async function submitVoiceTranscript() {
  if (!state.workspace.buddyId) {
    setWorkspaceStatus("Create or select a Buddy before saving a reviewed transcript note.");
    return;
  }
  const transcript = $("voiceTranscriptInput").value.trim();
  if (!transcript) {
    setWorkspaceStatus("Voice transcript is empty.");
    return;
  }
  try {
    const response = await requestJson(`/me/buddies/${state.workspace.buddyId}/state-memory/captures/conversation`, {
      method: "POST",
      body: JSON.stringify({ content: transcript }),
    });
    state.ui.voice.transcript = "";
    state.ui.voice.status = "idle";
    state.ui.selectedProposalId = response.proposal.proposal_id;
    $("proposalCorrectionInput").value = JSON.stringify(response.proposal.deltas, null, 2);
    setWorkspaceStatus(`Reviewed transcript saved as pending note: ${response.proposal.content}`);
    await loadSyncSnapshot();
  } catch (error) {
    setWorkspaceStatus(`Transcript save failed: ${error.message}`);
  }
}

async function submitQuery() {
  if (!state.workspace.buddyId) {
    setWorkspaceStatus("Create or select a Buddy before querying state memory.");
    return;
  }
  const question = $("queryTextInput").value.trim();
  if (!question) {
    setWorkspaceStatus("Query text is required.");
    return;
  }
  try {
    const answer = await requestJson(`/me/buddies/${state.workspace.buddyId}/state-memory/query`, {
      method: "POST",
      body: JSON.stringify({ question }),
    });
    $("queryTextInput").value = "";
    setWorkspaceStatus(`Query answered: ${answer.summary}`);
    await loadSyncSnapshot();
  } catch (error) {
    setWorkspaceStatus(`Query failed: ${error.message}`);
  }
}

async function confirmProposal(proposalId) {
  try {
    await requestJson(`/me/buddies/${state.workspace.buddyId}/state-memory/proposals/${proposalId}/confirm`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    if (state.ui.selectedProposalId === proposalId) {
      state.ui.selectedProposalId = null;
      $("proposalCorrectionInput").value = "";
    }
    setWorkspaceStatus("Proposal confirmed.");
    await loadSyncSnapshot();
  } catch (error) {
    setWorkspaceStatus(`Confirm failed: ${error.message}`);
  }
}

async function rejectProposal(proposalId) {
  try {
    await requestJson(`/me/buddies/${state.workspace.buddyId}/state-memory/proposals/${proposalId}/reject`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    if (state.ui.selectedProposalId === proposalId) {
      state.ui.selectedProposalId = null;
      $("proposalCorrectionInput").value = "";
    }
    setWorkspaceStatus("Proposal rejected.");
    await loadSyncSnapshot();
  } catch (error) {
    setWorkspaceStatus(`Reject failed: ${error.message}`);
  }
}

async function submitCorrection() {
  const proposal = selectedProposal();
  if (!state.workspace.buddyId || !proposal) {
    setWorkspaceStatus("Select a pending proposal before applying a correction.");
    return;
  }
  let deltas;
  try {
    deltas = JSON.parse($("proposalCorrectionInput").value);
  } catch (error) {
    setWorkspaceStatus("Correction JSON is invalid.");
    return;
  }
  try {
    await requestJson(`/me/buddies/${state.workspace.buddyId}/state-memory/proposals/${proposal.proposal_id}/correct`, {
      method: "POST",
      body: JSON.stringify({ deltas }),
    });
    state.ui.selectedProposalId = null;
    $("proposalCorrectionInput").value = "";
    setWorkspaceStatus("Correction applied.");
    await loadSyncSnapshot();
  } catch (error) {
    setWorkspaceStatus(`Correction failed: ${error.message}`);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  state.ui.voice.supported = voiceRecognitionSupported();
  $("authRegisterButton").addEventListener("click", registerAuth);
  $("authLoginButton").addEventListener("click", loginAuth);
  $("authLogoutButton").addEventListener("click", logoutAuth);
  $("createMyBuddyButton").addEventListener("click", createMyBuddy);
  $("authBuddySelect").addEventListener("change", () => {
    state.workspace.buddyId = $("authBuddySelect").value || null;
    loadSyncSnapshot().catch((error) => setWorkspaceStatus(`Buddy switch failed: ${error.message}`));
  });
  $("captureSubmitButton").addEventListener("click", submitCapture);
  $("photoFileInput").addEventListener("change", handlePhotoSelected);
  $("clearPhotoSelectionButton").addEventListener("click", clearPhotoSelection);
  $("submitPhotoCaptureButton").addEventListener("click", submitPhotoCapture);
  $("startVoiceCaptureButton").addEventListener("click", startVoiceCapture);
  $("retryVoiceCaptureButton").addEventListener("click", retryVoiceCapture);
  $("submitVoiceTranscriptButton").addEventListener("click", submitVoiceTranscript);
  $("voiceTranscriptInput").addEventListener("input", () => {
    state.ui.voice.transcript = $("voiceTranscriptInput").value;
    if (state.ui.voice.transcript.trim()) {
      state.ui.voice.status = "captured";
    }
    renderCaptureComposer();
  });
  $("querySubmitButton").addEventListener("click", submitQuery);
  $("submitCorrectionButton").addEventListener("click", submitCorrection);
  $("saveProviderSettingsButton").addEventListener("click", saveProviderSettings);
  $("dismissProactiveHintButton").addEventListener("click", dismissProactiveHint);
  $("providerDisplayNameInput").addEventListener("input", () => {
    state.ui.provider.displayName = $("providerDisplayNameInput").value;
  });
  $("providerModelInput").addEventListener("input", () => {
    state.ui.provider.defaultModel = $("providerModelInput").value;
  });
  $("detailsDrawer").addEventListener("toggle", () => {
    state.ui.detailsOpen = $("detailsDrawer").open;
  });

  renderExperienceShell();
  restoreSession().catch(() => {
    renderExperienceShell();
  });
  loadSyncSnapshot().catch(() => {
    renderExperienceShell();
  });
});
