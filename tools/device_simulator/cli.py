from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import quote

from tools.device_simulator.state import build_device_event, build_heartbeat_payload, render_screen


RequestJson = Callable[[str, str, dict[str, object] | None, dict[str, str] | None], dict[str, Any]]
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_AGENT_MACHINE_ENDPOINT = DEFAULT_BASE_URL
DEFAULT_DEVICE_PUBLIC_KEY = "sim-device-public-key-placeholder"
DEFAULT_AGENT_MACHINE_PUBLIC_KEY = "sim-agent-machine-public-key-placeholder"


class RuntimeRequestError(RuntimeError):
    """Raised when the simulator cannot complete a runtime API request."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.device_simulator.cli",
        description=(
            "Run a local Buddys Buddy Body simulator against a runtime API. "
            f"Default runtime URL: {DEFAULT_BASE_URL}"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    pair = subparsers.add_parser("pair", help="P0 demo bootstrap: POST /buddies then /devices/{device_id}/pair")
    _add_common_args(pair)
    pair.add_argument("--user-id", default="user_demo")
    pair.add_argument("--space-id", default=None)
    pair.add_argument("--firmware-version", default="0.2.0-sim")
    pair.add_argument("--pairing-token", default=None)
    pair.add_argument("--idempotency-key", default=None)
    pair.add_argument("--device-public-key", default=DEFAULT_DEVICE_PUBLIC_KEY)
    pair.add_argument("--agent-machine-id", default=None)
    pair.add_argument("--agent-machine-type", default="local_dev")
    pair.add_argument("--agent-machine-endpoint", default=DEFAULT_AGENT_MACHINE_ENDPOINT)
    pair.add_argument("--agent-machine-public-key", default=DEFAULT_AGENT_MACHINE_PUBLIC_KEY)
    pair.add_argument("--runtime-version", default="0.2.0-sim")

    heartbeat = subparsers.add_parser("heartbeat", help="POST /devices/{device_id}/heartbeat")
    _add_common_args(heartbeat)
    heartbeat.add_argument("--firmware-version", default="0.2.0-sim")
    heartbeat.add_argument("--current-state", default="idle")
    heartbeat.add_argument("--uptime-ms", type=int, default=None)
    heartbeat.add_argument("--wifi-rssi", type=int, default=-55)
    heartbeat.add_argument("--idempotency-key", default=None)
    heartbeat.add_argument("--pairing-token", required=True)

    poll = subparsers.add_parser("poll", help="GET /devices/{device_id}/desired-state")
    _add_common_args(poll)
    poll.add_argument("--pairing-token", required=True)

    event = subparsers.add_parser("event", help="POST approve/reject/ack/manual_done device events")
    _add_common_args(event)
    event.add_argument("--type", required=True, help="approve, reject, ack, or manual_done")
    event.add_argument("--idempotency-key", default=None)
    event.add_argument("--payload-json", default="{}")
    event.add_argument("--pairing-token", required=True)

    return parser


def main(argv: Sequence[str] | None = None, request_json: RequestJson | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    requester = request_json or _request_json
    try:
        if args.command == "pair":
            buddy = requester("POST", _api_url(args.base_url, "buddies"), {"user_id": args.user_id})
            payload = _build_pair_payload(args, buddy)
            response = requester("POST", _device_url(args.base_url, args.device_id, "pair"), payload)
            _print_json({"buddy": buddy, "pairing_token": payload["pairing_token"], "pairing": response})
            return 0

        if args.command == "heartbeat":
            payload = build_heartbeat_payload(
                firmware_version=args.firmware_version,
                current_state=args.current_state,
                uptime_ms=args.uptime_ms if args.uptime_ms is not None else int(time.monotonic() * 1000),
                wifi_rssi=args.wifi_rssi,
                idempotency_key=args.idempotency_key or _idempotency_key("hb"),
            )
            response = requester(
                "POST",
                _device_url(args.base_url, args.device_id, "heartbeat"),
                payload,
                _device_auth_headers(args.pairing_token),
            )
            _print_json(response)
            return 0

        if args.command == "poll":
            response = requester(
                "GET",
                _device_url(args.base_url, args.device_id, "desired-state"),
                None,
                _device_auth_headers(args.pairing_token),
            )
            _print_json(response)
            print(render_screen(response))
            return 0

        if args.command == "event":
            payload = build_device_event(
                args.type,
                idempotency_key=args.idempotency_key or _idempotency_key(f"event-{args.type}"),
                payload=_parse_payload_json(args.payload_json),
            )
            response = requester(
                "POST",
                _device_url(args.base_url, args.device_id, "events"),
                payload,
                _device_auth_headers(args.pairing_token),
            )
            _print_json(response)
            return 0
    except RuntimeRequestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"error: unsupported command {args.command}", file=sys.stderr)
    return 2


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)


def _device_url(base_url: str, device_id: str, suffix: str) -> str:
    return _api_url(base_url, "devices", quote(device_id, safe=""), suffix)


def _api_url(base_url: str, *parts: str) -> str:
    suffix = "/".join(part.strip("/") for part in parts)
    return f"{base_url.rstrip('/')}/{suffix}"


def _build_pair_payload(args: argparse.Namespace, buddy: dict[str, Any]) -> dict[str, object]:
    buddy_id = _required_response_text(buddy, "buddy_id")
    owner_user_id = _required_response_text(buddy, "user_id")
    space_id = args.space_id or _required_response_text(buddy, "space_id")
    return {
        "buddy_id": buddy_id,
        "space_id": space_id,
        "public_key": args.device_public_key,
        "firmware_version": args.firmware_version,
        "pairing_token": args.pairing_token or _idempotency_key("pair-token"),
        "agent_machine": {
            "agent_machine_id": args.agent_machine_id or f"agent_machine_{args.device_id}",
            "owner_user_id": owner_user_id,
            "machine_type": args.agent_machine_type,
            "endpoint": args.agent_machine_endpoint,
            "public_key": args.agent_machine_public_key,
            "runtime_version": args.runtime_version,
        },
        "idempotency_key": args.idempotency_key or _idempotency_key("pair"),
    }


def _request_json(
    method: str,
    url: str,
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    data = None
    request_headers = {"accept": "application/json"}
    if headers:
        request_headers.update(headers)
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        request_headers["content-type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeRequestError(_format_http_error(exc, method, url)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeRequestError(f"runtime request failed for {method} {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeRequestError(f"runtime request timed out for {method} {url}") from exc

    if not body:
        return {}
    try:
        parsed = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeRequestError(f"runtime returned invalid JSON for {method} {url}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("runtime response must be a JSON object")
    return parsed


def _parse_payload_json(value: str) -> dict[str, object]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("--payload-json must decode to a JSON object")
    return parsed


def _print_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _idempotency_key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _required_response_text(response: dict[str, Any], field_name: str) -> str:
    value = response.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeRequestError(f"runtime response missing required field: {field_name}")
    return value


def _device_auth_headers(pairing_token: str) -> dict[str, str]:
    return {"X-Buddys-Pairing-Token": pairing_token}


def _format_http_error(exc: urllib.error.HTTPError, method: str, url: str) -> str:
    detail_code = _http_error_detail_code(exc)
    if detail_code:
        return f"runtime HTTP {exc.code} {detail_code} for {method} {url}"
    return f"runtime HTTP {exc.code} {exc.reason} for {method} {url}"


def _http_error_detail_code(exc: urllib.error.HTTPError) -> str | None:
    try:
        body = exc.read()
    except OSError:
        return None
    if not body:
        return None
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    detail = parsed.get("detail")
    if isinstance(detail, dict):
        code = detail.get("code")
        if isinstance(code, str) and code.strip():
            return code
    return None


if __name__ == "__main__":
    raise SystemExit(main())
