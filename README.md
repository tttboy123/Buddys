# Buddys Runtime MVP

Local P0 runtime for the first Buddys demo loop.

## Run Tests

```bash
.venv/bin/python -m pytest tests/golden/test_golden_trace.py -v
.venv/bin/python -m pytest -v
```

## Start API

```bash
PYTHONPATH=src .venv/bin/python -m uvicorn buddys_api.main:app --host 127.0.0.1 --port 8000 --reload
```

## Device Simulator

Run the local API first, then use the P0 Buddy Body simulator:

```bash
PYTHONPATH=src .venv/bin/python -m uvicorn buddys_api.main:app --host 127.0.0.1 --port 8000 --reload

.venv/bin/python -m tools.device_simulator.cli pair --device-id dev_home_001 --user-id user_demo --base-url http://127.0.0.1:8000
.venv/bin/python -m tools.device_simulator.cli heartbeat --device-id dev_home_001 --base-url http://127.0.0.1:8000
.venv/bin/python -m tools.device_simulator.cli poll --device-id dev_home_001 --base-url http://127.0.0.1:8000
.venv/bin/python -m tools.device_simulator.cli event --device-id dev_home_001 --type approve --base-url http://127.0.0.1:8000
.venv/bin/python -m tools.device_simulator.cli event --device-id dev_home_001 --type reject --base-url http://127.0.0.1:8000
.venv/bin/python -m tools.device_simulator.cli event --device-id dev_home_001 --type ack --base-url http://127.0.0.1:8000
.venv/bin/python -m tools.device_simulator.cli event --device-id dev_home_001 --type manual_done --base-url http://127.0.0.1:8000
```

`pair` is a P0/demo bootstrap command. It creates a local home Buddy for `--user-id`, then pairs the simulator device with placeholder public keys so the later heartbeat, poll, and event commands run against a fresh local API.

## Curl Demo

```bash
curl -s http://127.0.0.1:8000/healthz

buddy_id=$(curl -s -X POST http://127.0.0.1:8000/buddies \
  -H 'content-type: application/json' \
  -d '{"user_id":"user_1"}' | jq -r '.buddy_id')

message=$(curl -s -X POST "http://127.0.0.1:8000/buddies/${buddy_id}/messages" \
  -H 'content-type: application/json' \
  -d '{"user_id":"user_1","message":"把客厅灯调暗"}')

proposal_id=$(printf '%s' "$message" | jq -r '.proposal_id')
trace_id=$(printf '%s' "$message" | jq -r '.trace_id')

curl -s -X POST "http://127.0.0.1:8000/proposals/${proposal_id}/confirm" \
  -H 'content-type: application/json' \
  -d '{"decision":"approved"}'

curl -s "http://127.0.0.1:8000/traces/${trace_id}" | jq
curl -s http://127.0.0.1:8000/cost-events | jq
```
