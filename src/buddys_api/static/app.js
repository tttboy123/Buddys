const SESSION_STORAGE_KEY = "buddysAccessToken";

const state = {
  accessToken: null,
  currentUser: null,
  buddyId: null,
  authBuddyId: null,
  demoBuddyId: null,
  proposalId: null,
  traceId: null,
  stateRevision: 0,
  selectedStateMemoryProposalId: null,
  pendingProposalsById: new Map(),
};

const $ = (id) => document.getElementById(id);

function setDevice(status, face, prompt) {
  $("buddyState").textContent = status;
  $("deviceState").textContent = status;
  $("pixelFace").textContent = face;
  $("devicePrompt").textContent = prompt;
  $("mobileStatus").textContent = prompt;
}

function setMobileReview(proposal, instruction, canApprove) {
  $("mobileProposal").textContent = proposal;
  $("mobileManualInstruction").textContent = instruction;
  $("mobileApproveButton").disabled = !canApprove;
}

function setTimeline(items) {
  const timeline = $("traceTimeline");
  timeline.replaceChildren();
  items.forEach((item) => {
    const listItem = document.createElement("li");
    listItem.textContent = item;
    timeline.appendChild(listItem);
  });
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

function money(value) {
  return `¥${value.toFixed(4)}`;
}

function formatQuantity(quantity, unit) {
  if (quantity === null || quantity === undefined) {
    return unit || "-";
  }
  const normalized = Number.isInteger(quantity) ? String(quantity) : String(quantity);
  return `${normalized}${unit || ""}`;
}

function costEventCny(cost) {
  if (!cost) return 0;
  const usd = (cost.model_cost_usd || 0) + (cost.tool_cost_usd || 0) + (cost.log_cost_usd || 0);
  return usd * 7.25;
}

function setAuthStatus(message, tone = "muted") {
  const node = $("authStatus");
  node.textContent = message;
  node.dataset.tone = tone;
}

function setWorkspaceStatus(message) {
  $("stateMemoryWorkspaceStatus").textContent = message;
}

function setStateMemoryFeedback(message) {
  setWorkspaceStatus(message);
}

function resetBuddyOverview() {
  state.buddyId = null;
  $("overviewTitle").textContent = "Home Buddy";
  $("buddySpace").textContent = "Home";
  $("buddyState").textContent = "idle";
}

function resetLegacyDemoRail() {
  state.proposalId = null;
  state.traceId = null;
  $("assistantMessage").textContent = "Ready to propose a safe A-level action.";
  $("proposalSummary").textContent = "No action proposal yet";
  $("proposalPolicy").textContent = "requires confirmation";
  $("approveButton").disabled = true;
  $("runDemoButton").disabled = isAuthenticated();
  $("manualInstruction").textContent =
    "If direct device control is unavailable, Buddys will ask the user to perform the action manually instead of reporting false success.";
  $("modelCost").textContent = "¥0.00";
  $("tokenUsage").textContent = "0";
  $("monthCost").textContent = "month cost ¥0.00";
  $("riskState").textContent = "none";
  setMobileReview("No action proposal yet", "Manual instructions will appear here before trace and cost details.", false);
  setDevice("idle", "•_•", "ready at home");
  setTimeline(["Waiting for demo run."]);
}

function defaultBuddyOptionLabel() {
  return state.currentUser ? "Select my Buddy" : "No auth buddy";
}

function setBuddyOptions(buddies) {
  const select = $("authBuddySelect");
  select.replaceChildren();
  if (!buddies.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = defaultBuddyOptionLabel();
    select.appendChild(option);
    select.value = "";
    return;
  }
  buddies.forEach((buddy) => {
    const option = document.createElement("option");
    option.value = buddy.buddy_id;
    option.textContent = `${buddy.name} · ${buddy.space_id}`;
    select.appendChild(option);
  });
  if (state.authBuddyId) {
    select.value = state.authBuddyId;
  }
}

function isAuthenticated() {
  return Boolean(state.accessToken && state.currentUser);
}

function authHeaders(extraHeaders = {}) {
  const headers = { ...extraHeaders };
  if (state.accessToken) {
    headers.Authorization = `Bearer ${state.accessToken}`;
  }
  return headers;
}

function setControlsDisabled(disabled) {
  $("authBuddySelect").disabled = disabled;
  $("createMyBuddyButton").disabled = !state.currentUser;
  $("captureSourceSelect").disabled = disabled;
  $("captureContentInput").disabled = disabled;
  $("submitCaptureButton").disabled = disabled;
  $("queryQuestionInput").disabled = disabled;
  $("submitQueryButton").disabled = disabled;
  $("proposalCorrectionInput").disabled = disabled;
  $("submitCorrectionButton").disabled = disabled || !state.selectedStateMemoryProposalId;
}

function syncAuthUiState() {
  const signedIn = isAuthenticated();
  $("authLogoutButton").disabled = !signedIn;
  $("createMyBuddyButton").disabled = !state.currentUser;
  $("createBuddyButton").disabled = signedIn;
  $("runDemoButton").disabled = signedIn;
  if (!signedIn) {
    setControlsDisabled(true);
    if (!state.demoBuddyId) {
      setWorkspaceStatus("Login and select a Buddy before submitting state-memory actions.");
    }
    setMobileReview("No action proposal yet", "Manual instructions will appear here before trace and cost details.", false);
    return;
  }
  const hasBuddy = Boolean(state.authBuddyId);
  setControlsDisabled(!hasBuddy);
  if (!hasBuddy) {
    setWorkspaceStatus("Create your first Buddy to unlock capture, query, and proposal review.");
  }
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
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch (error) {
      payload = { detail: text };
    }
  }
  if (!response.ok) {
    const detailCode = payload?.detail?.code;
    const error = new Error(detailCode || `${response.status} ${url}`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

function saveSession(accessToken, user) {
  state.accessToken = accessToken;
  state.currentUser = user;
  resetLegacyDemoRail();
  localStorage.setItem(SESSION_STORAGE_KEY, accessToken);
}

function clearSession() {
  state.accessToken = null;
  state.currentUser = null;
  state.authBuddyId = null;
  state.selectedStateMemoryProposalId = null;
  state.pendingProposalsById = new Map();
  resetBuddyOverview();
  resetLegacyDemoRail();
  localStorage.removeItem(SESSION_STORAGE_KEY);
  setBuddyOptions([]);
  renderProposalReview([]);
  renderStateMemory({}, null);
  syncAuthUiState();
}

async function restoreSession() {
  const accessToken = localStorage.getItem(SESSION_STORAGE_KEY);
  if (!accessToken) {
    syncAuthUiState();
    return;
  }
  state.accessToken = accessToken;
  try {
    state.currentUser = await requestJson("/auth/me");
    setAuthStatus(`Signed in as ${state.currentUser.email}`, "ok");
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
    setAuthStatus(`Signed in as ${result.user.email}`, "ok");
    await loadAuthWorkspace();
  } catch (error) {
    setAuthStatus(`Login failed: ${error.message}`, "error");
  }
}

async function logoutAuth() {
  if (!state.accessToken) {
    return;
  }
  try {
    await requestJson("/auth/logout", { method: "POST" });
  } catch (error) {
    // Ignore logout transport failures and clear local session anyway.
  }
  clearSession();
  setAuthStatus("Signed out. Login to use state memory.", "muted");
  await loadSyncSnapshot();
}

async function loadAuthBuddies() {
  if (!state.currentUser) {
    setBuddyOptions([]);
    return [];
  }
  const result = await requestJson("/me/buddies");
  const buddies = result.buddies || [];
  if (!buddies.length) {
    state.authBuddyId = null;
    setBuddyOptions([]);
    return [];
  }
  if (!state.authBuddyId || !buddies.some((buddy) => buddy.buddy_id === state.authBuddyId)) {
    state.authBuddyId = buddies[0].buddy_id;
  }
  setBuddyOptions(buddies);
  return buddies;
}

async function createMyBuddy() {
  if (!state.currentUser) {
    setAuthStatus("Login before creating a Buddy.", "error");
    return;
  }
  try {
    const buddy = await requestJson("/me/buddies", {
      method: "POST",
      body: JSON.stringify({ name: "Home Buddy", space_id: "home" }),
    });
    state.authBuddyId = buddy.buddy_id;
    setAuthStatus(`Buddy created for ${state.currentUser.email}`, "ok");
    await loadAuthWorkspace();
  } catch (error) {
    setAuthStatus(`Create Buddy failed: ${error.message}`, "error");
  }
}

async function loadAuthWorkspace() {
  await loadAuthBuddies();
  syncAuthUiState();
  if (!state.authBuddyId) {
    setWorkspaceStatus("Create your first Buddy to unlock capture, query, and proposal review.");
    renderProposalReview([]);
    renderStateMemory({}, null);
    return;
  }
  await loadSyncSnapshot();
}

async function createBuddy() {
  if (isAuthenticated()) {
    setAuthStatus("Signed-in mode uses auth Buddies. Sign out to run the legacy demo.", "muted");
    return null;
  }
  const buddy = await requestJson("/buddies", {
    method: "POST",
    headers: {},
    body: JSON.stringify({ user_id: "user_1" }),
  });
  state.demoBuddyId = buddy.buddy_id;
  state.buddyId = buddy.buddy_id;
  $("overviewTitle").textContent = buddy.name;
  $("buddySpace").textContent = buddy.space_id;
  setDevice("idle", "•_•", "Home Buddy online");
  setAuthStatus("Legacy demo Buddy ready. Login to switch to auth state memory.", "muted");
  await loadSyncSnapshot();
  return buddy;
}

function activeBuddyId() {
  if (isAuthenticated()) {
    return state.authBuddyId;
  }
  return state.demoBuddyId || state.buddyId;
}

async function loadSyncSnapshot() {
  const snapshot = await requestJson("/sync/snapshot");
  state.stateRevision = snapshot.state_revision || 0;

  const buddies = snapshot.buddies || [];
  let buddy = null;
  if (isAuthenticated()) {
    buddy = buddies.find((item) => item.buddy_id === state.authBuddyId) || buddies[0] || null;
    if (buddy) {
      state.authBuddyId = buddy.buddy_id;
      $("authBuddySelect").value = buddy.buddy_id;
    }
  } else {
    buddy = buddies.find((item) => item.buddy_id === state.demoBuddyId) || buddies[0] || null;
  }
  if (buddy) {
    state.buddyId = buddy.buddy_id;
    $("overviewTitle").textContent = buddy.name;
    $("buddySpace").textContent = buddy.space_id;
    $("buddyState").textContent = buddy.status;
  }

  const traces = snapshot.traces || [];
  const latestTrace = traces[traces.length - 1];
  if (latestTrace) {
    state.traceId = latestTrace.trace_id;
  }

  const costSummary = snapshot.cost_summary || {};
  $("tokenUsage").textContent = String(costSummary.total_tokens || 0);
  $("modelCost").textContent = money(
    ((costSummary.model_cost_usd || 0) + (costSummary.tool_cost_usd || 0) + (costSummary.log_cost_usd || 0)) * 7.25,
  );

  const selectedBuddyId = isAuthenticated() ? state.authBuddyId : state.buddyId;
  renderStateMemory(snapshot.state_memory || {}, selectedBuddyId);
  renderProposalReview(snapshot.state_memory?.pending_proposals_by_buddy?.[selectedBuddyId] || []);

  if (isAuthenticated()) {
    if (selectedBuddyId) {
      setWorkspaceStatus(`Signed in. Workspace revision ${state.stateRevision}.`);
    } else {
      setWorkspaceStatus("No auth Buddy selected.");
    }
  }
  syncAuthUiState();
}

async function ensureBuddy() {
  if (!activeBuddyId()) {
    await createBuddy();
  }
}

async function checkHealth() {
  try {
    await requestJson("/healthz", { headers: {} });
    $("runtimeHealth").textContent = "runtime ok";
    $("runtimeHealth").classList.add("ok");
  } catch (error) {
    $("runtimeHealth").textContent = "runtime error";
    $("runtimeHealth").classList.add("error");
  }
}

async function runBuddysDemo() {
  if (isAuthenticated()) {
    $("assistantMessage").textContent = "Signed-in mode is for auth state memory. Sign out to run the legacy light demo.";
    return;
  }
  await ensureBuddy();
  setDevice("thinking", "•-•", "understanding light request");
  $("assistantMessage").textContent = "Thinking through the safest action...";
  $("runDemoButton").disabled = true;

  const message = await requestJson(`/buddies/${state.buddyId}/messages`, {
    method: "POST",
    headers: {},
    body: JSON.stringify({ user_id: "user_1", message: "把客厅灯调暗" }),
  });

  state.proposalId = message.proposal_id;
  state.traceId = message.trace_id;
  state.stateRevision = message.state_revision || state.stateRevision;
  $("assistantMessage").textContent = message.assistant_message;
  $("proposalSummary").textContent = "把 living_room_light 亮度调到 35%";
  $("proposalPolicy").textContent = "A-level requires confirmation";
  $("approveButton").disabled = false;
  $("riskState").textContent = "waiting for approval";
  setMobileReview(
    "把 living_room_light 亮度调到 35%",
    "Review this A-level device action before opening trace or cost details.",
    true,
  );
  setDevice("asking_confirmation", "•o•", "approve dim light?");
  setTimeline([
    "User input: 把客厅灯调暗",
    "Buddy understanding: adjust_light",
    "Policy: A-level action requires confirmation",
  ]);
  await loadSyncSnapshot();
}

async function approveProposal() {
  if (!state.proposalId) return;
  $("approveButton").disabled = true;
  setDevice("executing", "•_•", "executing adapter action");

  const confirmed = await requestJson(`/proposals/${state.proposalId}/confirm`, {
    method: "POST",
    headers: {},
    body: JSON.stringify({ decision: "approved" }),
  });
  const trace = await requestJson(`/traces/${confirmed.trace_id}`, { headers: {} });
  const costs = await requestJson("/cost-events", { headers: {} });
  renderResult(trace, costs.cost_events);
  await loadSyncSnapshot();
}

function renderStateMemory(snapshotStateMemory, selectedBuddyId) {
  const projection = snapshotStateMemory || {};
  const items = selectedBuddyId ? projection.items_by_buddy?.[selectedBuddyId] || [] : [];
  const pending = selectedBuddyId ? projection.pending_proposals_by_buddy?.[selectedBuddyId] || [] : [];
  const summary = selectedBuddyId ? projection.summary_by_buddy?.[selectedBuddyId] || {} : {};
  const latestQuery = selectedBuddyId ? projection.latest_query_by_buddy?.[selectedBuddyId] || null : null;

  $("stateMemoryConfirmedCount").textContent = String(summary.confirmed_item_count || items.length || 0);
  $("stateMemoryPendingCount").textContent = String(summary.pending_proposal_count || pending.length || 0);
  $("stateMemoryLastUpdated").textContent = summary.last_state_change_at || "-";

  renderTextList("stateMemoryConfirmedList", items, "No confirmed items yet.", (item) => {
    return `${item.name} · ${formatQuantity(item.quantity, item.unit)} · ${item.status}`;
  });
  renderTextList("stateMemoryPendingList", pending, "No pending proposals.", (proposal) => {
    return `${proposal.content} · ${proposal.deltas.length} delta`;
  });

  if (!latestQuery) {
    $("stateMemoryQuerySummary").textContent = "No state-memory query yet.";
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
    (item) => {
      return `${item.name} · ${formatQuantity(item.quantity, item.unit)} · ${item.status}`;
    },
  );
}

function renderProposalReview(pendingProposals) {
  const list = $("proposalReviewList");
  list.replaceChildren();
  state.pendingProposalsById = new Map();

  if (!pendingProposals.length) {
    const emptyItem = document.createElement("li");
    emptyItem.textContent = "No proposal selected for review.";
    list.appendChild(emptyItem);
    $("proposalCorrectionInput").value = "";
    state.selectedStateMemoryProposalId = null;
    syncAuthUiState();
    return;
  }

  pendingProposals.forEach((proposal) => {
    state.pendingProposalsById.set(proposal.proposal_id, proposal);
    const item = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = proposal.content;
    const meta = document.createElement("p");
    meta.textContent = `${proposal.deltas.length} delta · ${proposal.source}`;
    const actions = document.createElement("div");
    actions.className = "button-row";

    const selectButton = document.createElement("button");
    selectButton.type = "button";
    selectButton.className = "ghost-button";
    selectButton.textContent = "Edit correction";
    selectButton.addEventListener("click", () => {
      state.selectedStateMemoryProposalId = proposal.proposal_id;
      $("proposalCorrectionInput").value = JSON.stringify(proposal.deltas, null, 2);
      syncAuthUiState();
      setStateMemoryFeedback(`Correction loaded for: ${proposal.content}`);
    });

    const confirmButton = document.createElement("button");
    confirmButton.type = "button";
    confirmButton.className = "primary-button";
    confirmButton.textContent = "Confirm";
    confirmButton.addEventListener("click", () => confirmStateMemoryProposal(proposal.proposal_id));

    const rejectButton = document.createElement("button");
    rejectButton.type = "button";
    rejectButton.className = "secondary-button";
    rejectButton.textContent = "Reject";
    rejectButton.addEventListener("click", () => rejectStateMemoryProposal(proposal.proposal_id));

    actions.appendChild(selectButton);
    actions.appendChild(confirmButton);
    actions.appendChild(rejectButton);
    item.appendChild(title);
    item.appendChild(meta);
    item.appendChild(actions);
    list.appendChild(item);
  });

  if (
    state.selectedStateMemoryProposalId &&
    !state.pendingProposalsById.has(state.selectedStateMemoryProposalId)
  ) {
    state.selectedStateMemoryProposalId = null;
    $("proposalCorrectionInput").value = "";
  }
  syncAuthUiState();
}

async function submitCapture() {
  if (!state.authBuddyId) {
    setStateMemoryFeedback("Create or select a Buddy before capture.");
    return;
  }
  const content = $("captureContentInput").value.trim();
  if (!content) {
    setStateMemoryFeedback("Capture content is required.");
    return;
  }
  const source = $("captureSourceSelect").value;
  try {
    const response = await requestJson(`/me/buddies/${state.authBuddyId}/state-memory/captures/${source}`, {
      method: "POST",
      body: JSON.stringify({ content }),
    });
    $("captureContentInput").value = "";
    state.selectedStateMemoryProposalId = response.proposal.proposal_id;
    $("proposalCorrectionInput").value = JSON.stringify(response.proposal.deltas, null, 2);
    setStateMemoryFeedback(`Capture saved as pending proposal: ${response.proposal.content}`);
    await loadSyncSnapshot();
  } catch (error) {
    setStateMemoryFeedback(`Capture failed: ${error.message}`);
  }
}

async function submitQuery() {
  if (!state.authBuddyId) {
    setStateMemoryFeedback("Create or select a Buddy before querying state memory.");
    return;
  }
  const question = $("queryQuestionInput").value.trim();
  if (!question) {
    setStateMemoryFeedback("Query text is required.");
    return;
  }
  try {
    const answer = await requestJson(`/me/buddies/${state.authBuddyId}/state-memory/query`, {
      method: "POST",
      body: JSON.stringify({ question }),
    });
    $("queryQuestionInput").value = "";
    $("stateMemoryQuerySummary").textContent = answer.summary;
    setStateMemoryFeedback(`Query answered: ${answer.summary}`);
    await loadSyncSnapshot();
  } catch (error) {
    setStateMemoryFeedback(`Query failed: ${error.message}`);
  }
}

async function confirmStateMemoryProposal(proposalId) {
  try {
    await requestJson(`/me/buddies/${state.authBuddyId}/state-memory/proposals/${proposalId}/confirm`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    if (state.selectedStateMemoryProposalId === proposalId) {
      state.selectedStateMemoryProposalId = null;
      $("proposalCorrectionInput").value = "";
    }
    setStateMemoryFeedback("Proposal confirmed.");
    await loadSyncSnapshot();
  } catch (error) {
    setStateMemoryFeedback(`Confirm failed: ${error.message}`);
  }
}

async function rejectStateMemoryProposal(proposalId) {
  try {
    await requestJson(`/me/buddies/${state.authBuddyId}/state-memory/proposals/${proposalId}/reject`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    if (state.selectedStateMemoryProposalId === proposalId) {
      state.selectedStateMemoryProposalId = null;
      $("proposalCorrectionInput").value = "";
    }
    setStateMemoryFeedback("Proposal rejected.");
    await loadSyncSnapshot();
  } catch (error) {
    setStateMemoryFeedback(`Reject failed: ${error.message}`);
  }
}

async function submitCorrection() {
  if (!state.authBuddyId || !state.selectedStateMemoryProposalId) {
    setStateMemoryFeedback("Select a pending proposal before applying a correction.");
    return;
  }
  let deltas;
  try {
    deltas = JSON.parse($("proposalCorrectionInput").value);
  } catch (error) {
    setStateMemoryFeedback("Correction JSON is invalid.");
    return;
  }
  try {
    await requestJson(
      `/me/buddies/${state.authBuddyId}/state-memory/proposals/${state.selectedStateMemoryProposalId}/correct`,
      {
        method: "POST",
        body: JSON.stringify({ deltas }),
      },
    );
    state.selectedStateMemoryProposalId = null;
    $("proposalCorrectionInput").value = "";
    setStateMemoryFeedback("Correction applied.");
    await loadSyncSnapshot();
  } catch (error) {
    setStateMemoryFeedback(`Correction failed: ${error.message}`);
  }
}

function renderResult(trace, costEvents) {
  const toolResult = trace.tool_result || {};
  const manualRequired = toolResult.status === "manual_required";
  const success = toolResult.status === "success";
  const cost = costEvents.find((event) => event.trace_id === trace.trace_id);
  const tokenCount = cost ? cost.input_tokens + cost.output_tokens : 0;
  const estimatedCost = costEventCny(cost);

  $("proposalPolicy").textContent = trace.permission_decision.policy_result;
  $("manualInstruction").textContent = manualRequired
    ? toolResult.user_instruction
    : "No manual fallback needed for this run.";
  $("mobileApproveButton").disabled = true;
  $("modelCost").textContent = money(estimatedCost);
  $("monthCost").textContent = `month cost ${money(estimatedCost)}`;
  $("tokenUsage").textContent = String(tokenCount);

  if (manualRequired) {
    setMobileReview(
      "Manual action required",
      toolResult.user_instruction || toolResult.voice_prompt || "Please complete this action manually.",
      false,
    );
    setDevice("manual_required", "•!•", toolResult.voice_prompt || toolResult.user_instruction);
    $("riskState").textContent = "manual action required";
  } else if (success) {
    setMobileReview("Action completed", "No manual fallback needed for this run.", false);
    setDevice("success", "^_^", "living room dimmed");
    $("riskState").textContent = "none";
  } else {
    setMobileReview("Adapter error", "Open the trace for details before retrying.", false);
    setDevice("error", "x_x", "adapter returned no result");
    $("riskState").textContent = "adapter error";
  }

  setTimeline([
    `User input: ${trace.intent.summary}`,
    `Proposal: ${trace.proposal.summary}`,
    `Policy: ${trace.permission_decision.reason}`,
    `Execution: ${toolResult.status || "not executed"}`,
    `Cost refs: ${trace.cost_refs.join(", ")}`,
  ]);
}

function resetDemo() {
  resetLegacyDemoRail();
}

window.runBuddysDemo = runBuddysDemo;

document.addEventListener("DOMContentLoaded", () => {
  $("createBuddyButton").addEventListener("click", createBuddy);
  $("runDemoButton").addEventListener("click", runBuddysDemo);
  $("approveButton").addEventListener("click", approveProposal);
  $("mobileApproveButton").addEventListener("click", approveProposal);
  $("resetButton").addEventListener("click", resetDemo);
  $("authRegisterButton").addEventListener("click", registerAuth);
  $("authLoginButton").addEventListener("click", loginAuth);
  $("authLogoutButton").addEventListener("click", logoutAuth);
  $("createMyBuddyButton").addEventListener("click", createMyBuddy);
  $("refreshWorkspaceButton").addEventListener("click", () => {
    if (isAuthenticated()) {
      loadAuthWorkspace().catch((error) => setStateMemoryFeedback(`Refresh failed: ${error.message}`));
    } else {
      loadSyncSnapshot().catch(() => {});
    }
  });
  $("authBuddySelect").addEventListener("change", () => {
    state.authBuddyId = $("authBuddySelect").value || null;
    loadSyncSnapshot().catch((error) => setStateMemoryFeedback(`Buddy switch failed: ${error.message}`));
  });
  $("submitCaptureButton").addEventListener("click", submitCapture);
  $("submitQueryButton").addEventListener("click", submitQuery);
  $("submitCorrectionButton").addEventListener("click", submitCorrection);

  checkHealth();
  syncAuthUiState();
  restoreSession().catch(() => {});
  loadSyncSnapshot().catch(() => {});
});
