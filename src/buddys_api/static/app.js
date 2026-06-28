const SESSION_STORAGE_KEY = "buddysAccessToken";
const VOICE_UNSUPPORTED_COPY = "当前浏览器暂不支持语音采集。";
const UNRECOGNIZED_COPY = "我听到了内容，但还没法完整结构化。";
const DEFAULT_CAPTURE_EMPTY = "暂未有已确认库存。";
const DEFAULT_PENDING_EMPTY = "暂无待确认提案。";
const DEFAULT_QUERY_EMPTY = "还未提交过状态查询。";
const DEFAULT_RECIPE_EMPTY = "暂无已保存食谱。";
const DEFAULT_SHOPPING_PASS_EMPTY = "还没有购物清单项。";
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
  $("agentManagementActionStatus").textContent = "暂无已注册智能体。";
  $("deviceOwnerInstructionInput").value = "";
  $("recipeNameInput").value = "";
  $("recipeIngredientsInput").value = "";
  $("shoppingPassNameInput").value = "";
  renderExperienceShell();
}

async function recoverExpiredSession() {
  clearSession();
  setAuthStatus("登录已过期，请重新登录。", "error");
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
        ? "未登录：当前仅允许邀请码注册。"
        : "未登录：请登录后使用状态管理。",
    );
  }
  $("authInviteCodeInput").placeholder = BUDDYS_BOOTSTRAP.inviteRequired
    ? "请输入邀请码"
    : "未启用邀请码时可留空";

  const select = $("authBuddySelect");
  select.replaceChildren();
  if (!state.workspace.buddies.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = isAuthenticated() ? "还未创建 Buddy" : "登录后可查看你的 Buddy";
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
    $("buddyGreeting").textContent = "Buddy 已就绪";
    $("buddyNameHeading").textContent = "我的 Buddy";
    $("buddySummaryLine").textContent =
      "告诉 Buddy 你买了什么、用了什么，再问它家里还剩哪些。";
    $("overviewTitle").textContent = "我的 Buddy";
    $("buddySpace").textContent = "家庭";
    $("buddyState").textContent = isAuthenticated() ? "待初始化" : "未登录";
    return;
  }
  $("buddyGreeting").textContent = `你好，我在替你看管 ${buddy.space_id}。`;
  $("buddyNameHeading").textContent = buddy.name;
  $("buddySummaryLine").textContent = "先录入状态，再复核一次，随后提问可给出证据依据。";
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
    setWorkspaceStatus("请先登录并选择一个 Buddy 后再进行状态操作。");
  } else if (!state.workspace.buddyId) {
    setWorkspaceStatus("请先创建第一个 Buddy，解锁录入、查询与提案审核流程。");
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
    ? `已选照片：${state.ui.photo.fileName}`
    : "未选择照片。";
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
    return "正在录音，请说一条简短更新。";
  }
  if (state.ui.voice.status === "captured") {
    return "语音转写完成，可直接提交流程。";
  }
  if (state.ui.voice.status === "error") {
    return "语音采集失败，请重试或手动输入。";
  }
  return "语音转写空闲。";
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
    setWorkspaceStatus("照片预览失败，请换一张图片重试。");
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
    emptyItem.textContent = "当前未选中待处理提案。";
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
  meta.textContent = `${proposal.source} · ${proposal.deltas.length} 条结构化项`;
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
  selectButton.textContent = "编辑修正";
  selectButton.addEventListener("click", () => {
    state.ui.selectedProposalId = proposal.proposal_id;
    $("proposalCorrectionInput").value = JSON.stringify(proposal.deltas, null, 2);
    setWorkspaceStatus(`已加载 ${proposal.content} 的修正草稿。`);
    syncAuthControls();
  });

  const confirmButton = document.createElement("button");
  confirmButton.type = "button";
  confirmButton.className = "primary-button";
  confirmButton.textContent = "确认";
  confirmButton.addEventListener("click", () => confirmProposal(proposal.proposal_id));

  const rejectButton = document.createElement("button");
  rejectButton.type = "button";
  rejectButton.className = "secondary-button";
  rejectButton.textContent = "拒绝";
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
    $("stateMemoryQueryMeta").textContent = "发起状态查询后，相关证据会展示在这里。";
    renderTextList("stateMemoryEvidenceList", [], "尚未抓取到证据项。", () => "");
    return;
  }
  $("stateMemoryQuerySummary").textContent = latestQuery.summary;
  $("stateMemoryQueryMeta").textContent = latestQuery.missing_items?.length
    ? `Buddy 已基于历史证据作答，仍缺失：${latestQuery.missing_items.join(" / ")}。`
    : "Buddy 已基于历史证据作答。";
  renderTextList(
    "stateMemoryEvidenceList",
    latestQuery.evidence_items || [],
    latestQuery.evidence_item_ids?.length ? "证据明细暂不可用。" : "尚未抓取到证据项。",
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
    $("recipeShelfStatus").textContent = "请先登录后为该 Buddy 保存食谱。";
  } else if (!state.workspace.buddyId) {
    $("recipeShelfStatus").textContent = "请先创建一个 Buddy，再开始保存食谱。";
  } else {
    $("recipeShelfStatus").textContent = state.workspace.recipes.length
      ? "已保存的食谱会优先用于配方缺口应答。"
      : "先保存一条食谱，可让回答更贴合该 Buddy。";
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
    deleteButton.textContent = "删除";
    deleteButton.addEventListener("click", () => deleteRecipe(recipe.recipe_id));

    actions.appendChild(deleteButton);
    item.appendChild(actions);
    list.appendChild(item);
  });

  syncAuthControls();
}

function shoppingPassSourceLabel(item) {
  if (item.source_kind === "manual") {
    return "手动";
  }
  if (item.source_kind === "proactive_hint") {
    return "提示";
  }
  if (item.source_kind === "missing_for_recipe") {
    return "食谱缺口";
  }
  return item.source_kind || "未知";
}

function renderShoppingPass() {
  const list = $("shoppingPassList");
  const summary = state.workspace.shoppingPassSummary || {};
  list.replaceChildren();

  if (!isAuthenticated()) {
    $("shoppingPassStatus").textContent = "请先登录后再为该 Buddy 生成购物清单。";
  } else if (!state.workspace.buddyId) {
    $("shoppingPassStatus").textContent = "请先创建并选择一个 Buddy，再规划下一次购物清单。";
  } else if (state.workspace.shoppingPassItems.length) {
    const openCount = Number(summary.open_count || state.workspace.shoppingPassItems.length || 0);
    const doneCount = Number(summary.done_count || 0);
    $("shoppingPassStatus").textContent = `还有 ${openCount} 项未完成，${doneCount} 项已完成。`;
  } else if (Number(summary.done_count || 0) > 0) {
    $("shoppingPassStatus").textContent = "当前补货清单已处理完毕。可手动添加新条目，或从最新提示/问题补充。";
  } else {
    $("shoppingPassStatus").textContent =
      "可手动添加条目，或通过“最近提示/问题”补齐下次购物清单。";
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
    doneButton.textContent = "完成";
    doneButton.addEventListener("click", () => markShoppingPassItemDone(item.shopping_item_id));

    actions.appendChild(doneButton);
    entry.appendChild(actions);
    list.appendChild(entry);
  });

  syncAuthControls();
}

function formatRecentActivity(activity) {
  return activity.summary || "Buddy 最近有操作记录。";
}

function renderRecentActivity() {
  const activities = (state.workspace.recentActivity || []).slice().reverse();
  const status = $("buddyActivityStatus");

  if (!isAuthenticated()) {
    status.textContent = "请先登录后查看 Buddy 的最新更新与应答。";
    renderTextList("buddyActivityList", [], "暂无最近活动。", () => "");
    return;
  }
  if (!state.workspace.buddyId) {
    status.textContent = "请先创建一个 Buddy 再查看最近活动与应答。";
    renderTextList("buddyActivityList", [], "暂无最近活动。", () => "");
    return;
  }

  status.textContent = activities.length
    ? "Buddy 会在此展示最近保存的更新、复核与应答。"
    : "Buddy 将在此展示最近保存的更新与应答。";

  renderTextList("buddyActivityList", activities, "暂无最近活动。", (activity) => {
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
    : "暂无服务商用量数据。";
  const topModelCopy = topModelEntry
    ? `${topModelEntry[0]} · ${topModelEntry[1].total_tokens || 0} tokens`
    : "暂无模型用量数据。";

  if (!isAuthenticated()) {
    $("costGovernanceStatus").textContent = "请先登录查看 Token 与消费透明度。";
    renderTextList("planUsageList", [], "登录后可查看用量明细。", (line) => line);
    renderTextList("planUsageBreakdownList", [], "登录后可查看服务商/模型用量。", (line) => line);
    $("planGovernanceCostRow").textContent = "暂无成本快照。";
    return;
  }

  if (!planUsage || !Object.keys(planUsage).length) {
    $("costGovernanceStatus").textContent = "暂未拿到用量汇总。";
    renderTextList("planUsageList", [], "暂无套餐用量快照。", (line) => line);
    renderTextList("planUsageBreakdownList", [], "暂无用量细分。", (line) => line);
    $("planGovernanceCostRow").textContent = "暂无成本快照。";
    return;
  }

  planLines.push(`套餐：${planId}`);
  planLines.push(`月份：${usageMonth}`);
  planLines.push(`已用令牌：${usedTokens}`);
  planLines.push(`月度上限：${monthlyLimit || 0}`);
  planLines.push(
    `剩余令牌：${remainingTokens === null ? "不限" : remainingTokens.toLocaleString("en-US")}`,
  );
  planLines.push(`硬性上限：${hardLimit === "enabled" ? "已开启" : "未开启"}`);
  planLines.push(`BYOK 模式：${planUsage.byok ? "开启" : "关闭"}`);
  if (planUsage.over_limit) {
    planLines.push("配额状态：已达上限");
  } else {
    planLines.push("配额状态：正常");
  }

  $("costGovernanceStatus").textContent = "Token 与成本快照已从服务端更新。";
  renderTextList("planUsageList", planLines, "成本汇总为空。", (line) => line);
  renderTextList("planUsageBreakdownList", [topProviderCopy, topModelCopy], "暂无用量细分。", (line) => line);
  $("planGovernanceCostRow").textContent = `预计支出：${money(costSummary.model_cost_usd + costSummary.tool_cost_usd + costSummary.log_cost_usd || 0)} / ${costEventCny(
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
  $("proactiveTitle").textContent = "Buddy 发现提醒";
  $("proactiveMessage").textContent = hint.message;
  $("proactiveBasis").textContent = `基于 ${hint.basis.item_names.join(" / ")}`;
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
    $("answerBasisQuestion").textContent = "当前无可展示的回答依据。";
    $("answerBasisSummary").textContent = "请先向 Buddy 提问以查看证据详情。";
    const emptyItem = document.createElement("li");
    emptyItem.textContent = "尚未返回证据。";
    list.appendChild(emptyItem);
    return;
  }

  $("answerBasisQuestion").textContent = `${latestQuery.question} · ${latestQuery.answer_type}`;
  $("answerBasisSummary").textContent = latestQuery.missing_items?.length
    ? `${latestQuery.summary}；缺失：${latestQuery.missing_items.join(" / ")}`
    : latestQuery.summary;

  if (!(latestQuery.evidence_items || []).length) {
    const emptyItem = document.createElement("li");
    emptyItem.textContent = "尚未返回证据。";
    list.appendChild(emptyItem);
    return;
  }

  latestQuery.evidence_items.forEach((item) => {
    const entry = document.createElement("li");
    appendLine(entry, `${item.name} · ${formatQuantity(item.quantity, item.unit)} · ${item.status}`);
    appendLine(entry, `来源：${item.source}`, "evidence-line");
    appendLine(entry, `最后出现：${item.last_seen_at}`, "evidence-line");
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
    return ["暂无创作者采集来源统计。"];
  }
  return entries.map(([source, count]) => `${source}：${count}`);
}

function renderFounderMetrics() {
  $("founderMetricsPanel").hidden = !state.workspace.founderMetricsVisible;
  if (!state.workspace.founderMetricsVisible) {
    return;
  }

  const unavailableReason = state.workspace.founderMetricsUnavailableReason;
  if (unavailableReason) {
    $("founderMetricsStatus").textContent = `创始人指标不可用：${unavailableReason}`;
    renderFounderMetricCard("founderActivationPanel", "我在用", ["创始人指标不可用"]);
    renderFounderMetricCard("founderRetentionPanel", "留存表现", ["创始人指标不可用"]);
    renderFounderMetricCard("founderCaptureMixPanel", "采集来源", ["创始人指标不可用"]);
    return;
  }

  const engagement = state.workspace.engagementMetrics || {};
  const retention = state.workspace.retentionSummary || {};
  const activated = Boolean(engagement.activation?.completed_first_capture_confirm_query);

  $("founderMetricsStatus").textContent = "当前账户已启用创始人指标。";
  renderFounderMetricCard("founderActivationPanel", "我在用", [
    activated ? "已完成首次录入-复核-提问闭环" : "未完成首次录入-复核-提问闭环",
    `已追踪事件：${engagement.event_count || 0}`,
  ]);
  renderFounderMetricCard("founderRetentionPanel", "留存表现", [
    `已激活用户：${retention.activated_users || 0}`,
    `D1 活跃：${retention.d1_active_users || 0}`,
    `D3 活跃：${retention.d3_active_users || 0}`,
    `D7 活跃：${retention.d7_active_users || 0}`,
  ]);
  renderFounderMetricCard("founderCaptureMixPanel", "采集来源", captureMixRows(retention.capture_by_source));
}

function renderDeviceWorkspace() {
  const device = state.workspace.device;
  const heartbeat = state.workspace.latestHeartbeat;
  const desiredState = state.workspace.desiredState;
  const binding = state.workspace.binding;
  const agentMachine = state.workspace.agentMachine;
  const deviceEvents = state.workspace.deviceEvents || [];

  if (!isAuthenticated()) {
    $("deviceWorkspaceStatus").textContent = "请先登录后查看该 Buddy 的绑定设备。";
    $("deviceOwnerInstructionInput").value = "";
    renderFounderMetricCard("deviceIdentityPanel", "设备身份", ["尚未绑定设备。"]);
    renderFounderMetricCard("deviceHealthPanel", "心跳与状态", ["尚未绑定设备。"]);
    renderFounderMetricCard("deviceDesiredStatePanel", "目标状态与版本", ["尚未绑定设备。"]);
    renderFounderMetricCard("deviceEventPanel", "近期设备事件", ["尚未绑定设备。"]);
    renderFounderMetricCard("deviceBindingPanel", "绑定与 Agent 机器", ["尚未绑定设备。"]);
    syncAuthControls();
    return;
  }

  if (!state.workspace.buddyId) {
    $("deviceWorkspaceStatus").textContent = "请先创建第一个 Buddy 再查看设备。";
    $("deviceOwnerInstructionInput").value = "";
    renderFounderMetricCard("deviceIdentityPanel", "设备身份", ["尚未配对设备。"]);
    renderFounderMetricCard("deviceHealthPanel", "心跳与状态", ["尚未配对设备。"]);
    renderFounderMetricCard("deviceDesiredStatePanel", "目标状态与版本", ["尚未配对设备。"]);
    renderFounderMetricCard("deviceEventPanel", "近期设备事件", ["尚未配对设备。"]);
    renderFounderMetricCard("deviceBindingPanel", "绑定与 Agent 机器", ["尚未配对设备。"]);
    syncAuthControls();
    return;
  }

  if (!device) {
    $("deviceWorkspaceStatus").textContent = "当前未配对设备。";
    delete state.ui.deviceReminderDraftsByBuddy[state.workspace.buddyId];
    $("deviceOwnerInstructionInput").value = "";
    renderFounderMetricCard("deviceIdentityPanel", "设备身份", ["当前未配对设备。"]);
    renderFounderMetricCard("deviceHealthPanel", "心跳与状态", ["当前未配对设备。"]);
    renderFounderMetricCard("deviceDesiredStatePanel", "目标状态与版本", ["当前未配对设备。"]);
    renderFounderMetricCard("deviceEventPanel", "近期设备事件", ["当前未配对设备。"]);
    renderFounderMetricCard("deviceBindingPanel", "绑定与 Agent 机器", ["当前未配对设备。"]);
    syncAuthControls();
    return;
  }

  $("deviceWorkspaceStatus").textContent = "可在当前页面发布设备提醒意图。";
  $("deviceOwnerInstructionInput").value = state.ui.deviceReminderDraftsByBuddy[state.workspace.buddyId] || "";
  renderFounderMetricCard("deviceIdentityPanel", "设备身份", [
    `设备：${device.device_id}`,
    `固件：${device.firmware_version || "未知"}`,
    `空间：${device.space_id}`,
  ]);
  renderFounderMetricCard("deviceHealthPanel", "心跳与状态", [
    heartbeat ? `当前状态：${heartbeat.current_state}` : "当前状态：未知",
    heartbeat ? `Wi-Fi 信号：${heartbeat.wifi_rssi}` : "Wi-Fi 信号：未知",
    heartbeat ? `在线时长：${heartbeat.uptime_seconds}s` : "在线时长：未知",
    heartbeat ? `最近心跳：${heartbeat.created_at}` : "最近心跳：等待首次上报",
  ]);
  renderFounderMetricCard("deviceDesiredStatePanel", "目标状态与版本", [
    `目标状态：${desiredState?.state || "空闲"}`,
    `版本：${desiredState?.revision || 0}`,
    `手动确认：${desiredState?.manual_required ? "是" : "否"}`,
    desiredState?.updated_at ? `更新时间：${desiredState.updated_at}` : "更新时间：-",
  ]);
  renderFounderMetricCard(
    "deviceEventPanel",
    "近期设备事件",
    deviceEvents.length
      ? deviceEvents.slice(-5).reverse().map((event) => `${event.event_type} · ${event.created_at}`)
      : ["暂无设备事件。"],
  );
  renderFounderMetricCard("deviceBindingPanel", "绑定与 Agent 机器", [
    binding ? `角色：${binding.role}` : "角色：未绑定",
    binding ? `权责轮次：${binding.authority_epoch}` : "权责轮次：-",
    agentMachine ? `机器：${agentMachine.agent_machine_id} · ${agentMachine.machine_type}` : "机器：未分配",
    agentMachine ? `机器状态：${agentMachine.status}` : "机器状态：未知",
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
      ["请先登录后查看已注册的智能体与 Agent 机器。"],
      "请先登录后查看已注册的智能体与 Agent 机器。",
      (line) => line,
    );
    statusNode.textContent = "请先登录后查看已注册的智能体与 Agent 机器。";
    actionStatusNode.textContent = "请先登录后管理智能体。";
    return;
  }

  list.replaceChildren();
  actionStatusNode.textContent = "智能体注册控件已就绪。";
  if (createButton) {
    createButton.disabled = !hasAgentName;
  }

  if (!hasAgents && !hasAgentMachines) {
    const emptyItem = document.createElement("li");
    emptyItem.textContent = "暂无已注册智能体或 Agent 机器。";
    list.appendChild(emptyItem);
    statusNode.textContent = "暂无已注册智能体或 Agent 机器。";
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
    headerTitle.textContent = "已注册智能体";
    agentHeader.appendChild(headerTitle);
    list.appendChild(agentHeader);

    sortedAgents.forEach((agent) => {
      const item = document.createElement("li");
      item.className = "proposal-card";
      const heading = document.createElement("strong");
      const agentName = agent.name || "未命名智能体";
      const agentRole = agent.role || "未知";
      heading.textContent = `${agentName} · ${agentRole}`;
      item.appendChild(heading);

      const meta = document.createElement("p");
      meta.className = "support-copy";
      meta.textContent = `状态：${agent.status} · 版本：${agent.version || "未知"}`;
      item.appendChild(meta);

      const ids = document.createElement("p");
      ids.className = "support-copy";
      ids.textContent = `智能体 ID：${agent.agent_id}`;
      item.appendChild(ids);

      const lastSeen = document.createElement("p");
      lastSeen.className = "support-copy";
      lastSeen.textContent = `最近在线：${agent.last_seen || "从未"}`;
      item.appendChild(lastSeen);

      const metadataKeys = Object.keys(agent.metadata || {});
      const capabilityKeys = Object.keys(agent.capabilities || {});
      const extra = document.createElement("p");
      extra.className = "support-copy";
      extra.textContent = `元数据：${metadataKeys.length ? metadataKeys.join(", ") : "无"} · 能力：${
        capabilityKeys.length ? capabilityKeys.join(", ") : "无"
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
      heartbeatStatusLabel.textContent = "状态";
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
      heartbeatVersionLabel.textContent = "版本";
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
      sendHeartbeatButton.textContent = isHeartbeatInFlight ? "发送中..." : "发送心跳";
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
    machineTitle.textContent = "Agent 机器";
    machineHeader.appendChild(machineTitle);
    list.appendChild(machineHeader);

    state.workspace.agentMachines.forEach((agentMachine) => {
      const item = document.createElement("li");
      item.className = "proposal-card";
      const header = document.createElement("strong");
      const machineType = agentMachine.machine_type || "agent-machine";
      const machineStatus = agentMachine.status || "未知";
      header.textContent = `${machineType} · ${machineStatus}`;
      item.appendChild(header);

      const machineId = document.createElement("p");
      machineId.className = "support-copy";
      machineId.textContent = `机器 ID：${agentMachine.agent_machine_id || "-"}`;
      item.appendChild(machineId);

      const machineVersion = document.createElement("p");
      machineVersion.className = "support-copy";
      machineVersion.textContent = `运行时：${agentMachine.runtime_version || "-"}`;
      item.appendChild(machineVersion);

      const machineOwner = document.createElement("p");
      machineOwner.className = "support-copy";
      machineOwner.textContent = `所属用户：${agentMachine.owner_user_id || "-"}`;
      item.appendChild(machineOwner);

      list.appendChild(item);
    });
  }

  statusNode.textContent = `智能体：${state.workspace.agents.length} · Agent 机器：${state.workspace.agentMachines.length}`;
}

function parseAgentHeartbeatVersion(versionValue) {
  const trimmed = (versionValue || "").trim();
  return trimmed ? trimmed : null;
}

async function sendAgentHeartbeat(agentId) {
  if (!state.auth.user) {
    $("agentManagementActionStatus").textContent = "请先登录后发送心跳。";
    return;
  }

  const statusNode = $("agentManagementActionStatus");
  const statusSelect = $(`agentHeartbeatStatus-${agentId}`);
  const versionInput = $(`agentHeartbeatVersion-${agentId}`);
  const heartbeatButton = $(`agentHeartbeatSend-${agentId}`);

  if (!statusSelect) {
    statusNode.textContent = "心跳控件暂不可用。";
    return;
  }
  if (!heartbeatButton) {
    statusNode.textContent = "心跳控件暂不可用。";
    return;
  }
  if (!versionInput) {
    statusNode.textContent = "心跳控件暂不可用。";
    return;
  }
  if (HEARTBEAT_REQUESTS_IN_FLIGHT.has(agentId)) {
    statusNode.textContent = "心跳发送进行中，请稍候。";
    return;
  }

  const statusValue = statusSelect.value;
  const version = parseAgentHeartbeatVersion(versionInput?.value);
  const currentAgent = state.workspace.agents.find((entry) => entry.agent_id === agentId);

  if (!currentAgent) {
    statusNode.textContent = "未找到该智能体。";
    return;
  }

  statusNode.textContent = `正在发送 ${currentAgent.name || agentId} 的心跳...`;
  HEARTBEAT_REQUESTS_IN_FLIGHT.add(agentId);
  statusSelect.disabled = true;
  versionInput.disabled = true;
  heartbeatButton.disabled = true;
  heartbeatButton.textContent = "发送中...";

  try {
    await requestJson(`/agents/${agentId}/heartbeat`, {
      method: "POST",
      body: JSON.stringify({
        status: statusValue,
        version,
        capabilities: currentAgent.capabilities || {},
      }),
    });
    statusNode.textContent = `${currentAgent.name || agentId} 的心跳已发送。`;
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    statusNode.textContent = `发送心跳失败：${error.message}`;
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
      heartbeatButton.textContent = "发送心跳";
    }
  }
}

async function createAgent() {
  if (!state.auth.user) {
    $("agentManagementActionStatus").textContent = "请先登录后再注册智能体。";
    return;
  }
  const agentName = $("agentManagementNameInput").value.trim();
  const agentRole = $("agentManagementRoleSelect").value;
  if (!agentName) {
    $("agentManagementActionStatus").textContent = "请输入智能体名称。";
    return;
  }

  $("agentManagementActionStatus").textContent = "正在注册智能体...";

  try {
    await requestJson("/agents", {
      method: "POST",
      body: JSON.stringify({
        name: agentName,
        role: agentRole,
      }),
    });
    $("agentManagementNameInput").value = "";
    $("agentManagementActionStatus").textContent = `已注册：${agentName}。`;
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    $("agentManagementActionStatus").textContent = `智能体注册失败：${error.message}`;
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
    setAuthStatus(`已登录：${state.auth.user.email}`, "ok");
    await loadAuthWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    clearSession();
    setAuthStatus("会话已过期，请重新登录。", "error");
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
    setAuthStatus("注册需填写邮箱和密码。", "error");
    return;
  }
  if (BUDDYS_BOOTSTRAP.inviteRequired && !payload.invite_code) {
    setAuthStatus("注册需填写邀请码。", "error");
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
    setAuthStatus(`已注册并登录：${result.user.email}`, "ok");
    await loadAuthWorkspace();
  } catch (error) {
    setAuthStatus(`注册失败：${error.message}`, "error");
  }
}

async function loginAuth() {
  const payload = authPayload();
  if (!payload.email || !payload.password) {
    setAuthStatus("登录需填写邮箱和密码。", "error");
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
    setAuthStatus(`已登录：${result.user.email}`, "ok");
    await loadAuthWorkspace();
  } catch (error) {
    setAuthStatus(`登录失败：${error.message}`, "error");
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
      ? "已登出：当前为邀请码注册模式。"
      : "已登出：登录后可使用状态记忆。",
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
    setAuthStatus("请先登录后再创建 Buddy。", "error");
    return;
  }
  try {
    const buddy = await requestJson("/me/buddies", {
      method: "POST",
      body: JSON.stringify({ name: "My Buddy", space_id: "home" }),
    });
    state.workspace.buddyId = buddy.buddy_id;
    setAuthStatus(`已为 ${state.auth.user.email} 创建 Buddy。`, "ok");
    await loadAuthWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setAuthStatus(`创建 Buddy 失败：${error.message}`, "error");
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
    $("deviceWorkspaceStatus").textContent = "当前未配对设备。";
    return;
  }
  const instruction = $("deviceOwnerInstructionInput").value.trim();
  if (!instruction) {
    $("deviceWorkspaceStatus").textContent = "请先填写手动提醒内容。";
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
    $("deviceWorkspaceStatus").textContent = `已发布目标状态，版本 ${response.desired_state.revision}。`;
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    $("deviceWorkspaceStatus").textContent = `发布失败：${error.message}`;
  }
}

async function submitCapture() {
  if (!state.workspace.buddyId) {
    setWorkspaceStatus("请先创建或选择一个 Buddy 再提交捕获。");
    return;
  }
  const content = $("captureTextInput").value.trim();
  if (!content) {
    setWorkspaceStatus("请输入本次记录内容。");
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
    setWorkspaceStatus(`已保存为待审批提案：${response.proposal.content}`);
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setWorkspaceStatus(`记录保存失败：${error.message}`);
  }
}

async function submitPhotoCapture() {
  if (!state.workspace.buddyId || !state.ui.photo.base64 || !state.ui.photo.mediaType) {
    setWorkspaceStatus("请先选择一张图片，再保存照片记录。");
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
    setWorkspaceStatus(`图片记录已保存为待审批提案：${response.proposal.content}`);
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setWorkspaceStatus(`照片记录失败：${error.message}`);
  }
}

async function submitVoiceTranscript() {
  if (!state.workspace.buddyId) {
    setWorkspaceStatus("请先创建或选择一个 Buddy 再保存语音文本。");
    return;
  }
  const transcript = $("voiceTranscriptInput").value.trim();
  if (!transcript) {
    setWorkspaceStatus("语音转写内容为空。");
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
    setWorkspaceStatus(`语音转写已保存为待审批记录：${response.proposal.content}`);
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setWorkspaceStatus(`转写保存失败：${error.message}`);
  }
}

async function submitQuery() {
  if (!state.workspace.buddyId) {
    setWorkspaceStatus("请先创建或选择一个 Buddy 再查询状态。");
    return;
  }
  const question = $("queryTextInput").value.trim();
  if (!question) {
    setWorkspaceStatus("请输入提问内容。");
    return;
  }
  try {
    const answer = await requestJson(`/me/buddies/${state.workspace.buddyId}/state-memory/query`, {
      method: "POST",
      body: JSON.stringify({ question }),
    });
    $("queryTextInput").value = "";
    setWorkspaceStatus(`已查询：${answer.summary}`);
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setWorkspaceStatus(`查询失败：${error.message}`);
  }
}

async function submitRecipe() {
  if (!state.workspace.buddyId) {
    setWorkspaceStatus("请先创建或选择一个 Buddy 再保存食谱。");
    return;
  }
  const name = $("recipeNameInput").value.trim();
  const ingredients = $("recipeIngredientsInput").value
    .split(/[，,]/)
    .map((value) => value.trim())
    .filter(Boolean);
  if (!name || !ingredients.length) {
    setWorkspaceStatus("请填写食谱名称与食材。");
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
    setWorkspaceStatus(`食谱已保存：${formatRecipe(response.recipe)}`);
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setWorkspaceStatus(`保存食谱失败：${error.message}`);
  }
}

async function deleteRecipe(recipeId) {
  try {
    await requestJson(`/me/buddies/${state.workspace.buddyId}/state-memory/recipes/${recipeId}`, {
      method: "DELETE",
    });
    setWorkspaceStatus("食谱已删除。");
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setWorkspaceStatus(`删除食谱失败：${error.message}`);
  }
}

async function addShoppingPassItem() {
  if (!state.workspace.buddyId) {
    setWorkspaceStatus("请先创建或选择一个 Buddy，再添加购物清单条目。");
    return;
  }
  const name = $("shoppingPassNameInput").value.trim();
  if (!name) {
    setWorkspaceStatus("购物清单条目名称不能为空。");
    syncAuthControls();
    return;
  }
  try {
    const response = await requestJson(`/me/buddies/${state.workspace.buddyId}/state-memory/shopping-pass/items`, {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    $("shoppingPassNameInput").value = "";
    setWorkspaceStatus(`购物清单条目已添加：${response.item.name}`);
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setWorkspaceStatus(`添加购物清单条目失败：${error.message}`);
  }
}

async function promoteShoppingPassHint() {
  if (!state.workspace.buddyId) {
    setWorkspaceStatus("请先创建或选择一个 Buddy，再从提示补齐购物清单。");
    return;
  }
  try {
    const response = await requestJson(`/me/buddies/${state.workspace.buddyId}/state-memory/shopping-pass/promote-hint`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    setWorkspaceStatus(`已按提示补齐：${response.item.name}`);
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setWorkspaceStatus(`提示补齐购物清单失败：${error.message}`);
  }
}

async function promoteShoppingPassLatestQuery() {
  if (!state.workspace.buddyId) {
    setWorkspaceStatus("请先创建或选择一个 Buddy，再根据最近提问补齐清单。");
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
        ? `已根据最近提问补齐：${itemNames.join(" / ")}`
        : "已根据最近提问补齐购物清单。",
    );
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setWorkspaceStatus(`最近提问补齐失败：${error.message}`);
  }
}

async function markShoppingPassItemDone(shoppingItemId) {
  if (!state.workspace.buddyId) {
    setWorkspaceStatus("请先创建或选择一个 Buddy，再完成清单条目。");
    return;
  }
  try {
    const response = await requestJson(`/me/buddies/${state.workspace.buddyId}/state-memory/shopping-pass/items/${shoppingItemId}/done`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    setWorkspaceStatus(`条目完成：${response.item.name}`);
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setWorkspaceStatus(`购物清单条目完成失败：${error.message}`);
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
    setWorkspaceStatus("提案已确认。");
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setWorkspaceStatus(`确认失败：${error.message}`);
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
    setWorkspaceStatus("提案已拒绝。");
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setWorkspaceStatus(`拒绝失败：${error.message}`);
  }
}

async function submitCorrection() {
  const proposal = selectedProposal();
  if (!state.workspace.buddyId || !proposal) {
    setWorkspaceStatus("请先选择待处理提案后再提交纠正。");
    return;
  }
  let deltas;
  try {
    deltas = JSON.parse($("proposalCorrectionInput").value);
  } catch (error) {
    setWorkspaceStatus("纠正 JSON 格式无效。");
    return;
  }
  try {
    await requestJson(`/me/buddies/${state.workspace.buddyId}/state-memory/proposals/${proposal.proposal_id}/correct`, {
      method: "POST",
      body: JSON.stringify({ deltas }),
    });
    state.ui.selectedProposalId = null;
    $("proposalCorrectionInput").value = "";
    setWorkspaceStatus("纠正已应用。");
    await refreshWorkspace();
  } catch (error) {
    if (isRecoveredSessionExpiry(error)) {
      return;
    }
    setWorkspaceStatus(`纠正失败：${error.message}`);
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
    loadSyncSnapshot().catch((error) => setWorkspaceStatus(`Buddy 切换失败：${error.message}`));
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
