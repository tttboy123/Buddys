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
