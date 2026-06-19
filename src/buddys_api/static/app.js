const state = {
  buddyId: null,
  proposalId: null,
  traceId: null,
  stateRevision: 0,
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

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "content-type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${url}`);
  }
  return response.json();
}

async function createBuddy() {
  const buddy = await requestJson("/buddies", {
    method: "POST",
    body: JSON.stringify({ user_id: "user_1" }),
  });
  state.buddyId = buddy.buddy_id;
  $("overviewTitle").textContent = buddy.name;
  $("buddySpace").textContent = buddy.space_id;
  setDevice("idle", "•_•", "Home Buddy online");
  await loadSyncSnapshot();
  return buddy;
}

async function loadSyncSnapshot() {
  const snapshot = await requestJson("/sync/snapshot");
  state.stateRevision = snapshot.state_revision || 0;

  const buddy = snapshot.buddies && snapshot.buddies[0];
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

  renderStateMemory(snapshot.state_memory || {}, state.buddyId);
}

async function ensureBuddy() {
  if (!state.buddyId) {
    await createBuddy();
  }
}

async function checkHealth() {
  try {
    await requestJson("/healthz");
    $("runtimeHealth").textContent = "runtime ok";
    $("runtimeHealth").classList.add("ok");
  } catch (error) {
    $("runtimeHealth").textContent = "runtime error";
    $("runtimeHealth").classList.add("error");
  }
}

async function runBuddysDemo() {
  await ensureBuddy();
  setDevice("thinking", "•-•", "understanding light request");
  $("assistantMessage").textContent = "Thinking through the safest action...";
  $("runDemoButton").disabled = true;

  const message = await requestJson(`/buddies/${state.buddyId}/messages`, {
    method: "POST",
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
    body: JSON.stringify({ decision: "approved" }),
  });
  const trace = await requestJson(`/traces/${confirmed.trace_id}`);
  const costs = await requestJson("/cost-events");
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
  state.proposalId = null;
  state.traceId = null;
  $("assistantMessage").textContent = "Ready to propose a safe A-level action.";
  $("proposalSummary").textContent = "No action proposal yet";
  $("proposalPolicy").textContent = "requires confirmation";
  $("approveButton").disabled = true;
  $("runDemoButton").disabled = false;
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

window.runBuddysDemo = runBuddysDemo;

document.addEventListener("DOMContentLoaded", () => {
  $("createBuddyButton").addEventListener("click", createBuddy);
  $("runDemoButton").addEventListener("click", runBuddysDemo);
  $("approveButton").addEventListener("click", approveProposal);
  $("mobileApproveButton").addEventListener("click", approveProposal);
  $("resetButton").addEventListener("click", resetDemo);
  checkHealth();
  loadSyncSnapshot().catch(() => {});
});
