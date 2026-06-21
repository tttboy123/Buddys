from __future__ import annotations

from typing import Any

from tools.device_simulator import cli


def test_help_includes_common_simulator_commands() -> None:
    help_text = cli.build_parser().format_help()

    assert "pair" in help_text
    assert "heartbeat" in help_text
    assert "poll" in help_text
    assert "event" in help_text
    assert "http://127.0.0.1:8000" in help_text


def test_pair_command_bootstraps_buddy_then_pairs_device(capsys) -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request(method: str, url: str, payload: dict[str, object] | None = None) -> dict[str, Any]:
        calls.append((method, url, payload))
        if url == "http://runtime.test/root/buddies":
            return {
                "buddy_id": "buddy_demo_001",
                "user_id": "user_demo",
                "name": "Home Buddy",
                "space_id": "home",
            }
        return {"device": {"device_id": "dev_home_001"}, "binding": {"buddy_id": "buddy_demo_001"}}

    exit_code = cli.main(
        [
            "pair",
            "--device-id",
            "dev_home_001",
            "--base-url",
            "http://runtime.test/root/",
            "--user-id",
            "user_demo",
            "--idempotency-key",
            "pair-test-001",
            "--pairing-token",
            "pair-token-test-001",
        ],
        request_json=fake_request,
    )

    assert exit_code == 0
    assert [call[0] for call in calls] == ["POST", "POST"]
    assert [call[1] for call in calls] == [
        "http://runtime.test/root/buddies",
        "http://runtime.test/root/devices/dev_home_001/pair",
    ]
    assert calls[0][2] == {"user_id": "user_demo"}

    pair_payload = calls[1][2]
    assert pair_payload["buddy_id"] == "buddy_demo_001"
    assert pair_payload["space_id"] == "home"
    assert pair_payload["pairing_token"] == "pair-token-test-001"
    assert pair_payload["idempotency_key"] == "pair-test-001"
    assert pair_payload["public_key"] == "sim-device-public-key-placeholder"
    assert pair_payload["agent_machine"]["owner_user_id"] == "user_demo"
    assert pair_payload["agent_machine"]["endpoint"] == "http://127.0.0.1:8000"
    assert pair_payload["agent_machine"]["public_key"] == "sim-agent-machine-public-key-placeholder"

    output = capsys.readouterr().out
    assert '"device_id": "dev_home_001"' in output
    assert '"pairing_token": "pair-token-test-001"' in output


def test_pair_command_surfaces_generated_pairing_token_when_flag_is_omitted(capsys) -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request(method: str, url: str, payload: dict[str, object] | None = None) -> dict[str, Any]:
        calls.append((method, url, payload))
        if url == "http://runtime.test/buddies":
            return {
                "buddy_id": "buddy_demo_001",
                "user_id": "user_demo",
                "name": "Home Buddy",
                "space_id": "home",
            }
        return {"device": {"device_id": "dev_home_001"}, "binding": {"buddy_id": "buddy_demo_001"}}

    exit_code = cli.main(
        [
            "pair",
            "--device-id",
            "dev_home_001",
            "--base-url",
            "http://runtime.test",
            "--user-id",
            "user_demo",
            "--idempotency-key",
            "pair-test-generated-001",
        ],
        request_json=fake_request,
    )

    assert exit_code == 0
    generated_token = calls[1][2]["pairing_token"]
    assert isinstance(generated_token, str)
    assert generated_token.startswith("pair-token-")

    output = capsys.readouterr().out
    assert f'"pairing_token": "{generated_token}"' in output


def test_cli_builds_device_endpoint_urls_without_real_http(capsys) -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    captured_headers: list[dict[str, str] | None] = []

    def fake_request(
        method: str,
        url: str,
        payload: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        calls.append((method, url, payload))
        captured_headers.append(headers)
        if url.endswith("/desired-state"):
            return {
                "device_id": "dev_home_001",
                "state": "manual_required",
                "revision": 3,
                "display_text": "Manual action needed",
                "user_instruction": "Press the physical button after finishing.",
            }
        return {"ok": True}

    assert (
        cli.main(
            [
                "heartbeat",
                "--device-id",
                "dev_home_001",
                "--base-url",
                "http://runtime.test/root/",
                "--idempotency-key",
                "hb-test-001",
                "--pairing-token",
                "pair-token-test-001",
            ],
            request_json=fake_request,
        )
        == 0
    )
    assert (
        cli.main(
            [
                "poll",
                "--device-id",
                "dev_home_001",
                "--base-url",
                "http://runtime.test/root/",
                "--pairing-token",
                "pair-token-test-001",
            ],
            request_json=fake_request,
        )
        == 0
    )
    assert (
        cli.main(
            [
                "event",
                "--device-id",
                "dev_home_001",
                "--base-url",
                "http://runtime.test/root/",
                "--type",
                "manual_done",
                "--idempotency-key",
                "event-test-001",
                "--pairing-token",
                "pair-token-test-001",
            ],
            request_json=fake_request,
        )
        == 0
    )

    assert [call[0] for call in calls] == ["POST", "GET", "POST"]
    assert [call[1] for call in calls] == [
        "http://runtime.test/root/devices/dev_home_001/heartbeat",
        "http://runtime.test/root/devices/dev_home_001/desired-state",
        "http://runtime.test/root/devices/dev_home_001/events",
    ]
    assert calls[0][2]["current_state"] == "idle"
    assert calls[2][2]["event_type"] == "manual_done"
    assert captured_headers == [
        {"X-Buddys-Pairing-Token": "pair-token-test-001"},
        {"X-Buddys-Pairing-Token": "pair-token-test-001"},
        {"X-Buddys-Pairing-Token": "pair-token-test-001"},
    ]

    output = capsys.readouterr().out
    assert '"ok": true' in output
    assert "Press the physical button after finishing." in output


def test_bad_event_exits_before_any_http_call() -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request(method: str, url: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        calls.append((method, url, payload))
        return {"unexpected": True}

    exit_code = cli.main(
        [
            "event",
            "--device-id",
            "dev_home_001",
            "--type",
            "bad",
            "--base-url",
            "http://runtime.test",
        ],
        request_json=fake_request,
    )

    assert exit_code == 2
    assert calls == []


def test_runtime_request_errors_return_clear_cli_error(capsys) -> None:
    def fake_request(
        method: str,
        url: str,
        payload: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        raise cli.RuntimeRequestError("runtime HTTP 404 device_not_found: device is not paired")

    exit_code = cli.main(
        [
            "heartbeat",
            "--device-id",
            "dev_home_001",
            "--base-url",
            "http://runtime.test",
            "--idempotency-key",
            "hb-test-001",
            "--pairing-token",
            "pair-token-test-001",
        ],
        request_json=fake_request,
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "runtime HTTP 404 device_not_found" in captured.err


def test_request_json_wraps_api_down_as_runtime_request_error() -> None:
    import urllib.error

    def failing_urlopen(request, timeout):  # noqa: ANN001
        raise urllib.error.URLError("connection refused")

    original_urlopen = cli.urllib.request.urlopen
    cli.urllib.request.urlopen = failing_urlopen
    try:
        try:
            cli._request_json("GET", "http://127.0.0.1:8000/healthz")
        except cli.RuntimeRequestError as exc:
            assert "runtime request failed" in str(exc)
            assert "connection refused" in str(exc)
        else:
            raise AssertionError("expected RuntimeRequestError")
    finally:
        cli.urllib.request.urlopen = original_urlopen


def test_request_json_wraps_http_error_detail_code() -> None:
    import io
    import urllib.error

    def failing_urlopen(request, timeout):  # noqa: ANN001
        body = io.BytesIO(b'{"detail":{"code":"device_not_found"}}')
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, body)

    original_urlopen = cli.urllib.request.urlopen
    cli.urllib.request.urlopen = failing_urlopen
    try:
        try:
            cli._request_json("POST", "http://127.0.0.1:8000/devices/dev_home_001/heartbeat", {})
        except cli.RuntimeRequestError as exc:
            assert "runtime HTTP 404 device_not_found" in str(exc)
            assert "/devices/dev_home_001/heartbeat" in str(exc)
        else:
            raise AssertionError("expected RuntimeRequestError")
    finally:
        cli.urllib.request.urlopen = original_urlopen
