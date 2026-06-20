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
    assert "Why this answer / details" in html


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


def test_console_assets_support_session_aware_auth_and_state_memory_client_flow() -> None:
    client = make_client()

    script = client.get("/static/app.js").text
    request_json_body = extract_function_body(script, "requestJson")

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
    assert "/sync/snapshot" in script
    assert "/state-memory/captures/conversation" in script
    assert "/state-memory/query" in script
    assert "/state-memory/proposals/" in script
    assert "proposalReviewList" in script
    assert "proposalCorrectionInput" in script
    assert "detailCode || payload?.detail" in request_json_body


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
    assert "state.workspace.traces = [];" in project_workspace_body
    assert "state.workspace.costSummary = {};" in project_workspace_body


def test_console_assets_render_evidence_and_details_basis_for_current_answer() -> None:
    client = make_client()

    html = client.get("/console").text
    script = client.get("/static/app.js").text

    assert 'id="answerBasisTitle"' in html
    assert 'id="answerBasisQuestion"' in html
    assert 'id="answerBasisSummary"' in html
    assert 'id="answerBasisEvidenceList"' in html
    assert "renderAnswerBasisPanel" in script
    assert "item.source" in script
    assert "item.last_seen_at" in script
    assert "latestQuery.answer_type" in script


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
