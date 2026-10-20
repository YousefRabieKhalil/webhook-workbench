import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

async function api(path, body) {
  const response = await fetch(
    `/api${path}`,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Request could not be processed",
    );
  return data;
}

function App() {
  const [data, setData] = useState({ events: [], counts: {} });
  const [selected, setSelected] = useState(null);
  const [failures, setFailures] = useState("1");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [filter, setFilter] = useState("all");
  const refresh = async () => setData(await api("/events"));
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, []);
  async function act(task) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await task();
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const current = data.events.find((e) => e.id === selected);
  const visible = data.events.filter(
    (e) => filter === "all" || e.status === filter,
  );
  const labels = {
    pending: "Pending",
    retrying: "Retrying",
    delivered: "Delivered",
    dead_letter: "Dead letter",
  };
  return (
    <div className="shell">
      <aside>
        <div className="brand">
          W
          <span>
            Webhook
            <br />
            Workbench
          </span>
        </div>
        <div className="nav">◈ &nbsp; Event inbox</div>
        <p className="aside-note">
          A personal engineering demo
          <br />
          Python · React · SQLite
        </p>
        <a href="https://github.com/YousefRabieKhalil">
          Built with Yousef Rabie Khalil
        </a>
      </aside>
      <main>
        <header>
          <div>
            <p className="eyebrow">INTEGRATION OPERATIONS / LOCAL SANDBOX</p>
            <h1>Every event. Accounted for.</h1>
            <p className="muted">
              Inspect deliveries, explore retries, and recover failed events.
            </p>
          </div>
          <span className="sandbox">● SIMULATED PROVIDER</span>
        </header>
        <section className="metrics" aria-label="Event totals">
          {Object.entries(labels).map(([key, label]) => (
            <div className="metric" key={key}>
              <span>{label}</span>
              <strong>{data.counts[key] || 0}</strong>
              <i className={key} />
            </div>
          ))}
        </section>
        <section className="producer">
          <div>
            <h2>Send a demo order</h2>
            <p>Choose how the simulated downstream service responds.</p>
          </div>
          <label>
            Delivery scenario
            <select
              value={failures}
              onChange={(e) => setFailures(e.target.value)}
            >
              <option value="0">Healthy · succeeds immediately</option>
              <option value="1">Transient outage · fails once</option>
              <option value="3">Persistent outage · dead letter</option>
            </select>
          </label>
          <button
            disabled={busy}
            onClick={() =>
              act(async () => {
                await api("/demo", {
                  order_id: `ORD-${Date.now()}`,
                  amount_cents: 12900,
                  simulated_failures: Number(failures),
                });
                setNotice("Demo order queued. Run the worker to process it.");
              })
            }
          >
            + Send event
          </button>
        </section>
        <div className="toolbar">
          <div>
            <h2>
              Event inbox <span className="count">{data.events.length}</span>
            </h2>
            <p className="muted">
              Latest 100 events · retry delays: 2s, then 4s · up to 3 attempts
            </p>
          </div>
          <div className="actions">
            <label className="sr-only" htmlFor="filter">
              Filter events
            </label>
            <select
              id="filter"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            >
              <option value="all">All statuses</option>
              {Object.entries(labels).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
            <button
              className="secondary"
              disabled={busy}
              onClick={() => act(refresh)}
            >
              Refresh
            </button>
            <button
              disabled={busy}
              onClick={() =>
                act(async () => {
                  const result = await api("/process", {});
                  setNotice(
                    `Processed ${result.processed} eligible event(s). Retries wait until their next attempt time.`,
                  );
                })
              }
            >
              {busy ? "Working…" : "Run worker →"}
            </button>
          </div>
        </div>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <p className="notice" role="status">
          {notice}
        </p>
        <div className="workspace">
          <section className="events" aria-label="Events">
            {!visible.length ? (
              <div className="empty">
                <div>↗</div>
                <h3>No events here yet</h3>
                <p>
                  Send a demo order above to explore the delivery lifecycle.
                </p>
              </div>
            ) : (
              visible.map((event) => (
                <button
                  className={`event ${selected === event.id ? "selected" : ""}`}
                  key={event.id}
                  onClick={() => setSelected(event.id)}
                >
                  <span className="event-icon">↗</span>
                  <span className="event-info">
                    <strong>{event.payload.order_id}</strong>
                    <small>
                      {new Date(event.created * 1000).toLocaleString()} ·{" "}
                      {event.payload.currency}{" "}
                      {(event.payload.amount_cents / 100).toFixed(2)}
                    </small>
                  </span>
                  <span className={`badge ${event.status}`}>
                    {labels[event.status]}
                  </span>
                  <span className="attempts">{event.attempts}/3</span>
                </button>
              ))
            )}
          </section>
          <section className="detail" aria-label="Event detail">
            {current ? (
              <>
                <p className="eyebrow">DELIVERY INSPECTOR</p>
                <h2>{current.payload.order_id}</h2>
                <p className="event-id">{current.id}</p>
                <h3>Payload</h3>
                <pre>{JSON.stringify(current.payload, null, 2)}</pre>
                <h3>Attempt history</h3>
                {current.history.length ? (
                  <ol>
                    {current.history.map((h, i) => (
                      <li key={i}>
                        <strong>
                          {h.attempt ? `Attempt ${h.attempt}` : "Replay"}
                        </strong>
                        <span>{h.result}</span>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="muted">Awaiting the first worker run.</p>
                )}
                {current.status === "retrying" && (
                  <p className="muted">
                    Eligible after{" "}
                    {new Date(current.next_attempt * 1000).toLocaleTimeString()}
                    . Run the worker again after this time.
                  </p>
                )}
                {current.status === "dead_letter" && (
                  <button
                    disabled={busy}
                    onClick={() =>
                      act(async () => {
                        await api(`/events/${current.id}/replay`, {});
                        setNotice(
                          "Outage cleared in the simulation. Run the worker to deliver the replay.",
                        );
                      })
                    }
                  >
                    Clear simulated outage & replay
                  </button>
                )}
              </>
            ) : (
              <div className="detail-empty">
                <span>◎</span>
                <h3>Follow an event’s journey</h3>
                <p>
                  Select an event to inspect its payload and delivery attempts.
                </p>
              </div>
            )}
          </section>
        </div>
        <footer>
          Signed intake · Durable event inbox · Idempotent ingestion ·
          Exponential retry · Dead-letter recovery
          <br />
          Local educational demo. Delivery is simulated; no real orders or
          payment requests are sent.
        </footer>
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")).render(<App />);
