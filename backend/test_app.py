import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from backend import app as module


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DB", str(tmp_path / "test.db"))
    monkeypatch.setattr(module, "SECRET", "test-secret")
    monkeypatch.setattr(module.time, "time", lambda: 1000)
    return TestClient(module.app)


def signed(client, event_id="event-1", amount=100, timestamp="1000", body=None):
    body = body or json.dumps({"order_id": "ORDER-1", "amount_cents": amount}).encode()
    digest = hmac.new(b"test-secret", timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return client.post("/api/webhooks", content=body, headers={
        "X-Event-ID": event_id, "X-Webhook-Timestamp": timestamp, "X-Webhook-Signature": digest,
    })


def test_signature_and_replay_window(client):
    assert client.post("/api/webhooks", json={}).status_code == 401
    assert signed(client, timestamp="1").status_code == 401
    assert signed(client).status_code == 202


def test_duplicate_and_conflicting_payload(client):
    assert signed(client).json()["duplicate"] is False
    assert signed(client).json()["duplicate"] is True
    assert signed(client, amount=200).status_code == 409
    assert len(client.get("/api/events").json()["events"]) == 1


def test_concurrent_duplicate_intake(client):
    client.get("/api/health")
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: signed(client).json(), range(6)))
    assert sum(not result["duplicate"] for result in results) == 1


def test_retry_delay_delivery_and_replay(client, monkeypatch):
    result = client.post("/api/demo", json={
        "order_id": "ORDER-2", "amount_cents": 2999, "simulated_failures": 3,
    })
    event_id = result.json()["id"]
    assert client.post("/api/process").json()["processed"] == 1
    assert client.post("/api/process").json()["processed"] == 0
    for now in [1002, 1006]:
        monkeypatch.setattr(module.time, "time", lambda: now)
        client.post("/api/process")
    row = client.get("/api/events").json()["events"][0]
    assert row["status"] == "dead_letter"
    assert row["attempts"] == 3
    assert client.post(f"/api/events/{event_id}/replay").status_code == 200
    client.post("/api/process")
    row = client.get("/api/events").json()["events"][0]
    assert row["status"] == "delivered"
    assert len(row["history"]) == 5
    assert client.post(f"/api/events/{event_id}/replay").status_code == 409


def test_recovery_before_attempt_limit(client, monkeypatch):
    client.post("/api/demo", json={"order_id": "ORDER-3", "amount_cents": 10, "simulated_failures": 1})
    client.post("/api/process")
    monkeypatch.setattr(module.time, "time", lambda: 1002)
    client.post("/api/process")
    assert client.get("/api/events").json()["events"][0]["status"] == "delivered"


def test_validation_and_unknown_event(client):
    assert signed(client, amount=-1).status_code == 422
    assert signed(client, body=b"x" * 17000).status_code == 413
    assert client.post("/api/events/missing/replay").status_code == 404
    assert client.post("/api/demo", json={"order_id": "", "amount_cents": 1}).status_code == 422
