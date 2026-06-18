from fastapi.testclient import TestClient

from buddys_api.main import create_app


def make_client() -> TestClient:
    return TestClient(create_app())


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
