from fastapi.testclient import TestClient

from buddys_api.device_store import DeviceRegistry
from buddys_api.main import create_app
from tools.device_simulator import cli


def test_device_simulator_pair_heartbeat_and_event_are_visible_in_sync_events(tmp_path) -> None:
    store = DeviceRegistry()
    client = TestClient(create_app(device_store=store, db_path=tmp_path / "buddys.sqlite3"))

    def request_json(method: str, url: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        path = url.removeprefix("http://runtime.test")
        response = client.request(method, path, json=payload)
        assert response.status_code < 400, response.text
        return response.json()

    assert (
        cli.main(
            [
                "pair",
                "--device-id",
                "dev_home_sync_001",
                "--base-url",
                "http://runtime.test",
                "--user-id",
                "user_demo",
                "--pairing-token",
                "pair-token-sync-flow-001",
                "--idempotency-key",
                "pair-sync-flow-001",
            ],
            request_json=request_json,
        )
        == 0
    )
    assert (
        cli.main(
            [
                "heartbeat",
                "--device-id",
                "dev_home_sync_001",
                "--base-url",
                "http://runtime.test",
                "--idempotency-key",
                "hb-sync-flow-001",
            ],
            request_json=request_json,
        )
        == 0
    )
    assert (
        cli.main(
            [
                "event",
                "--device-id",
                "dev_home_sync_001",
                "--base-url",
                "http://runtime.test",
                "--type",
                "manual_done",
                "--idempotency-key",
                "event-sync-flow-001",
                "--payload-json",
                '{"source":"simulator"}',
            ],
            request_json=request_json,
        )
        == 0
    )

    events_response = client.get("/sync/events", params={"since_revision": 0})

    assert events_response.status_code == 200
    events = events_response.json()["events"]
    assert [event["event_type"] for event in events] == [
        "buddy.created",
        "device.paired",
        "device.heartbeat",
        "device.event",
    ]
    assert events[-3]["entity_id"] == "dev_home_sync_001"
    assert events[-2]["entity_id"] == "dev_home_sync_001"
    assert events[-1]["entity_id"] == "dev_home_sync_001"
    assert events[-1]["payload_summary"] == {"device_id": "dev_home_sync_001", "event_type": "manual_done"}

    snapshot = client.get("/sync/snapshot").json()
    assert snapshot["devices"][0]["device_id"] == "dev_home_sync_001"
    assert snapshot["latest_heartbeats"]["dev_home_sync_001"]["current_state"] == "idle"
    assert snapshot["device_events"][0]["event_type"] == "manual_done"
