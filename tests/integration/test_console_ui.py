import re

from fastapi.testclient import TestClient

from buddys_api.main import create_app


def make_client() -> TestClient:
    return TestClient(create_app())


def extract_function_body(script: str, function_name: str) -> str:
    match = re.search(rf"function {function_name}\([^)]*\) \{{(?P<body>.*?)\n\}}", script, re.S)
    assert match is not None
    return match.group("body")


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

    assert css_response.status_code == 200
    assert css_response.headers["content-type"].startswith("text/css")
    assert "--accent-orange" in css_response.text

    assert js_response.status_code == 200
    assert "runBuddysDemo" in js_response.text


def test_favicon_does_not_create_browser_console_404() -> None:
    client = make_client()

    response = client.get("/favicon.ico")

    assert response.status_code == 204


def test_console_html_contains_tri_surface_landmarks() -> None:
    client = make_client()

    response = client.get("/console")

    assert 'data-surface="browser-console"' in response.text
    assert 'data-surface="mobile-app"' in response.text
    assert 'data-surface="hardware-display"' in response.text
    assert "Action Trace" in response.text
    assert "Manual fallback" in response.text


def test_mobile_surface_prioritizes_confirmation_before_trace_and_cost() -> None:
    client = make_client()

    response = client.get("/console")
    html = response.text

    mobile_position = html.index('data-surface="mobile-app"')
    trace_position = html.index('id="traceTitle"')
    cost_position = html.index('id="costTitle"')

    assert mobile_position < trace_position
    assert mobile_position < cost_position
    assert 'id="mobileProposal"' in html
    assert 'id="mobileManualInstruction"' in html
    assert 'id="mobileApproveButton"' in html


def test_hardware_display_uses_240_square_logical_size() -> None:
    client = make_client()

    css_response = client.get("/static/styles.css")

    assert "width: 240px;" in css_response.text
    assert "height: 240px;" in css_response.text


def test_console_assets_expose_manual_required_as_first_class_state() -> None:
    client = make_client()

    html_response = client.get("/console")
    js_response = client.get("/static/app.js")

    assert "user_instruction" in js_response.text
    assert "voice_prompt" in js_response.text
    assert "manual_required" in js_response.text
    assert "No manual fallback needed" in js_response.text
    assert "model_cost_usd" in js_response.text
    assert "estimated_cost_cny" not in js_response.text
    assert "Manual fallback" in html_response.text
    assert 'toolResult.status === "manual_required"' in js_response.text
    assert 'toolResult.status === "success"' in js_response.text
    assert js_response.text.index('toolResult.status === "manual_required"') < js_response.text.index(
        'toolResult.status === "success"'
    )


def test_console_timeline_does_not_render_trace_content_with_inner_html() -> None:
    client = make_client()

    js_response = client.get("/static/app.js")

    assert "traceTimeline" in js_response.text
    assert "innerHTML" not in js_response.text
    assert "createElement(\"li\")" in js_response.text
    assert "textContent = item" in js_response.text


def test_console_uses_sync_snapshot_as_shared_state_source() -> None:
    client = make_client()

    js_response = client.get("/static/app.js")

    assert "/sync/snapshot" in js_response.text
    assert "loadSyncSnapshot" in js_response.text


def test_console_html_contains_separate_state_memory_sections() -> None:
    client = make_client()

    response = client.get("/console")

    assert "State Memory" in response.text
    assert "Confirmed state" in response.text
    assert "Pending proposals" in response.text
    assert "Latest query" in response.text
    assert 'id="stateMemoryConfirmedList"' in response.text
    assert 'id="stateMemoryPendingList"' in response.text
    assert 'id="stateMemoryEvidenceList"' in response.text


def test_console_assets_render_state_memory_from_sync_snapshot_without_html_injection() -> None:
    client = make_client()

    js_response = client.get("/static/app.js")

    assert "renderStateMemory" in js_response.text
    assert "state_memory" in js_response.text
    assert "items_by_buddy" in js_response.text
    assert "pending_proposals_by_buddy" in js_response.text
    assert "latest_query_by_buddy" in js_response.text
    assert "item.name" in js_response.text
    assert "proposal.content" in js_response.text
    assert "renderTextList" in js_response.text


def test_console_html_contains_auth_workspace_and_state_memory_controls() -> None:
    client = make_client()

    response = client.get("/console")

    assert 'id="authStatus"' in response.text
    assert 'id="authEmailInput"' in response.text
    assert 'id="authPasswordInput"' in response.text
    assert 'id="authRegisterButton"' in response.text
    assert 'id="authLoginButton"' in response.text
    assert 'id="authLogoutButton"' in response.text
    assert 'id="authBuddySelect"' in response.text
    assert 'id="createMyBuddyButton"' in response.text
    assert 'id="captureSourceSelect"' in response.text
    assert 'id="captureContentInput"' in response.text
    assert 'id="submitCaptureButton"' in response.text
    assert 'id="queryQuestionInput"' in response.text
    assert 'id="submitQueryButton"' in response.text
    assert 'id="proposalReviewList"' in response.text
    assert 'id="proposalCorrectionInput"' in response.text
    assert 'id="submitCorrectionButton"' in response.text


def test_console_assets_support_session_aware_auth_and_state_memory_client_flow() -> None:
    client = make_client()

    js_response = client.get("/static/app.js")

    assert "localStorage" in js_response.text
    assert "buddysAccessToken" in js_response.text
    assert "Authorization" in js_response.text
    assert "/auth/register" in js_response.text
    assert "/auth/login" in js_response.text
    assert "/auth/me" in js_response.text
    assert "/auth/logout" in js_response.text
    assert "/me/buddies" in js_response.text
    assert "/sync/snapshot" in js_response.text
    assert "/state-memory/captures/" in js_response.text
    assert "/state-memory/query" in js_response.text
    assert "/state-memory/proposals/" in js_response.text
    assert "proposalReviewList" in js_response.text
    assert "proposalCorrectionInput" in js_response.text


def test_console_assets_clear_stale_auth_shell_on_logout_and_session_expiry() -> None:
    client = make_client()

    script = client.get("/static/app.js").text
    clear_session_body = extract_function_body(script, "clearSession")

    assert "function resetBuddyOverview()" in script
    assert '$("overviewTitle").textContent = "Home Buddy";' in script
    assert '$("buddySpace").textContent = "Home";' in script
    assert '$("buddyState").textContent = "idle";' in script
    assert "resetBuddyOverview();" in clear_session_body
    assert "resetLegacyDemoRail();" in clear_session_body
    assert 'setAuthStatus("Stored session expired. Please login again.", "error");\n    await loadSyncSnapshot();' in script


def test_console_assets_reset_legacy_demo_proposal_state_when_auth_session_starts() -> None:
    client = make_client()

    script = client.get("/static/app.js").text
    save_session_body = extract_function_body(script, "saveSession")
    reset_demo_body = extract_function_body(script, "resetLegacyDemoRail")

    assert "resetLegacyDemoRail();" in save_session_body
    assert "state.proposalId = null;" in reset_demo_body
    assert '$("proposalSummary").textContent = "No action proposal yet";' in reset_demo_body
    assert '$("approveButton").disabled = true;' in reset_demo_body
    assert 'setMobileReview("No action proposal yet", "Manual instructions will appear here before trace and cost details.", false);' in reset_demo_body
