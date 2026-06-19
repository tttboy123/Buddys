const SESSION_STORAGE_KEY = "buddysAccessToken";
const VOICE_COMING_SOON = "Voice capture coming soon";
const PHOTO_COMING_SOON = "Photo capture coming soon";
const UNRECOGNIZED_COPY = "I heard this but could not structure it yet";
const DEFAULT_CAPTURE_EMPTY = "No confirmed state yet.";
const DEFAULT_PENDING_EMPTY = "No pending proposals.";
const DEFAULT_QUERY_EMPTY = "No state-memory query yet.";

const state = {
  auth: {
    accessToken: null,
    user: null,
  },
  workspace: {
    buddyId: null,
    buddies: [],
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
    const detailText = payload?.detail?.message || payload?.detail || detailCode;
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
  localStorage.removeItem(SESSION_STORAGE_KEY);
  $("authPasswordInput").value = "";
  $("authDisplayNameInput").value = "";
  renderExperienceShell();
}

function syncAuthControls() {
  const signedIn = isAuthenticated();
  const hasBuddy = Boolean(state.workspace.buddyId);
  $("authRegisterButton").disabled = signedIn;
  $("authLoginButton").disabled = signedIn;
  $("authLogoutButton").disabled = !signedIn;
  $("authBuddySelect").disabled = !signedIn || !state.workspace.buddies.length;
  $("createMyBuddyButton").disabled = !signedIn || hasBuddy;
  $("captureTextInput").disabled = !hasBuddy;
  $("captureSubmitButton").disabled = !hasBuddy;
  $("queryTextInput").disabled = !hasBuddy;
  $("querySubmitButton").disabled = !hasBuddy;
  $("proposalCorrectionInput").disabled = !hasBuddy || !selectedProposal();
  $("submitCorrectionButton").disabled = !hasBuddy || !selectedProposal();
}

function renderAuthRail() {
  if (!isAuthenticated()) {
    setAuthStatus("Signed out. Login to use state memory.");
  }

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
    (item) => `${item.name} · ${formatQuantity(item.quantity, item.unit)} · ${item.status}`,
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
  if (!hint) {
    return;
  }
  $("proactiveTitle").textContent = "Buddy noticed";
  $("proactiveMessage").textContent = hint.message;
  $("proactiveBasis").textContent = `Based on ${hint.basis.item_names.join(" / ")}`;
}

function renderDetailsDrawer() {
  $("detailsDrawer").open = state.ui.detailsOpen;

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
  };
}

async function registerAuth() {
  const payload = authPayload();
  if (!payload.email || !payload.password) {
    setAuthStatus("Email and password are required for registration.", "error");
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
    setAuthStatus(`Registered ${result.user.email}`, "ok");
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
  setAuthStatus("Signed out. Login to use state memory.");
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
  await loadSyncSnapshot();
}

function projectWorkspace(snapshot) {
  state.workspace.stateRevision = snapshot.state_revision || 0;
  state.workspace.buddies = snapshot.buddies || [];
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
  $("authRegisterButton").addEventListener("click", registerAuth);
  $("authLoginButton").addEventListener("click", loginAuth);
  $("authLogoutButton").addEventListener("click", logoutAuth);
  $("createMyBuddyButton").addEventListener("click", createMyBuddy);
  $("authBuddySelect").addEventListener("change", () => {
    state.workspace.buddyId = $("authBuddySelect").value || null;
    loadSyncSnapshot().catch((error) => setWorkspaceStatus(`Buddy switch failed: ${error.message}`));
  });
  $("captureSubmitButton").addEventListener("click", submitCapture);
  $("querySubmitButton").addEventListener("click", submitQuery);
  $("submitCorrectionButton").addEventListener("click", submitCorrection);
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
