"""Send one signed sample event twice; uses only the Python standard library."""
import hashlib
import hmac
import json
import os
import time
import urllib.request
import uuid

body = json.dumps({"order_id": "SIGNED-DEMO", "amount_cents": 4900}).encode()
timestamp = str(int(time.time()))
secret = os.getenv("WEBHOOK_SECRET", "local-demo-secret-change-me")
digest = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
event_id = str(uuid.uuid4())
for _ in range(2):
    request = urllib.request.Request(
        "http://127.0.0.1:8000/api/webhooks", data=body,
        headers={"Content-Type": "application/json", "X-Event-ID": event_id,
                 "X-Webhook-Timestamp": timestamp, "X-Webhook-Signature": digest},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        print(response.status, response.read().decode())
