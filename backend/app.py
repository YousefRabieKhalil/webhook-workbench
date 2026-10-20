"""Local portfolio demo: durable, signed webhook intake and retry processing."""
import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

DB = os.getenv("DATABASE_PATH", "events.db")
SECRET = os.getenv("WEBHOOK_SECRET", "local-demo-secret-change-me")
MAX_ATTEMPTS = 3
app = FastAPI(title="Webhook Workbench", version="1.0.0")


@contextmanager
def database():
    connection = sqlite3.connect(DB, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("""CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL,
            created REAL NOT NULL, next_attempt REAL NOT NULL,
            history TEXT NOT NULL DEFAULT '[]')""")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


class Order(BaseModel):
    order_id: str = Field(min_length=1, max_length=80)
    amount_cents: int = Field(gt=0, le=100000000)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    simulated_failures: int = Field(default=0, ge=0, le=3)


def signature(body: bytes, timestamp: str) -> str:
    return hmac.new(SECRET.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def receive(event_id: str, order: Order):
    payload = json.dumps(order.model_dump(), sort_keys=True)
    now = time.time()
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT payload FROM events WHERE id=?", (event_id,)).fetchone()
        if existing:
            if existing["payload"] != payload:
                raise HTTPException(409, "Event ID already exists with different content")
            return {"id": event_id, "duplicate": True}
        db.execute(
            "INSERT INTO events(id,payload,status,failures,created,next_attempt) VALUES(?,?,?,?,?,?)",
            (event_id, payload, "pending", order.simulated_failures, now, now),
        )
    return {"id": event_id, "duplicate": False}


@app.get("/api/health")
def health():
    with database() as db:
        db.execute("SELECT 1")
    return {"status": "ok"}


@app.post("/api/webhooks", status_code=202)
async def webhook(request: Request):
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > 16384:
            raise HTTPException(413, "Payload exceeds 16 KiB")
    timestamp = request.headers.get("x-webhook-timestamp", "")
    supplied = request.headers.get("x-webhook-signature", "")
    event_id = request.headers.get("x-event-id", "")
    try:
        fresh = abs(time.time() - int(timestamp)) <= 300
    except ValueError:
        fresh = False
    if not fresh or not hmac.compare_digest(signature(body, timestamp), supplied):
        raise HTTPException(401, "Invalid or expired signature")
    if not event_id or len(event_id) > 100:
        raise HTTPException(400, "X-Event-ID must contain 1–100 characters")
    try:
        order = Order.model_validate_json(body)
    except ValueError:
        raise HTTPException(422, "Invalid order payload")
    return receive(event_id, order)


@app.post("/api/demo", status_code=202)
def demo(order: Order):
    """Convenience producer for a trusted local demo, bypassing signature intake."""
    return receive(str(uuid.uuid4()), order)


@app.get("/api/events")
def events():
    with database() as db:
        rows = db.execute("SELECT * FROM events ORDER BY created DESC LIMIT 100").fetchall()
        counts = dict(db.execute("SELECT status,count(*) FROM events GROUP BY status").fetchall())
    return {"events": [
        {**dict(row), "payload": json.loads(row["payload"]), "history": json.loads(row["history"])}
        for row in rows
    ], "counts": counts}


@app.post("/api/process")
def process():
    """One deterministic worker tick, with a transaction serializing concurrent ticks."""
    now = time.time()
    processed = 0
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute(
            "SELECT * FROM events WHERE status IN ('pending','retrying') AND next_attempt<=? LIMIT 20",
            (now,),
        ).fetchall()
        for row in rows:
            attempt = row["attempts"] + 1
            failed = attempt <= row["failures"]
            status = ("dead_letter" if attempt >= MAX_ATTEMPTS else "retrying") if failed else "delivered"
            history = json.loads(row["history"])
            history.append({"attempt": attempt, "at": now, "result": "simulated 503" if failed else "simulated 200"})
            db.execute(
                "UPDATE events SET attempts=?,status=?,next_attempt=?,history=? WHERE id=?",
                (attempt, status, now + 2 ** attempt, json.dumps(history), row["id"]),
            )
            processed += 1
    return {"processed": processed}


@app.post("/api/events/{event_id}/replay")
def replay(event_id: str):
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT status,history FROM events WHERE id=?", (event_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Event not found")
        if row["status"] != "dead_letter":
            raise HTTPException(409, "Only dead-letter events can be replayed")
        history = json.loads(row["history"])
        history.append({"attempt": 0, "at": time.time(), "result": "manual replay; simulated outage cleared"})
        db.execute(
            "UPDATE events SET status='pending',attempts=0,failures=0,next_attempt=?,history=? WHERE id=?",
            (time.time(), json.dumps(history), event_id),
        )
    return {"id": event_id, "status": "pending"}


assets = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if assets.exists():
    app.mount("/", StaticFiles(directory=assets, html=True), name="frontend")
