import json
import re
import subprocess

from fastapi.testclient import TestClient

from buddys_api.main import create_app


def make_client() -> TestClient:
    return TestClient(create_app())


def extract_function_body(script: str, function_name: str) -> str:
    match = re.search(rf"function {function_name}\([^)]*\) \{{(?P<body>.*?)\n\}}", script, re.S)
    assert match is not None
    return match.group("body")


def run_node(script: str) -> str:
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def test_console_route_serves_html() -> None:
    client = make_client()

    response = client.get("/console")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>Buddys Console</title>" in response.text


def test_static_assets_are_served() -> None:
    client = make_client()

    css_response = client.get("/static/styles.css")
    js_response = client.get("/static/app.js")
    raw_index_response = client.get("/static/index.html")

    assert css_response.status_code == 200
    assert css_response.headers["content-type"].startswith("text/css")
    assert "--accent-orange" in css_response.text

    assert js_response.status_code == 200
    assert "renderExperienceShell" in js_response.text
    assert raw_index_response.status_code == 404


def test_favicon_does_not_create_browser_console_404() -> None:
    client = make_client()

    response = client.get("/favicon.ico")

    assert response.status_code == 204


def test_console_html_exposes_single_primary_state_memory_workspace() -> None:
    client = make_client()

    html = client.get("/console").text

    assert 'id="experienceShell"' in html
    assert 'id="authRail"' in html
    assert 'id="buddyHero"' in html
    assert 'id="confirmedStatePanel"' in html
    assert 'id="captureComposer"' in html
    assert 'id="proposalInbox"' in html
    assert 'id="queryComposer"' in html
    assert 'id="latestAnswerPanel"' in html
    assert 'id="proactiveMemoryCard"' in html
    assert 'id="dismissProactiveHintButton"' in html
    assert 'id="detailsDrawer"' in html
    assert 'id="answerBasisPanel"' in html
    assert 'data-surface="browser-console"' not in html
    assert 'data-surface="mobile-app"' not in html
    assert 'data-surface="hardware-display"' not in html
    assert "Create demo Buddy" not in html


def test_console_html_exposes_real_photo_input_and_honest_voice_surface() -> None:
    client = make_client()

    html = client.get("/console").text

    assert 'id="captureTextInput"' in html
    assert 'id="captureSubmitButton"' in html
    assert 'id="photoFileInput"' in html
    assert 'id="photoPreviewImage"' in html
    assert 'id="submitPhotoCaptureButton"' in html
    assert 'id="startVoiceCaptureButton"' in html
    assert 'id="voiceTranscriptInput"' in html
    assert 'id="submitVoiceTranscriptButton"' in html
    assert "Photo capture coming soon" not in html


def test_console_html_contains_auth_workspace_and_state_memory_controls() -> None:
    client = make_client()

    html = client.get("/console").text

    assert 'id="authStatus"' in html
    assert 'id="authEmailInput"' in html
    assert 'id="authPasswordInput"' in html
    assert 'id="authDisplayNameInput"' in html
    assert 'id="authInviteCodeInput"' in html
    assert 'id="authRegisterButton"' in html
    assert 'id="authLoginButton"' in html
    assert 'id="authLogoutButton"' in html
    assert 'id="authBuddySelect"' in html
    assert 'id="createMyBuddyButton"' in html
    assert 'id="captureTextInput"' in html
    assert 'id="captureSubmitButton"' in html
    assert 'id="queryTextInput"' in html
    assert 'id="querySubmitButton"' in html
    assert 'id="proposalReviewList"' in html
    assert 'id="proposalCorrectionInput"' in html
    assert 'id="submitCorrectionButton"' in html
    assert 'id="recipeShelfPanel"' in html
    assert 'id="recipeList"' in html
    assert 'id="recipeNameInput"' in html
    assert 'id="recipeIngredientsInput"' in html
    assert 'id="createRecipeButton"' in html
    assert "Why this answer / details" in html


def test_console_html_exposes_user_transparency_surfaces_without_operator_panels() -> None:
    client = make_client()

    html = client.get("/console").text

    assert 'id="buddyTransparencyPanel"' in html
    assert 'id="buddyTransparencyTitle"' in html
    assert 'id="buddyActivityPanel"' in html
    assert 'id="buddyActivityTitle"' in html
    assert 'id="buddyActivityList"' in html
    assert 'id="buddyThinkingPanel"' in html
    assert 'id="buddyThinkingTitle"' in html
    assert 'id="answerBasisPanel"' in html
    assert "See what Buddy remembers, what it just did, and why it answered that way." in html
    assert "What Buddy just did" in html
    assert "Why Buddy thinks that" in html
    assert 'id="agentManagementPanel"' in html
    assert 'id="agentManagementTitle"' in html
    assert 'id="agentManagementStatus"' in html
    assert 'id="agentManagementList"' in html
    assert 'id="agentManagementNameInput"' in html
    assert 'id="agentManagementRoleSelect"' in html
    assert 'id="createAgentButton"' in html
    assert 'id="agentManagementActionStatus"' in html
    assert "Register agent" in html
    assert "Agent and machine workspace" in html
    assert 'id="costGovernancePanel"' in html
    assert 'id="costGovernanceTitle"' in html
    assert 'id="costGovernanceStatus"' in html
    assert 'id="planUsageList"' in html
    assert 'id="planUsageBreakdownList"' in html
    assert 'id="planGovernanceCostRow"' in html
    assert "Provider settings" not in html
    assert "Model usage detail" not in html


def test_console_html_exposes_founder_metrics_containers() -> None:
    client = make_client()

    html = client.get("/console").text

    assert 'id="founderMetricsPanel"' in html
    assert 'id="founderActivationPanel"' in html
    assert 'id="founderRetentionPanel"' in html
    assert 'id="founderCaptureMixPanel"' in html


def test_console_html_exposes_device_workspace_and_owner_action_controls() -> None:
    client = make_client()

    html = client.get("/console").text

    assert 'id="deviceWorkspacePanel"' in html
    assert 'id="deviceIdentityPanel"' in html
    assert 'id="deviceHealthPanel"' in html
    assert 'id="deviceDesiredStatePanel"' in html
    assert 'id="deviceEventPanel"' in html
    assert 'id="deviceBindingPanel"' in html
    assert 'id="deviceOwnerInstructionInput"' in html
    assert 'id="publishDeviceDesiredStateButton"' in html


def test_console_assets_drive_primary_state_memory_flow_and_details_drawer() -> None:
    client = make_client()

    script = client.get("/static/app.js").text

    assert "renderExperienceShell" in script
    assert "renderCaptureComposer" in script
    assert "renderProposalInbox" in script
    assert "renderLatestAnswer" in script
    assert "renderProactiveMemoryCard" in script
    assert "toggleDetailsDrawer" in script
    assert "runBuddysDemo" not in script
    assert "createBuddyButton" not in script
    assert "captureSourceSelect" not in script
    assert "captureContentInput" not in script
    assert "startVoiceCapture" in script
    assert "handlePhotoSelected" in script
    assert "submitPhotoCapture" in script
    assert "submitVoiceTranscript" in script
    assert "renderRecipeShelf" in script
    assert "submitRecipe" in script
    assert "deleteRecipe" in script


def test_console_assets_project_workspace_maps_recipe_shelf_snapshot_and_reset_state() -> None:
    client = make_client()

    script = client.get("/static/app.js").text
    project_workspace_body = extract_function_body(script, "projectWorkspace")
    clear_session_body = extract_function_body(script, "clearSession")
    render_recipe_shelf_body = extract_function_body(script, "renderRecipeShelf")

    assert "recipes_by_buddy" in project_workspace_body
    assert 'state.workspace.recipes = buddyId ? stateMemory.recipes_by_buddy?.[buddyId] || [] : [];' in project_workspace_body
    assert "state.workspace.recipes = [];" in clear_session_body
    assert "state.workspace.recipes.length" in render_recipe_shelf_body
    assert "recipeShelfStatus" in render_recipe_shelf_body
    assert "deleteRecipe(recipe.recipe_id)" in render_recipe_shelf_body


def test_console_assets_project_safe_recent_activity_for_transparency_view() -> None:
    client = make_client()

    script = client.get("/static/app.js").text
    html = client.get("/console").text
    project_workspace_body = extract_function_body(script, "projectWorkspace")
    clear_session_body = extract_function_body(script, "clearSession")
    render_recent_activity_body = extract_function_body(script, "renderRecentActivity")
    format_recent_activity_body = extract_function_body(script, "formatRecentActivity")

    assert "renderRecentActivity" in script
    assert "recent_activity_by_buddy" in project_workspace_body
    assert 'state.workspace.recentActivity = buddyId ? stateMemory.recent_activity_by_buddy?.[buddyId] || [] : [];' in project_workspace_body
    assert 'state.workspace.recentActivity = [];' in clear_session_body
    assert ".slice().reverse()" in render_recent_activity_body
    assert "activity.summary" in format_recent_activity_body
    assert "Saved " not in format_recent_activity_body
    assert "Waiting for review:" not in format_recent_activity_body
    assert "Answered:" not in format_recent_activity_body
    assert "api_key" not in script
    assert "renderAgentManagement" in script
    assert "snapshot.agents" in project_workspace_body
    assert "state.workspace.agents = snapshot.agents || [];" in project_workspace_body
    assert "snapshot.agent_machines" in project_workspace_body
    assert "state.workspace.agentMachines = agentMachines;" in project_workspace_body
    assert "providerSettingsPanel" not in script
    assert "renderCostGovernancePanel" in script
    assert "costGovernancePanel" in html


def test_console_assets_project_workspace_maps_agents_and_renders_agent_management_panel() -> None:
    client = make_client()

    html = client.get("/console").text
    script = client.get("/static/app.js").text
    project_workspace_body = extract_function_body(script, "projectWorkspace")
    render_agent_management_body = extract_function_body(script, "renderAgentManagement")

    assert 'id="agentManagementPanel"' in html
    assert 'id="agentManagementList"' in html
    assert "snapshot.agents" in project_workspace_body
    assert "state.workspace.agents = snapshot.agents || [];" in project_workspace_body
    assert "snapshot.agent_machines" in project_workspace_body
    assert "state.workspace.agentMachines = agentMachines;" in project_workspace_body
    assert "renderAgentManagement" in script
    assert "agentManagementStatus" in render_agent_management_body
    assert "state.workspace.agents.length" in render_agent_management_body
    assert "state.workspace.agentMachines.length" in render_agent_management_body
    assert "agentManagementActionStatus" in render_agent_management_body


def test_console_assets_agent_creation_path_is_declared_in_console_js() -> None:
    client = make_client()

    script = client.get("/static/app.js").text
    render_agent_management_body = extract_function_body(script, "renderAgentManagement")
    create_agent_body = extract_function_body(script, "createAgent")

    assert "agentManagementNameInput" in script
    assert "agentManagementRoleSelect" in script
    assert "/agents" in create_agent_body
    assert "method: \"POST\"" in create_agent_body
    assert "refreshWorkspace()" in create_agent_body
    assert "createAgentButton" in render_agent_management_body
    assert "agentManagementNameInput" in render_agent_management_body
    assert "agentManagementActionStatus" in render_agent_management_body
    assert "Registered ${agentName}" in create_agent_body
    

def test_console_assets_agent_heartbeat_controls_declared_in_console_js() -> None:
    client = make_client()

    script = client.get("/static/app.js").text
    render_agent_management_body = extract_function_body(script, "renderAgentManagement")
    send_agent_heartbeat_body = extract_function_body(script, "sendAgentHeartbeat")

    assert "HEARTBEAT_REQUESTS_IN_FLIGHT" in script
    assert "agentHeartbeatStatus" in render_agent_management_body
    assert "agentHeartbeatVersion" in render_agent_management_body
    assert "agentHeartbeatSend" in render_agent_management_body
    assert "Send heartbeat" in render_agent_management_body
    assert "Sending heartbeat..." in render_agent_management_body
    assert "AGENT_STATUSES" in render_agent_management_body
    assert "heartbeatStatus.disabled = isHeartbeatInFlight;" in render_agent_management_body
    assert "heartbeatVersion.disabled = isHeartbeatInFlight;" in render_agent_management_body
    assert "/heartbeat" in send_agent_heartbeat_body
    assert "requestJson(`/agents/${agentId}/heartbeat`" in send_agent_heartbeat_body
    assert "statusSelect" in send_agent_heartbeat_body
    assert "statusValue" in send_agent_heartbeat_body
    assert "HEARTBEAT_REQUESTS_IN_FLIGHT.has(agentId)" in send_agent_heartbeat_body
    assert "HEARTBEAT_REQUESTS_IN_FLIGHT.add(agentId)" in send_agent_heartbeat_body
    assert "HEARTBEAT_REQUESTS_IN_FLIGHT.delete(agentId)" in send_agent_heartbeat_body
    assert "parseAgentHeartbeatVersion" in script


def test_console_assets_render_latest_answer_as_user_altitude_transparency_copy() -> None:
    client = make_client()

    script = client.get("/static/app.js").text
    render_latest_answer_body = extract_function_body(script, "renderLatestAnswer")

    assert "Buddy answered using saved evidence." in render_latest_answer_body
    assert "evidence ready" not in render_latest_answer_body


def test_console_assets_support_session_aware_auth_and_state_memory_client_flow() -> None:
    client = make_client()

    script = client.get("/static/app.js").text
    request_json_body = extract_function_body(script, "requestJson")
    register_auth_body = extract_function_body(script, "registerAuth")

    assert "localStorage" in script
    assert "buddysAccessToken" in script
    assert "Authorization" in script
    assert "/auth/register" in script
    assert "invite_code" in script
    assert "window.BUDDYS_BOOTSTRAP" in script
    assert "/auth/login" in script
    assert "/auth/me" in script
    assert "/auth/logout" in script
    assert "/me/buddies" in script
    assert "/metrics/engagement" in script
    assert "/metrics/retention-summary" in script
    assert "/sync/snapshot" in script
    assert "/state-memory/captures/conversation" in script
    assert "/state-memory/query" in script
    assert "/state-memory/proposals/" in script
    assert "proposalReviewList" in script
    assert "proposalCorrectionInput" in script
    assert "detailCode || payload?.detail" in request_json_body
    assert 'saveSession(result.access_token, result.user);' in register_auth_body
    assert 'setAuthStatus(`Signed in as ${result.user.email}`, "ok");' in register_auth_body
    assert "Registered ${result.user.email}" not in register_auth_body


def test_console_assets_manage_founder_metrics_state_and_hide_panel_for_non_founders() -> None:
    client = make_client()

    script = client.get("/static/app.js").text
    clear_session_body = extract_function_body(script, "clearSession")
    load_founder_metrics_body = extract_function_body(script, "loadFounderMetrics")
    render_founder_metrics_body = extract_function_body(script, "renderFounderMetrics")

    assert "engagementMetrics:" in script
    assert "retentionSummary:" in script
    assert "founderMetricsVisible:" in script
    assert "founderMetricsUnavailableReason:" in script
    assert "state.workspace.engagementMetrics = null;" in clear_session_body
    assert "state.workspace.retentionSummary = null;" in clear_session_body
    assert "state.workspace.founderMetricsVisible = false;" in clear_session_body
    assert "state.workspace.founderMetricsUnavailableReason = null;" in clear_session_body
    assert 'detailCode === "founder_metrics_forbidden"' in load_founder_metrics_body
    assert "state.workspace.founderMetricsVisible = false;" in load_founder_metrics_body
    assert "state.workspace.founderMetricsUnavailableReason" in load_founder_metrics_body
    assert "const requestGeneration = ++state.ui.founderMetricsRequestGeneration;" in load_founder_metrics_body
    assert "const requestSessionToken = state.auth.accessToken;" in load_founder_metrics_body
    assert "requestGeneration !== state.ui.founderMetricsRequestGeneration" in load_founder_metrics_body
    assert "requestSessionToken !== state.auth.accessToken" in load_founder_metrics_body
    assert "$(\"founderMetricsPanel\").hidden" in render_founder_metrics_body


def test_console_assets_project_and_publish_device_workspace_from_auth_snapshot() -> None:
    client = make_client()

    script = client.get("/static/app.js").text
    project_workspace_body = extract_function_body(script, "projectWorkspace")
    render_device_workspace_body = extract_function_body(script, "renderDeviceWorkspace")
    publish_device_desired_state_body = extract_function_body(script, "publishDeviceDesiredState")

    assert "deviceReminderDraftsByBuddy" in script
    assert "device:" in script
    assert "agentMachine:" in script
    assert "binding:" in script
    assert "latestHeartbeat:" in script
    assert "desiredState:" in script
    assert "deviceEvents:" in script
    assert "snapshot.devices" in project_workspace_body
    assert "snapshot.agent_machines" in project_workspace_body
    assert "snapshot.bindings" in project_workspace_body
    assert "snapshot.latest_heartbeats" in project_workspace_body
    assert "snapshot.desired_states" in project_workspace_body
    assert "snapshot.device_events" in project_workspace_body
    assert "No paired device yet." in render_device_workspace_body
    assert "deviceReminderDraftsByBuddy[state.workspace.buddyId]" in render_device_workspace_body
    assert "publishDeviceDesiredState" in script
    assert "/me/buddies/" in publish_device_desired_state_body
    assert "/desired-state" in publish_device_desired_state_body
    assert "deviceOwnerInstructionInput" in publish_device_desired_state_body
    assert "reminder_text" in publish_device_desired_state_body
    assert "state_memory" not in publish_device_desired_state_body
    assert "proactive_hint" not in publish_device_desired_state_body
    assert "recent_activity" not in publish_device_desired_state_body
    assert "source_trace_id" not in publish_device_desired_state_body
    assert '"state"' not in publish_device_desired_state_body
    assert '"manual_required"' not in publish_device_desired_state_body


def test_console_assets_refresh_workspace_without_waiting_for_founder_metrics() -> None:
    client = make_client()

    script = client.get("/static/app.js").text
    refresh_workspace_body = extract_function_body(script, "refreshWorkspace")

    assert "await loadSyncSnapshot();" in refresh_workspace_body
    assert "loadFounderMetrics().catch(() => {});" in refresh_workspace_body
    assert "await loadFounderMetrics();" not in refresh_workspace_body


def test_console_assets_clear_session_invalidates_inflight_founder_metrics_refresh() -> None:
    client = make_client()

    script = client.get("/static/app.js").text
    clear_session_body = extract_function_body(script, "clearSession")

    assert "founderMetricsRequestGeneration:" in script
    assert "state.ui.founderMetricsRequestGeneration += 1;" in clear_session_body


def test_console_assets_render_founder_metric_card_preserves_heading_ids_after_runtime_render() -> None:
    client = make_client()

    script = client.get("/static/app.js").text
    render_founder_metric_card_body = extract_function_body(script, "renderFounderMetricCard")
    node_output = run_node(
        f"""
        class Element {{
          constructor(tagName, id = "", className = "") {{
            this.tagName = tagName.toLowerCase();
            this.id = id;
            this.className = className;
            this.children = [];
            this.parentNode = null;
            this.textContent = "";
          }}
          appendChild(child) {{
            child.parentNode = this;
            this.children.push(child);
            return child;
          }}
          removeChild(child) {{
            this.children = this.children.filter((entry) => entry !== child);
            child.parentNode = null;
          }}
          querySelector(selector) {{
            if (selector === "h3") {{
              return this.children.find((child) => child.tagName === "h3") || null;
            }}
            if (selector === ".eyebrow") {{
              return this.children.find((child) => child.className === "eyebrow") || null;
            }}
            return null;
          }}
        }}
        const card = new Element("section", "founderActivationPanel");
        const eyebrow = card.appendChild(new Element("p", "", "eyebrow"));
        eyebrow.textContent = "Activation";
        const heading = card.appendChild(new Element("h3", "founderActivationTitle"));
        heading.textContent = "My activation";
        const stale = card.appendChild(new Element("p", "", "support-copy"));
        stale.textContent = "stale";
        const document = {{
          getElementById(id) {{
            return id === "founderActivationPanel" ? card : null;
          }},
          createElement(tagName) {{
            return new Element(tagName);
          }},
        }};
        const $ = (id) => document.getElementById(id);
        function renderFounderMetricCard(targetId, title, rows) {{{render_founder_metric_card_body}}}
        renderFounderMetricCard("founderActivationPanel", "My activation", ["Tracked events: 3"]);
        console.log(JSON.stringify({{
          headingId: card.children[1].id,
          headingText: card.children[1].textContent,
          childTags: card.children.map((child) => child.tagName),
          lastText: card.children[2].textContent,
        }}));
        """
    )

    rendered = json.loads(node_output)
    assert rendered["headingId"] == "founderActivationTitle"
    assert rendered["headingText"] == "My activation"
    assert rendered["childTags"] == ["p", "h3", "p"]
    assert rendered["lastText"] == "Tracked events: 3"


def test_console_assets_show_unavailable_state_for_founder_metrics_failures_without_breaking_workspace() -> None:
    client = make_client()

    script = client.get("/static/app.js").text
    load_founder_metrics_body = extract_function_body(script, "loadFounderMetrics")
    render_founder_metrics_body = extract_function_body(script, "renderFounderMetrics")

    assert "Founder metrics unavailable" in render_founder_metrics_body
    assert "setWorkspaceStatus" not in load_founder_metrics_body
    assert "await loadSyncSnapshot();" not in load_founder_metrics_body


def test_console_assets_clear_stale_session_when_protected_api_returns_invalid_or_expired_token() -> None:
    client = make_client()

    script = client.get("/static/app.js").text
    request_json_body = extract_function_body(script, "requestJson")
    recover_expired_session_body = extract_function_body(script, "recoverExpiredSession")

    assert 'response.status === 401' in request_json_body
    assert 'detailCode === "invalid_or_expired_token"' in request_json_body
    assert "await recoverExpiredSession();" in request_json_body
    assert "clearSession();" in recover_expired_session_body
    assert 'setAuthStatus("Stored session expired. Please login again.", "error");' in recover_expired_session_body
    assert "await loadSyncSnapshot();" in recover_expired_session_body


def test_console_route_bootstraps_invite_required_flag_from_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BUDDYS_INVITE_CODE", "letmein")
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))

    html = client.get("/console").text

    assert '"inviteRequired": true' in html


def test_console_assets_reset_auth_and_workspace_copy_honestly() -> None:
    client = make_client()

    script = client.get("/static/app.js").text
    clear_session_body = extract_function_body(script, "clearSession")

    assert "SpeechRecognition" in script
    assert "webkitSpeechRecognition" in script
    assert "Voice capture is not available in this browser." in script
    assert "I heard this but could not structure it yet" in script
    assert "No confirmed state yet." in script
    assert "No state-memory query yet." in script
    assert "proactiveHint: null" in script
    assert "founderMetricsVisible: false" in script
    assert "state.workspace.confirmedItems = [];" in clear_session_body
    assert "state.workspace.pendingProposals = [];" in clear_session_body
    assert "state.workspace.latestQuery = null;" in clear_session_body
    assert "state.workspace.proactiveHint = null;" in clear_session_body


def test_console_assets_surface_unrecognized_and_traceable_proactive_copy() -> None:
    client = make_client()

    script = client.get("/static/app.js").text

    assert "renderUnrecognizedList" in script
    assert "proposal.unrecognized" in script
    assert "I heard this but could not structure it yet" in script
    assert "Buddy noticed" in script
    assert "Based on" in script
    assert "dismissProactiveHint" in script
    assert "state.ui.dismissedHintKey = hint.hintKey;" in script


def test_console_assets_render_unknown_quantity_copy_not_dash_placeholder() -> None:
    client = make_client()

    script = client.get("/static/app.js").text
    format_quantity_body = extract_function_body(script, "formatQuantity")
    proposal_delta_copy_body = extract_function_body(script, "proposalDeltaCopy")

    assert "数量未输入" in format_quantity_body
    assert "数量未输入" in proposal_delta_copy_body
    assert "amount unknown" not in script
    assert 'return unit || "-"' not in format_quantity_body
    assert 'return "-"' not in format_quantity_body


def test_console_uses_sync_snapshot_as_shared_state_source_without_inner_html_injection() -> None:
    client = make_client()

    script = client.get("/static/app.js").text

    assert "/sync/snapshot" in script
    assert "loadSyncSnapshot" in script
    assert "innerHTML" not in script
    assert "createElement(\"li\")" in script


def test_console_assets_keep_signed_out_workspace_auth_only_when_sync_snapshot_contains_legacy_data() -> None:
    client = make_client()

    script = client.get("/static/app.js").text
    project_workspace_body = extract_function_body(script, "projectWorkspace")

    assert "if (!isAuthenticated())" in project_workspace_body
    assert "state.workspace.buddies = [];" in project_workspace_body
    assert "state.workspace.buddyId = null;" in project_workspace_body
    assert "state.workspace.confirmedItems = [];" in project_workspace_body
    assert "state.workspace.pendingProposals = [];" in project_workspace_body
    assert "state.workspace.latestQuery = null;" in project_workspace_body
    assert "state.workspace.recentActivity = [];" in project_workspace_body
    assert "state.workspace.traces = [];" in project_workspace_body
    assert "state.workspace.costSummary = {};" in project_workspace_body
    assert "state.workspace.planUsage = {};" in project_workspace_body


def test_console_assets_project_workspace_maps_plan_usage_and_renders_cost_panel() -> None:
    client = make_client()

    script = client.get("/static/app.js").text
    html = client.get("/console").text
    project_workspace_body = extract_function_body(script, "projectWorkspace")
    render_cost_governance_body = extract_function_body(script, "renderCostGovernancePanel")

    assert 'id="costGovernancePanel"' in html
    assert 'id="costGovernanceStatus"' in html
    assert 'id="planUsageList"' in html
    assert "snapshot.plan_usage" in project_workspace_body
    assert "state.workspace.planUsage = snapshot.plan_usage || {};" in project_workspace_body
    assert "renderCostGovernancePanel" in script
    assert "renderTextList(\"planUsageList\"" in render_cost_governance_body
    assert "costGovernanceStatus" in render_cost_governance_body


def test_console_assets_render_evidence_and_details_basis_for_current_answer() -> None:
    client = make_client()

    html = client.get("/console").text
    script = client.get("/static/app.js").text
    render_details_drawer_body = extract_function_body(script, "renderDetailsDrawer")

    assert 'id="answerBasisTitle"' in html
    assert 'id="answerBasisQuestion"' in html
    assert 'id="answerBasisSummary"' in html
    assert 'id="answerBasisEvidenceList"' in html
    assert 'id="buddyActivityList"' in html
    assert "renderAnswerBasisPanel" in script
    assert "renderRecentActivity" in script
    assert "item.source" in script
    assert "item.last_seen_at" in script
    assert "latestQuery.answer_type" in script
    assert "traceTimeline" not in script
    assert "runtimeHealth" not in script
    assert "tokenUsage" not in script
    assert "modelCost" not in script
    assert "monthCost" not in script
    assert "renderAnswerBasisPanel();" in render_details_drawer_body


def test_console_styles_define_single_column_mobile_first_experience_shell() -> None:
    client = make_client()

    css = client.get("/static/styles.css").text

    assert "#experienceShell" in css
    assert "max-width: 480px" in css
    assert "position: sticky" in css
    assert ".details-drawer" in css
    assert ".coming-soon-chip" in css


def test_console_styles_remove_hardware_square_and_legacy_tri_surface_constraints() -> None:
    client = make_client()

    css = client.get("/static/styles.css").text
    html = client.get("/console").text

    assert "width: 240px;" not in css
    assert "height: 240px;" not in css
    assert ".layout" not in css
    assert 'data-surface="hardware-display"' not in html
