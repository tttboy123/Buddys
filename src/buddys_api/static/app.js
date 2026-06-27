const SESSION_STORAGE_KEY = "buddysAccessToken";
const VOICE_UNSUPPORTED_COPY = "Voice capture is not available in this browser.";
const UNRECOGNIZED_COPY = "I heard this but could not structure it yet";
const DEFAULT_CAPTURE_EMPTY = "No confirmed state yet.";
const DEFAULT_PENDING_EMPTY = "No pending proposals.";
const DEFAULT_QUERY_EMPTY = "No state-memory query yet.";
const DEFAULT_RECIPE_EMPTY = "No saved recipes yet.";
const DEFAULT_SHOPPING_PASS_EMPTY = "No shopping-pass items yet.";
const BUDDYS_BOOTSTRAP = window.BUDDYS_BOOTSTRAP || { inviteRequired: false };

const state = {
  auth: {
    accessToken: null,
    user: null,
  },
  workspace: {
    buddyId: null,
    buddies: [],
    agents: [],
    agentMachines: [],
    confirmedItems: [],
    pendingProposals: [],
    recipes: [],
    shoppingPassItems: [],
    shoppingPassSummary: {},
    latestQuery: null,
    recentActivity: [],
    proactiveHint: null,
    summary: {},
    traces: [],
    costSummary: {},
    planUsage: {},
    engagementMetrics: null,
    retentionSummary: null,
    founderMetricsVisible: false,
    founderMetricsUnavailableReason: null,
    device: null,
    agentMachine: null,
    binding: null,
    latestHeartbeat: null,
    desiredState: null,
    deviceEvents: [],
    stateRevision: 0,
  },
  ui: {
    selectedProposalId: null,
    detailsOpen: false,
    dismissedHintKey: null,
    proactiveHint: null,
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
    deviceReminderDraftsByBuddy: {},
    founderMetricsRequestGeneration: 0,
  },
};

const AGENT_STATUSES = ["starting", "online", "degraded", "offline", "error"];
const HEARTBEAT_REQUESTS_IN_FLIGHT = new Set();

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
    if (response.status === 401 && detailCode === "invalid_or_expired_token") {
      await recoverExpiredSession();
    }
    const detailText = payload?.detail?.message || detailCode || payload?.detail;
    const error = new Error(detailText || `${response.status} ${url}`);
    error.status = response.status;
    error.payload = payload;
    if (response.status === 401 && detailCode === "invalid_or_expired_token") {
      error.recoveredSessionExpired = true;
    }
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
    return "数量未输入";
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
  state.workspace.agentMachines = [];
  state.workspace.confirmedItems = [];
  state.workspace.pendingProposals = [];
  state.workspace.recipes = [];
  state.workspace.shoppingPassItems = [];
  state.workspace.shoppingPassSummary = {};
  state.workspace.latestQuery = null;
  state.workspace.recentActivity = [];
  state.workspace.proactiveHint = null;
  state.workspace.summary = {};
  state.workspace.traces = [];
  state.workspace.costSummary = {};
  state.workspace.planUsage = {};
  state.workspace.engagementMetrics = null;
  state.workspace.retentionSummary = null;
  state.workspace.founderMetricsVisible = false;
  state.workspace.founderMetricsUnavailableReason = null;
  state.workspace.device = null;
  state.workspace.agentMachine = null;
  state.workspace.binding = null;
  state.workspace.latestHeartbeat = null;
  state.workspace.desiredState = null;
  state.workspace.deviceEvents = [];
  state.workspace.stateRevision = 0;
  state.ui.selectedProposalId = null;
  state.ui.detailsOpen = false;
  state.ui.dismissedHintKey = null;
  state.ui.proactiveHint = null;
  state.ui.photo = { base64: null, mediaType: null, previewUrl: null, fileName: null };
  state.ui.voice = { transcript: "", status: "idle", supported: voiceRecognitionSupported(), recording: false };
  state.ui.deviceReminderDraftsByBuddy = {};
  state.ui.founderMetricsRequestGeneration += 1;
  localStorage.removeItem(SESSION_STORAGE_KEY);
  $("authPasswordInput").value = "";
  $("authDisplayNameInput").value = "";
  $("authInviteCodeInput").value = "";
  $("agentManagementActionStatus").textContent = "No agent registration yet.";
  $("deviceOwnerInstructionInput").value = "";
  $("recipeNameInput").value = "";
  $("recipeIngredientsInput").value = "";
  $("shoppingPassNameInput").value = "";
  renderExperienceShell();
}

async function recoverExpiredSession() {
  clearSession();
  setAuthStatus("Stored session expired. Please login again.", "error");
  await loadSyncSnapshot();
}

function isRecoveredSessionExpiry(error) {
  return Boolean(error?.recoveredSessionExpired);
}

function syncAuthControls() {
  const signedIn = isAuthenticated();
  const hasBuddy = Boolean(state.workspace.buddyId);
  const hasDevice = Boolean(state.workspace.device);
  const hasPhoto = Boolean(state.ui.photo.base64);
  const hasVoiceTranscript = Boolean(state.ui.voice.transcript.trim());
  const hasDeviceInstruction = Boolean($("deviceOwnerInstructionInput")?.value.trim());
  const hasAgentName = Boolean($("agentManagementNameInput")?.value.trim());
  const hasRecipeName = Boolean($("recipeNameInput")?.value.trim());
  const hasRecipeIngredients = Boolean($("recipeIngredientsInput")?.value.trim());
  const hasShoppingPassName = Boolean($("shoppingPassNameInput")?.value.trim());
  $("authRegisterButton").disabled = signedIn;
  $("authLoginButton").disabled = signedIn;
  $("authLogoutButton").disabled = !signedIn;
  $("authBuddySelect").disabled = !signedIn || !state.workspace.buddies.length;
  $("createMyBuddyButton").disabled = !signedIn || hasBuddy;
  $("agentManagementNameInput").disabled = !signedIn;
  $("agentManagementRoleSelect").disabled = !signedIn;
  $("createAgentButton").disabled = !signedIn || !hasAgentName;
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
  $("recipeNameInput").disabled = !hasBuddy;
  $("recipeIngredientsInput").disabled = !hasBuddy;
  $("createRecipeButton").disabled = !hasBuddy || !hasRecipeName || !hasRecipeIngredients;
  $("shoppingPassNameInput").disabled = !hasBuddy;
  $("shoppingPassAddButton").disabled = !hasBuddy || !hasShoppingPassName;
  $("shoppingPassPromoteHintButton").disabled = !hasBuddy;
  $("shoppingPassPromoteLatestQueryButton").disabled = !hasBuddy;
  $("proposalCorrectionInput").disabled = !hasBuddy || !selectedProposal();
  $("submitCorrectionButton").disabled = !hasBuddy || !selectedProposal();
  $("deviceOwnerInstructionInput").disabled = !hasBuddy || !hasDevice;
  $("publishDeviceDesiredStateButton").disabled = !hasBuddy || !hasDevice || !hasDeviceInstruction;
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

function proposalDeltaCopy(delta) {
  const quantityCopy =
    delta.quantity === null || delta.quantity === undefined ? "数量未输入" : formatQuantity(delta.quantity, delta.unit);
  return `${delta.item_name} · ${delta.operation} · ${quantityCopy}`;
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

    const deltaList = document.createElement("ul");
    deltaList.className = "inline-list";
    (proposal.deltas || []).forEach((delta) => {
      const deltaItem = document.createElement("li");
      deltaItem.textContent = proposalDeltaCopy(delta);
      deltaList.appendChild(deltaItem);
    });
    item.appendChild(deltaList);

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
    ? `Buddy answered using saved evidence and still needs ${latestQuery.missing_items.join(" / ")}.`
    : "Buddy answered using saved evidence.";
  renderTextList(
    "stateMemoryEvidenceList",
    latestQuery.evidence_items || [],
    latestQuery.evidence_item_ids?.length ? "Evidence item details unavailable." : "No evidence items captured.",
    (item) =>
      `${item.name} · ${formatQuantity(item.quantity, item.unit)} · ${item.status} · ${item.source} · ${item.last_seen_at}`,
  );
}

function formatRecipe(recipe) {
  return `${recipe.name} · ${(recipe.ingredients || []).map((ingredient) => ingredient.name).join(" / ")}`;
}

function renderRecipeShelf() {
  const list = $("recipeList");
  list.replaceChildren();

  if (!isAuthenticated()) {
    $("recipeShelfStatus").textContent = "Login to save recipes for this Buddy.";
  } else if (!state.workspace.buddyId) {
    $("recipeShelfStatus").textContent = "Create your first Buddy before saving recipes.";
  } else {
    $("recipeShelfStatus").textContent = state.workspace.recipes.length
      ? "Saved recipes are used before fallback recipe defaults for this Buddy."
      : "Save one recipe to make missing-for-recipe answers personal to this Buddy.";
  }

  if (!state.workspace.recipes.length) {
    const emptyItem = document.createElement("li");
    emptyItem.textContent = DEFAULT_RECIPE_EMPTY;
    list.appendChild(emptyItem);
    syncAuthControls();
    return;
  }

  state.workspace.recipes.forEach((recipe) => {
    const item = document.createElement("li");
    item.className = "proposal-card";

    const title = document.createElement("strong");
    title.textContent = recipe.name;
    item.appendChild(title);

    const meta = document.createElement("p");
    meta.className = "support-copy";
    meta.textContent = (recipe.ingredients || []).map((ingredient) => ingredient.name).join(" / ");
    item.appendChild(meta);

    const actions = document.createElement("div");
    actions.className = "button-row";

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "ghost-button";
    deleteButton.textContent = "Delete";
    deleteButton.addEventListener("click", () => deleteRecipe(recipe.recipe_id));

    actions.appendChild(deleteButton);
    item.appendChild(actions);
    list.appendChild(item);
  });

  syncAuthControls();
}

function shoppingPassSourceLabel(item) {
  if (item.source_kind === "manual") {
    return "manual";
  }
  if (item.source_kind === "proactive_hint") {
    return "hint";
  }
  if (item.source_kind === "missing_for_recipe") {
    return "recipe gap";
  }
  return item.source_kind || "unknown";
}

function renderShoppingPass() {
  const list = $("shoppingPassList");
  const summary = state.workspace.shoppingPassSummary || {};
  list.replaceChildren();

  if (!isAuthenticated()) {
    $("shoppingPassStatus").textContent = "Login to build a shopping pass for this Buddy.";
  } else if (!state.workspace.buddyId) {
    $("shoppingPassStatus").textContent = "Create your first Buddy before planning the next shopping pass.";
  } else if (state.workspace.shoppingPassItems.length) {
    const openCount = Number(summary.open_count || state.workspace.shoppingPassItems.length || 0);
    const doneCount = Number(summary.done_count || 0);
    $("shoppingPassStatus").textContent = `${openCount} open item(s). ${doneCount} done item(s) already cleared from this Buddy's pass.`;
  } else if (Number(summary.done_count || 0) > 0) {
    $("shoppingPassStatus").textContent = "All promoted items are done. Add another item or promote a new hint/query.";
  } else {
    $("shoppingPassStatus").textContent =
      "Add items manually or promote the latest hint/query to keep the next shopping pass ready.";
  }

  if (!state.workspace.shoppingPassItems.length) {
    const emptyItem = document.createElement("li");
    emptyItem.textContent = DEFAULT_SHOPPING_PASS_EMPTY;
    list.appendChild(emptyItem);
    syncAuthControls();
    return;
  }

  state.workspace.shoppingPassItems.forEach((item) => {
    const entry = document.createElement("li");
    entry.className = "proposal-card";

    const title = document.createElement("strong");
    title.textContent = item.name;
    entry.appendChild(title);

    const meta = document.createElement("p");
    meta.className = "support-copy";
    meta.textContent = `${shoppingPassSourceLabel(item)} · ${item.source_summary}`;
    entry.appendChild(meta);

    const actions = document.createElement("div");
    actions.className = "button-row";

    const doneButton = document.createElement("button");
    doneButton.type = "button";
    doneButton.className = "ghost-button";
    doneButton.textContent = "Done";
    doneButton.addEventListener("click", () => markShoppingPassItemDone(item.shopping_item_id));

    actions.appendChild(doneButton);
    entry.appendChild(actions);
    list.appendChild(entry);
  });

  syncAuthControls();
}

function formatRecentActivity(activity) {
  return activity.summary || "Buddy recorded a recent action.";
}

function renderRecentActivity() {
  const activities = (state.workspace.recentActivity || []).slice().reverse();
  const status = $("buddyActivityStatus");

  if (!isAuthenticated()) {
    status.textContent = "Login to see Buddy's latest saved updates and answers.";
    renderTextList("buddyActivityList", [], "No recent Buddy activity yet.", () => "");
    return;
  }
  if (!state.workspace.buddyId) {
    status.textContent = "Create your first Buddy to see recent activity and answers.";
    renderTextList("buddyActivityList", [], "No recent Buddy activity yet.", () => "");
    return;
  }

  status.textContent = activities.length
    ? "Buddy keeps the latest saved updates, reviews, and answers here."
    : "Buddy will keep the latest saved updates and answers here.";

  renderTextList("buddyActivityList", activities, "No recent Buddy activity yet.", (activity) => {
    return formatRecentActivity(activity);
  });
}

function renderCostGovernancePanel() {
  const planUsage = state.workspace.planUsage || {};
  const planId = planUsage.plan_display_name || planUsage.plan_id || "unknown";
  const usageMonth = planUsage.usage_month || "current";
  const hardLimit = planUsage.hard_limit ? "enabled" : "disabled";
  const usedTokens = Number(planUsage.used_tokens || 0);
  const remainingTokens = planUsage.remaining_tokens === null || planUsage.remaining_tokens === undefined
    ? null
    : Number(planUsage.remaining_tokens);
  const monthlyLimit = Number(planUsage.monthly_token_limit || 0);
  const costSummary = state.workspace.costSummary || {};
  const byProvider = planUsage.provider_usage || {};
  const byModel = planUsage.model_usage || {};
  const topProviderEntry = Object.entries(byProvider).sort((left, right) => right[1].total_tokens - left[1].total_tokens)[0];
  const topModelEntry = Object.entries(byModel).sort((left, right) => right[1].total_tokens - left[1].total_tokens)[0];

  const planLines = [];
  const topProviderCopy = topProviderEntry
    ? `${topProviderEntry[0]} · ${topProviderEntry[1].total_tokens || 0} tokens`
    : "No provider usage yet.";
  const topModelCopy = topModelEntry
    ? `${topModelEntry[0]} · ${topModelEntry[1].total_tokens || 0} tokens`
    : "No model usage yet.";

  if (!isAuthenticated()) {
    $("costGovernanceStatus").textContent = "Login to see token usage and cost summary.";
    renderTextList("planUsageList", [], "Sign in to unlock usage transparency.", (line) => line);
    renderTextList("planUsageBreakdownList", [], "Sign in to see provider/model usage detail.", (line) => line);
    $("planGovernanceCostRow").textContent = "Cost snapshot unavailable.";
    return;
  }

  if (!planUsage || !Object.keys(planUsage).length) {
    $("costGovernanceStatus").textContent = "Usage summary is not available yet.";
    renderTextList("planUsageList", [], "No plan usage snapshot yet.", (line) => line);
    renderTextList("planUsageBreakdownList", [], "No usage breakdown yet.", (line) => line);
    $("planGovernanceCostRow").textContent = "Cost snapshot unavailable.";
    return;
  }

  planLines.push(`Plan: ${planId}`);
  planLines.push(`Month: ${usageMonth}`);
  planLines.push(`Used tokens: ${usedTokens}`);
  planLines.push(`Monthly limit: ${monthlyLimit || 0}`);
  planLines.push(
    `Remaining tokens: ${remainingTokens === null ? "unlimited" : remainingTokens.toLocaleString("en-US")}`,
  );
  planLines.push(`Hard limit: ${hardLimit}`);
  planLines.push(`Plan BYOK mode: ${planUsage.byok ? "on" : "off"}`);
  if (planUsage.over_limit) {
    planLines.push("Limit status: reached");
  } else {
    planLines.push("Limit status: in quota");
  }

  $("costGovernanceStatus").textContent = "Token and cost snapshot updated from server state.";
  renderTextList("planUsageList", planLines, "Cost summary is empty.", (line) => line);
  renderTextList("planUsageBreakdownList", [topProviderCopy, topModelCopy], "No usage breakdown yet.", (line) => line);
  $("planGovernanceCostRow").textContent = `Estimated spend: ${money(costSummary.model_cost_usd + costSummary.tool_cost_usd + costSummary.log_cost_usd || 0)} / ${costEventCny(
    costSummary,
  ).toFixed(2)} CNY`;
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
}

function founderMetricRows(title, rows) {
  const fragment = document.createDocumentFragment();
  const heading = document.createElement("h3");
  heading.textContent = title;
  fragment.appendChild(heading);
  rows.forEach((row) => {
    const line = document.createElement("p");
    line.className = "support-copy";
    line.textContent = row;
    fragment.appendChild(line);
  });
  return fragment;
}

function renderFounderMetricCard(targetId, title, rows) {
  const card = $(targetId);
  const eyebrow = card.querySelector(".eyebrow");
  const heading = card.querySelector("h3");
  if (heading) {
    heading.textContent = title;
  }
  Array.from(card.children).forEach((child) => {
    if (child !== eyebrow && child !== heading) {
      card.removeChild(child);
    }
  });
  rows.forEach((row) => {
    const line = document.createElement("p");
    line.className = "support-copy";
    line.textContent = row;
    card.appendChild(line);
  });
}

function captureMixRows(captureBySource) {
  const entries = Object.entries(captureBySource || {});
  if (!entries.length) {
    return ["No founder capture metrics yet."];
  }
  return entries.map(([source, count]) => `${source}: ${count}`);
}

function renderFounderMetrics() {
  $("founderMetricsPanel").hidden = !state.workspace.founderMetricsVisible;
  if (!state.workspace.founderMetricsVisible) {
    return;
  }

  const unavailableReason = state.workspace.founderMetricsUnavailableReason;
  if (unavailableReason) {
    $("founderMetricsStatus").textContent = `Founder metrics unavailable: ${unavailableReason}`;
    renderFounderMetricCard("founderActivationPanel", "My activation", ["Founder metrics unavailable"]);
    renderFounderMetricCard("founderRetentionPanel", "Activated retention", ["Founder metrics unavailable"]);
    renderFounderMetricCard("founderCaptureMixPanel", "Capture sources", ["Founder metrics unavailable"]);
    return;
  }

  const engagement = state.workspace.engagementMetrics || {};
  const retention = state.workspace.retentionSummary || {};
  const activated = Boolean(engagement.activation?.completed_first_capture_confirm_query);

  $("founderMetricsStatus").textContent = "Founder metrics are live for this account.";
  renderFounderMetricCard("founderActivationPanel", "My activation", [
    activated ? "Closed first capture -> review -> query loop: yes" : "Closed first capture -> review -> query loop: no",
    `Tracked events: ${engagement.event_count || 0}`,
  ]);
  renderFounderMetricCard("founderRetentionPanel", "Activated retention", [
    `Activated users: ${retention.activated_users || 0}`,
    `D1 active: ${retention.d1_active_users || 0}`,
    `D3 active: ${retention.d3_active_users || 0}`,
    `D7 active: ${retention.d7_active_users || 0}`,
  ]);
  renderFounderMetricCard("founderCaptureMixPanel", "Capture sources", captureMixRows(retention.capture_by_source));
}

function renderDeviceWorkspace() {
  const device = state.workspace.device;
  const heartbeat = state.workspace.latestHeartbeat;
  const desiredState = state.workspace.desiredState;
  const binding = state.workspace.binding;
  const agentMachine = state.workspace.agentMachine;
  const deviceEvents = state.workspace.deviceEvents || [];

  if (!isAuthenticated()) {
    $("deviceWorkspaceStatus").textContent = "Login to inspect the paired device for this Buddy.";
    $("deviceOwnerInstructionInput").value = "";
    renderFounderMetricCard("deviceIdentityPanel", "Device identity", ["No paired device yet."]);
    renderFounderMetricCard("deviceHealthPanel", "Heartbeat and state", ["No paired device yet."]);
    renderFounderMetricCard("deviceDesiredStatePanel", "Desired state and revision", ["No paired device yet."]);
    renderFounderMetricCard("deviceEventPanel", "Recent device events", ["No paired device yet."]);
    renderFounderMetricCard("deviceBindingPanel", "Binding and agent machine", ["No paired device yet."]);
    syncAuthControls();
    return;
  }

  if (!state.workspace.buddyId) {
    $("deviceWorkspaceStatus").textContent = "Create your first Buddy to inspect its device.";
    $("deviceOwnerInstructionInput").value = "";
    renderFounderMetricCard("deviceIdentityPanel", "Device identity", ["No paired device yet."]);
    renderFounderMetricCard("deviceHealthPanel", "Heartbeat and state", ["No paired device yet."]);
    renderFounderMetricCard("deviceDesiredStatePanel", "Desired state and revision", ["No paired device yet."]);
    renderFounderMetricCard("deviceEventPanel", "Recent device events", ["No paired device yet."]);
    renderFounderMetricCard("deviceBindingPanel", "Binding and agent machine", ["No paired device yet."]);
    syncAuthControls();
    return;
  }

  if (!device) {
    $("deviceWorkspaceStatus").textContent = "No paired device yet.";
    delete state.ui.deviceReminderDraftsByBuddy[state.workspace.buddyId];
    $("deviceOwnerInstructionInput").value = "";
    renderFounderMetricCard("deviceIdentityPanel", "Device identity", ["No paired device yet."]);
    renderFounderMetricCard("deviceHealthPanel", "Heartbeat and state", ["No paired device yet."]);
    renderFounderMetricCard("deviceDesiredStatePanel", "Desired state and revision", ["No paired device yet."]);
    renderFounderMetricCard("deviceEventPanel", "Recent device events", ["No paired device yet."]);
    renderFounderMetricCard("deviceBindingPanel", "Binding and agent machine", ["No paired device yet."]);
    syncAuthControls();
    return;
  }

  $("deviceWorkspaceStatus").textContent = "Owner-auth desired state can be published from this browser.";
  $("deviceOwnerInstructionInput").value = state.ui.deviceReminderDraftsByBuddy[state.workspace.buddyId] || "";
  renderFounderMetricCard("deviceIdentityPanel", "Device identity", [
    `Device: ${device.device_id}`,
    `Firmware: ${device.firmware_version || "-"}`,
    `Space: ${device.space_id}`,
  ]);
  renderFounderMetricCard("deviceHealthPanel", "Heartbeat and state", [
    heartbeat ? `Current state: ${heartbeat.current_state}` : "Current state: unknown",
    heartbeat ? `Wi-Fi RSSI: ${heartbeat.wifi_rssi}` : "Wi-Fi RSSI: unknown",
    heartbeat ? `Uptime: ${heartbeat.uptime_seconds}s` : "Uptime: unknown",
    heartbeat ? `Heartbeat: ${heartbeat.created_at}` : "Heartbeat: waiting for first heartbeat",
  ]);
  renderFounderMetricCard("deviceDesiredStatePanel", "Desired state and revision", [
    `Desired state: ${desiredState?.state || "idle"}`,
    `Revision: ${desiredState?.revision || 0}`,
    `Manual required: ${desiredState?.manual_required ? "yes" : "no"}`,
    desiredState?.updated_at ? `Updated: ${desiredState.updated_at}` : "Updated: -",
  ]);
  renderFounderMetricCard(
    "deviceEventPanel",
    "Recent device events",
    deviceEvents.length
      ? deviceEvents.slice(-5).reverse().map((event) => `${event.event_type} · ${event.created_at}`)
      : ["No device events yet."],
  );
  renderFounderMetricCard("deviceBindingPanel", "Binding and agent machine", [
    binding ? `Role: ${binding.role}` : "Role: unbound",
    binding ? `Authority epoch: ${binding.authority_epoch}` : "Authority epoch: -",
    agentMachine ? `Machine: ${agentMachine.agent_machine_id} · ${agentMachine.machine_type}` : "Machine: none",
    agentMachine ? `Machine status: ${agentMachine.status}` : "Machine status: unknown",
  ]);
  syncAuthControls();
}

function renderAgentManagement() {
  const hasWorkspace = isAuthenticated();
  const hasAgents = Boolean(state.workspace.agents.length);
  const hasAgentMachines = Boolean(state.workspace.agentMachines.length);
  const statusNode = $("agentManagementStatus");
  const actionStatusNode = $("agentManagementActionStatus");
  const list = $("agentManagementList");
  const createButton = $("createAgentButton");
  const hasAgentName = Boolean($("agentManagementNameInput")?.value.trim());

  if (!hasWorkspace) {
    renderTextList(
      "agentManagementList",
      ["Sign in to inspect registered agents and agent machines."],
      "Sign in to inspect registered agents and agent machines.",
      (line) => line,
    );
    statusNode.textContent = "Sign in to inspect registered agents and agent machines.";
    actionStatusNode.textContent = "Sign in to manage agents.";
    return;
  }

  list.replaceChildren();
  actionStatusNode.textContent = "Agent registration controls are ready.";
  if (createButton) {
    createButton.disabled = !hasAgentName;
  }

  if (!hasAgents && !hasAgentMachines) {
    const emptyItem = document.createElement("li");
    emptyItem.textContent = "No agents or agent machines are registered yet.";
    list.appendChild(emptyItem);
    statusNode.textContent = "No agents or agent machines are registered yet.";
    return;
  }

  if (hasAgents) {
    const sortedAgents = [...state.workspace.agents].sort((left, right) => {
      const leftName = (left.name || "").toLowerCase();
      const rightName = (right.name || "").toLowerCase();
      if (leftName === rightName) {
        return (left.role || "").localeCompare(right.role || "");
      }
      return leftName.localeCompare(rightName);
    });

    const agentHeader = document.createElement("li");
    agentHeader.className = "proposal-card";
    const headerTitle = document.createElement("strong");
    headerTitle.textContent = "Registered agents";
    agentHeader.appendChild(headerTitle);
    list.appendChild(agentHeader);

    sortedAgents.forEach((agent) => {
      const item = document.createElement("li");
      item.className = "proposal-card";
      const heading = document.createElement("strong");
      const agentName = agent.name || "Unnamed agent";
      const agentRole = agent.role || "unknown";
      heading.textContent = `${agentName} · ${agentRole}`;
      item.appendChild(heading);

      const meta = document.createElement("p");
      meta.className = "support-copy";
      meta.textContent = `Status: ${agent.status} · Version: ${agent.version || "-"}`;
      item.appendChild(meta);

      const ids = document.createElement("p");
      ids.className = "support-copy";
      ids.textContent = `Agent ID: ${agent.agent_id}`;
      item.appendChild(ids);

      const lastSeen = document.createElement("p");
      lastSeen.className = "support-copy";
      lastSeen.textContent = `Last seen: ${agent.last_seen || "never"}`;
      item.appendChild(lastSeen);

      const metadataKeys = Object.keys(agent.metadata || {});
      const capabilityKeys = Object.keys(agent.capabilities || {});
      const extra = document.createElement("p");
      extra.className = "support-copy";
      extra.textContent = `Metadata: ${metadataKeys.length ? metadataKeys.join(", ") : "none"} · Capabilities: ${
        capabilityKeys.length ? capabilityKeys.join(", ") : "none"
      }`;
      item.appendChild(extra);

      const heartbeatSection = document.createElement("div");
      heartbeatSection.className = "button-row";
      heartbeatSection.style.gap = "8px";
      heartbeatSection.style.alignItems = "end";

      const heartbeatStatusField = document.createElement("label");
      heartbeatStatusField.className = "field";
      heartbeatStatusField.style.flex = "1";
      const heartbeatStatusLabel = document.createElement("span");
      heartbeatStatusLabel.textContent = "Status";
      heartbeatStatusField.appendChild(heartbeatStatusLabel);
      const heartbeatStatus = document.createElement("select");
      heartbeatStatus.id = `agentHeartbeatStatus-${agent.agent_id}`;
      heartbeatStatus.className = "agent-heartbeat-control";
      AGENT_STATUSES.forEach((optionValue) => {
        const option = document.createElement("option");
        option.value = optionValue;
        option.textContent = optionValue;
        heartbeatStatus.appendChild(option);
      });
      heartbeatStatus.value = agent.status || "starting";
      heartbeatStatusField.appendChild(heartbeatStatus);
      heartbeatSection.appendChild(heartbeatStatusField);

      const heartbeatVersionField = document.createElement("label");
      heartbeatVersionField.className = "field";
      heartbeatVersionField.style.flex = "1";
      const heartbeatVersionLabel = document.createElement("span");
      heartbeatVersionLabel.textContent = "Version";
      heartbeatVersionField.appendChild(heartbeatVersionLabel);
      const heartbeatVersion = document.createElement("input");
      heartbeatVersion.id = `agentHeartbeatVersion-${agent.agent_id}`;
      heartbeatVersion.className = "agent-heartbeat-control";
      heartbeatVersion.type = "text";
      heartbeatVersion.placeholder = "例如：v1.0.0";
      heartbeatVersion.value = agent.version || "";
      heartbeatVersionField.appendChild(heartbeatVersion);
      heartbeatSection.appendChild(heartbeatVersionField);

      const sendHeartbeatButton = document.createElement("button");
      sendHeartbeatButton.id = `agentHeartbeatSend-${agent.agent_id}`;
      sendHeartbeatButton.className = "secondary-button";
      sendHeartbeatButton.type = "button";
      const isHeartbeatInFlight = HEARTBEAT_REQUESTS_IN_FLIGHT.has(agent.agent_id);
      sendHeartbeatButton.disabled = isHeartbeatInFlight;
      sendHeartbeatButton.textContent = isHeartbeatInFlight ? "Sending heartbeat..." : "Send heartbeat";
      heartbeatStatus.disabled = isHeartbeatInFlight;
      heartbeatVersion.disabled = isHeartbeatInFlight;
      sendHeartbeatButton.addEventListener("click", async () => {
        await sendAgentHeartbeat(agent.agent_id);
      });
      heartbeatSection.appendChild(sendHeartbeatButton);

      item.appendChild(heartbeatSection);

      list.appendChild(item);
    });
  }

  if (hasAgentMachines) {
    const machineHeader = document.createElement("li");
    machineHeader.className = "proposal-card";
    const machineTitle = document.createElement("strong");
    machineTitle.textContent = "Agent machines";
    machineHeader.appendChild(machineTitle);
    list.appendChild(machineHeader);

    state.workspace.agentMachines.forEach((agentMachine) => {
      const item = document.createElement("li");
      item.className = "proposal-card";
      const header = document.createElement("strong");
      const machineType = agentMachine.machine_type || "agent-machine";
      const machineStatus = agentMachine.status || "unknown";
      header.textContent = `${machineType} · ${machineStatus}`;
      item.appendChild(header);

      const machineId = document.createElement("p");
      machineId.className = "support-copy";
      machineId.textContent = `Machine ID: ${agentMachine.agent_machine_id || "-"}`;
      item.appendChild(machineId);

      const machineVersion = document.createElement("p");
      machineVersion.className = "support-copy";
      machineVersion.textContent = `Runtime: ${agentMachine.runtime_version || "-"}`;
      item.appendChild(machineVersion);

      const machineOwner = document.createElement("p");
      machineOwner.className = "support-copy";
      machineOwner.textContent = `Owner: ${agentMachine.owner_user_id || "-"}`;
      item.appendChild(machineOwner);

      list.appendChild(item);
    });
  }

  statusNode.textContent = `Agents: ${state.workspace.agents.length} · Agent machines: ${state.workspace.agentMachines.length}`;
}

function parseAgentHeartbeatVersion(versionValue) {
  const trimmed = (versionValue || "").trim();
  return trimmed ? trimmed : null;
}

async function sendAgentHeartbeat(agentId) {
  if (!state.auth.user) {
    $("agentManagementActionStatus").textContent = "Sign in to send heartbeat.";
    return;
  }

  const statusNode = $("agentManagementActionStatus");
  const statusSelect = $(`agentHeartbeatStatus-${agentId}`);
  const versionInput = $(`agentHeartbeatVersion-${agentId}`);
  const heartbeatButton = $(`agentHeartbeatSend-${agentId}`);

  if (!statusSelect) {
    statusNode.textContent = "Heartbeat controls unavailable.";
    return;
  }
  if (!heartbeatButton) {
    statusNode.textContent = "Heartbeat controls unavailable.";
    return;
  }
  if (!versionInput) {
    statusNode.textContent = "Heartbeat controls unavailable.";
    return;
  }
  if (HEARTBEAT_REQUESTS_IN_FLIGHT.has(agentId)) {
    statusNode.textContent = "Heartbeat send already in progress.";
    return;
  }

  const statusValue = statusSelect.value;
  const version = parseAgentHeartbeatVersion(versionInput?.value);
  const currentAgent = state.workspace.agents.find((entry) => entry.agent_id === agentId);

  if (!currentAgent) {
    statusNode.textContent = "Agent not found.";
    return;
  }

  statusNode.textContent = `Sending heartbeat for ${currentAgent.name || agentId}...`;
  HEARTBEAT_REQUESTS_IN_FLIGHT.add(agentId);
  statusSelect.disabled = true;
  versionInput.disabled = true;
  heartbeatButton.disabled = true;
  heartbeatButton.textContent = "Sending heartbeat...";

  try {
    await requestJson(`/agents/${agentId}/heartbeat`, {
      method: "POST",
      body: JSON.stringify({
        status: statusValue,
        version,
        capabilities: currentAgent.capabilities || {},
      }),
    });
    statusNode.textContent = `Heartbeat sent for ${currentAgent.name || agentId}.`;
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    statusNode.textContent = `Heartbeat failed: ${error.message}`;
  } finally {
    HEARTBEAT_REQUESTS_IN_FLIGHT.delete(agentId);
    if (statusSelect) {
      statusSelect.disabled = false;
    }
    if (versionInput) {
      versionInput.disabled = false;
    }
    if (heartbeatButton) {
      heartbeatButton.disabled = false;
      heartbeatButton.textContent = "Send heartbeat";
    }
  }
}

async function createAgent() {
  if (!state.auth.user) {
    $("agentManagementActionStatus").textContent = "Sign in before registering an agent.";
    return;
  }
  const agentName = $("agentManagementNameInput").value.trim();
  const agentRole = $("agentManagementRoleSelect").value;
  if (!agentName) {
    $("agentManagementActionStatus").textContent = "Agent name is required.";
    return;
  }

  $("agentManagementActionStatus").textContent = "Registering agent...";

  try {
    await requestJson("/agents", {
      method: "POST",
      body: JSON.stringify({
        name: agentName,
        role: agentRole,
      }),
    });
    $("agentManagementNameInput").value = "";
    $("agentManagementActionStatus").textContent = `Registered ${agentName}.`;
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    $("agentManagementActionStatus").textContent = `Agent registration failed: ${error.message}`;
  }
}

function renderExperienceShell() {
  renderAuthRail();
  renderBuddyHero();
  renderConfirmedState();
  renderCaptureComposer();
  renderProposalInbox();
  renderLatestAnswer();
  renderRecipeShelf();
  renderShoppingPass();
  renderAgentManagement();
  renderRecentActivity();
  renderCostGovernancePanel();
  renderProactiveMemoryCard();
  renderDetailsDrawer();
  renderFounderMetrics();
  renderDeviceWorkspace();
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
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    clearSession();
    setAuthStatus("Stored session expired. Please login again.", "error");
    await refreshWorkspace();
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
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setAuthStatus(`Create Buddy failed: ${error.message}`, "error");
  }
}

async function loadAuthWorkspace() {
  await refreshWorkspace();
}

function projectWorkspace(snapshot) {
  if (!isAuthenticated()) {
    state.workspace.stateRevision = 0;
    state.workspace.buddies = [];
    state.workspace.agents = [];
    state.workspace.buddyId = null;
    state.workspace.agentMachines = [];
    state.workspace.confirmedItems = [];
    state.workspace.pendingProposals = [];
    state.workspace.recipes = [];
    state.workspace.shoppingPassItems = [];
    state.workspace.shoppingPassSummary = {};
    state.workspace.latestQuery = null;
    state.workspace.recentActivity = [];
    state.workspace.proactiveHint = null;
    state.workspace.summary = {};
    state.workspace.traces = [];
    state.workspace.costSummary = {};
    state.workspace.planUsage = {};
    state.workspace.engagementMetrics = null;
    state.workspace.retentionSummary = null;
    state.workspace.founderMetricsVisible = false;
    state.workspace.founderMetricsUnavailableReason = null;
    state.workspace.device = null;
    state.workspace.agentMachine = null;
    state.workspace.binding = null;
    state.workspace.latestHeartbeat = null;
    state.workspace.desiredState = null;
    state.workspace.deviceEvents = [];
    state.ui.proactiveHint = null;
  } else {
    state.workspace.stateRevision = snapshot.state_revision || 0;
    state.workspace.buddies = snapshot.buddies || [];
    state.workspace.agents = snapshot.agents || [];
    if (state.workspace.buddies.length && !state.workspace.buddyId) {
      state.workspace.buddyId = state.workspace.buddies[0].buddy_id;
    }

    const buddyId = state.workspace.buddyId;
    const stateMemory = snapshot.state_memory || {};
    state.workspace.confirmedItems = buddyId ? stateMemory.items_by_buddy?.[buddyId] || [] : [];
    state.workspace.pendingProposals = buddyId ? stateMemory.pending_proposals_by_buddy?.[buddyId] || [] : [];
    state.workspace.recipes = buddyId ? stateMemory.recipes_by_buddy?.[buddyId] || [] : [];
    state.workspace.shoppingPassItems = buddyId ? stateMemory.shopping_pass_by_buddy?.[buddyId] || [] : [];
    state.workspace.shoppingPassSummary = buddyId ? stateMemory.shopping_pass_summary_by_buddy?.[buddyId] || {} : {};
    state.workspace.latestQuery = buddyId ? stateMemory.latest_query_by_buddy?.[buddyId] || null : null;
    state.workspace.recentActivity = buddyId ? stateMemory.recent_activity_by_buddy?.[buddyId] || [] : [];
    state.workspace.proactiveHint = buddyId ? stateMemory.proactive_hint_by_buddy?.[buddyId] || null : null;
    state.workspace.summary = buddyId ? stateMemory.summary_by_buddy?.[buddyId] || {} : {};
    state.workspace.traces = snapshot.traces || [];
    state.workspace.costSummary = snapshot.cost_summary || {};
    state.workspace.planUsage = snapshot.plan_usage || {};
    const devices = snapshot.devices || [];
    const bindings = snapshot.bindings || [];
    const agentMachines = snapshot.agent_machines || [];
    state.workspace.agentMachines = agentMachines;
    const latestHeartbeats = snapshot.latest_heartbeats || {};
    const desiredStates = snapshot.desired_states || {};
    const deviceEvents = snapshot.device_events || [];
    state.workspace.device = devices.find((entry) => entry.buddy_id === buddyId) || null;
    state.workspace.binding = bindings.find((entry) => entry.buddy_id === buddyId) || null;
    state.workspace.agentMachine = state.workspace.binding
      ? agentMachines.find((entry) => entry.agent_machine_id === state.workspace.binding.agent_machine_id) || null
      : null;
    state.workspace.latestHeartbeat = state.workspace.device
      ? latestHeartbeats[state.workspace.device.device_id] || null
      : null;
    state.workspace.desiredState = state.workspace.device
      ? desiredStates[state.workspace.device.device_id] || null
      : null;
    state.workspace.deviceEvents = state.workspace.device
      ? deviceEvents.filter((entry) => entry.device_id === state.workspace.device.device_id)
      : [];
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

async function loadFounderMetrics() {
  if (!isAuthenticated()) {
    state.workspace.engagementMetrics = null;
    state.workspace.retentionSummary = null;
    state.workspace.founderMetricsVisible = false;
    state.workspace.founderMetricsUnavailableReason = null;
    renderFounderMetrics();
    return;
  }
  if (!state.auth.user?.founder_metrics_allowed) {
    state.workspace.engagementMetrics = null;
    state.workspace.retentionSummary = null;
    state.workspace.founderMetricsVisible = false;
    state.workspace.founderMetricsUnavailableReason = null;
    renderFounderMetrics();
    return;
  }

  const requestGeneration = ++state.ui.founderMetricsRequestGeneration;
  const requestSessionToken = state.auth.accessToken;

  try {
    const retentionSummary = await requestJson("/metrics/retention-summary", { headers: {} });
    const engagementMetrics = await requestJson("/metrics/engagement", { headers: {} });
    if (
      requestGeneration !== state.ui.founderMetricsRequestGeneration ||
      requestSessionToken !== state.auth.accessToken ||
      !isAuthenticated()
    ) {
      return;
    }
    state.workspace.engagementMetrics = engagementMetrics;
    state.workspace.retentionSummary = retentionSummary;
    state.workspace.founderMetricsVisible = true;
    state.workspace.founderMetricsUnavailableReason = null;
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    if (
      requestGeneration !== state.ui.founderMetricsRequestGeneration ||
      requestSessionToken !== state.auth.accessToken ||
      !isAuthenticated()
    ) {
      return;
    }
    state.workspace.engagementMetrics = null;
    state.workspace.retentionSummary = null;
    state.workspace.founderMetricsVisible = true;
    state.workspace.founderMetricsUnavailableReason = error.message;
  }
  renderFounderMetrics();
}

async function loadSyncSnapshot() {
  const snapshot = await requestJson("/sync/snapshot", { headers: {} });
  projectWorkspace(snapshot);
  renderExperienceShell();
}

async function refreshWorkspace() {
  await loadAuthBuddies();
  await loadSyncSnapshot();
  loadFounderMetrics().catch(() => {});
}

async function publishDeviceDesiredState() {
  if (!state.workspace.buddyId || !state.workspace.device) {
    $("deviceWorkspaceStatus").textContent = "No paired device yet.";
    return;
  }
  const instruction = $("deviceOwnerInstructionInput").value.trim();
  if (!instruction) {
    $("deviceWorkspaceStatus").textContent = "Manual reminder text is required.";
    syncAuthControls();
    return;
  }
  try {
    const response = await requestJson(
      `/me/buddies/${state.workspace.buddyId}/devices/${state.workspace.device.device_id}/desired-state`,
      {
        method: "POST",
        body: JSON.stringify({
          reminder_text: instruction,
        }),
      },
    );
    state.ui.deviceReminderDraftsByBuddy[state.workspace.buddyId] = "";
    $("deviceOwnerInstructionInput").value = "";
    await refreshWorkspace();
    $("deviceWorkspaceStatus").textContent = `Desired state published at revision ${response.desired_state.revision}.`;
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    $("deviceWorkspaceStatus").textContent = `Publish failed: ${error.message}`;
  }
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
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
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
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
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
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
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
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setWorkspaceStatus(`Query failed: ${error.message}`);
  }
}

async function submitRecipe() {
  if (!state.workspace.buddyId) {
    setWorkspaceStatus("Create or select a Buddy before saving a recipe.");
    return;
  }
  const name = $("recipeNameInput").value.trim();
  const ingredients = $("recipeIngredientsInput").value
    .split(/[，,]/)
    .map((value) => value.trim())
    .filter(Boolean);
  if (!name || !ingredients.length) {
    setWorkspaceStatus("Recipe name and ingredients are required.");
    syncAuthControls();
    return;
  }
  try {
    const response = await requestJson(`/me/buddies/${state.workspace.buddyId}/state-memory/recipes`, {
      method: "POST",
      body: JSON.stringify({ name, ingredients }),
    });
    $("recipeNameInput").value = "";
    $("recipeIngredientsInput").value = "";
    setWorkspaceStatus(`Saved recipe: ${formatRecipe(response.recipe)}`);
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setWorkspaceStatus(`Recipe save failed: ${error.message}`);
  }
}

async function deleteRecipe(recipeId) {
  try {
    await requestJson(`/me/buddies/${state.workspace.buddyId}/state-memory/recipes/${recipeId}`, {
      method: "DELETE",
    });
    setWorkspaceStatus("Recipe deleted.");
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setWorkspaceStatus(`Recipe delete failed: ${error.message}`);
  }
}

async function addShoppingPassItem() {
  if (!state.workspace.buddyId) {
    setWorkspaceStatus("Create or select a Buddy before adding a shopping-pass item.");
    return;
  }
  const name = $("shoppingPassNameInput").value.trim();
  if (!name) {
    setWorkspaceStatus("Shopping-pass item name is required.");
    syncAuthControls();
    return;
  }
  try {
    const response = await requestJson(`/me/buddies/${state.workspace.buddyId}/state-memory/shopping-pass/items`, {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    $("shoppingPassNameInput").value = "";
    setWorkspaceStatus(`Shopping pass item added: ${response.item.name}`);
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setWorkspaceStatus(`Shopping pass add failed: ${error.message}`);
  }
}

async function promoteShoppingPassHint() {
  if (!state.workspace.buddyId) {
    setWorkspaceStatus("Create or select a Buddy before promoting a shopping hint.");
    return;
  }
  try {
    const response = await requestJson(`/me/buddies/${state.workspace.buddyId}/state-memory/shopping-pass/promote-hint`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    setWorkspaceStatus(`Shopping pass item added from hint: ${response.item.name}`);
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setWorkspaceStatus(`Shopping pass hint promotion failed: ${error.message}`);
  }
}

async function promoteShoppingPassLatestQuery() {
  if (!state.workspace.buddyId) {
    setWorkspaceStatus("Create or select a Buddy before promoting the latest query.");
    return;
  }
  try {
    const response = await requestJson(`/me/buddies/${state.workspace.buddyId}/state-memory/shopping-pass/promote-latest-query`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    const itemNames = (response.items || []).map((item) => item.name);
    setWorkspaceStatus(
      itemNames.length
        ? `Shopping pass updated from latest query: ${itemNames.join(" / ")}`
        : "Shopping pass updated from latest query.",
    );
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setWorkspaceStatus(`Shopping pass query promotion failed: ${error.message}`);
  }
}

async function markShoppingPassItemDone(shoppingItemId) {
  if (!state.workspace.buddyId) {
    setWorkspaceStatus("Create or select a Buddy before finishing a shopping-pass item.");
    return;
  }
  try {
    const response = await requestJson(`/me/buddies/${state.workspace.buddyId}/state-memory/shopping-pass/items/${shoppingItemId}/done`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    setWorkspaceStatus(`Shopping pass item done: ${response.item.name}`);
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setWorkspaceStatus(`Shopping pass done failed: ${error.message}`);
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
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
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
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
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
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setWorkspaceStatus(`Correction failed: ${error.message}`);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  state.ui.voice.supported = voiceRecognitionSupported();
  $("authRegisterButton").addEventListener("click", registerAuth);
  $("authLoginButton").addEventListener("click", loginAuth);
  $("authLogoutButton").addEventListener("click", logoutAuth);
  $("createMyBuddyButton").addEventListener("click", createMyBuddy);
  $("createAgentButton").addEventListener("click", createAgent);
  $("agentManagementNameInput").addEventListener("input", syncAuthControls);
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
  $("recipeNameInput").addEventListener("input", syncAuthControls);
  $("recipeIngredientsInput").addEventListener("input", syncAuthControls);
  $("createRecipeButton").addEventListener("click", submitRecipe);
  $("shoppingPassNameInput").addEventListener("input", syncAuthControls);
  $("shoppingPassAddButton").addEventListener("click", addShoppingPassItem);
  $("shoppingPassPromoteHintButton").addEventListener("click", promoteShoppingPassHint);
  $("shoppingPassPromoteLatestQueryButton").addEventListener("click", promoteShoppingPassLatestQuery);
  $("submitCorrectionButton").addEventListener("click", submitCorrection);
  $("dismissProactiveHintButton").addEventListener("click", dismissProactiveHint);
  $("deviceOwnerInstructionInput").addEventListener("input", () => {
    if (state.workspace.buddyId && state.workspace.device) {
      state.ui.deviceReminderDraftsByBuddy[state.workspace.buddyId] = $("deviceOwnerInstructionInput").value;
    }
    syncAuthControls();
  });
  $("publishDeviceDesiredStateButton").addEventListener("click", publishDeviceDesiredState);
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
