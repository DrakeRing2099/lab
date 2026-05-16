/**
 * WebSocket gateway — Redis order book → browser
 *
 * WHAT THIS FILE DOES
 * ────────────────────
 * 1. Serves index.html over HTTP (so the browser has a page to load)
 * 2. Upgrades that same HTTP server to handle WebSocket connections
 * 3. Connects to Redis with TWO clients (explained below)
 * 4. Subscribes to trades:channel — pushes fills to all browsers instantly
 * 5. Polls book:bids / book:asks every 200ms — pushes book state to all browsers
 * 6. On new browser connect — immediately sends current book so screen isn't blank
 *
 * WHY TWO REDIS CLIENTS?
 * ───────────────────────
 * Redis Pub/Sub is a mode. The moment you call SUBSCRIBE on a client,
 * that client enters subscriber mode and can ONLY receive messages —
 * it cannot run ZRANGE, GET, or any other command until you UNSUBSCRIBE.
 *
 * So we need two separate connections:
 *   subClient  — locked in subscriber mode, only receives Pub/Sub messages
 *   queryClient — free to run ZRANGE, GET, etc. for book snapshots
 *
 * This is a real Redis gotcha. Almost everyone hits it the first time.
 *
 * WHY NOT JUST USE PUB/SUB FOR THE BOOK TOO?
 * ────────────────────────────────────────────
 * The engine publishes trades to trades:channel. It does NOT publish
 * book snapshots — it just writes to the sorted sets. We could add
 * a "book changed" pub/sub event from the engine, but polling every
 * 200ms is simpler and cheap (two ZRANGE calls on RAM). For a real
 * system you'd publish book snapshots too.
 *
 * THE FAN-OUT PATTERN
 * ────────────────────
 * When a trade arrives from Redis, we loop over every connected
 * WebSocket client and send the same message to each.
 *
 *   Redis → Node → [browser1, browser2, browser3, ...]
 *
 * This is called fan-out. One event in, N pushes out. Node's event
 * loop handles this on a single thread — no locking, no threads.
 * Each ws.send() is non-blocking; Node queues it and moves on.
 */

const http = require("http");
const fs   = require("fs");
const path = require("path");
const WebSocket = require("ws");
const Redis = require("ioredis");

const PORT       = 8080;
const REDIS_HOST = "localhost";
const REDIS_PORT = 6379;

// ── Redis key names (mirror src/config.py) ───────────────────────
const BIDS_KEY      = "book:bids";
const ASKS_KEY      = "book:asks";
const MID_KEY       = "book:mid";
const TRADES_CHANNEL= "trades:channel";
const BOOK_DEPTH    = 15;

// ── 1. HTTP server — serves index.html ───────────────────────────
//
// Node's built-in http module. No Express.
// Every request gets index.html — this is a single-page app,
// there are no other routes.
const httpServer = http.createServer((req, res) => {
  const filePath = path.join(__dirname, "public", "index.html");
  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(500);
      res.end("Error loading index.html");
      return;
    }
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(data);
  });
});

// ── 2. WebSocket server — attached to the same HTTP server ───────
//
// The 'ws' library handles the HTTP → WebSocket upgrade handshake.
// When a browser connects, it first sends an HTTP request with:
//   Upgrade: websocket
//   Connection: Upgrade
//   Sec-WebSocket-Key: <random base64>
//
// The ws library responds with:
//   101 Switching Protocols
//   Sec-WebSocket-Accept: <derived key>
//
// After that, the TCP connection stays open and both sides speak
// the WebSocket frame protocol — not HTTP anymore.
//
// { server: httpServer } tells ws to piggyback on our HTTP server
// (same port, same process) rather than open a new port.
const wss = new WebSocket.Server({ server: httpServer });

// ── 3. Redis clients ─────────────────────────────────────────────
const subClient   = new Redis({ host: REDIS_HOST, port: REDIS_PORT });
const queryClient = new Redis({ host: REDIS_HOST, port: REDIS_PORT });

// ── Helper: broadcast to all connected browsers ──────────────────
//
// wss.clients is a Set of all currently connected WebSocket objects.
// WebSocket.OPEN means the connection is live (not connecting/closing).
// We serialize once, send to everyone — efficient for large fan-outs.
function broadcast(payload) {
  const message = JSON.stringify(payload);
  for (const client of wss.clients) {
    if (client.readyState === WebSocket.OPEN) {
      client.send(message);
    }
  }
}

// ── Helper: read current book state from Redis ───────────────────
//
// ZREVRANGE book:bids 0 14 WITHSCORES → top 15 bids, highest first
// ZRANGE    book:asks 0 14 WITHSCORES → top 15 asks, lowest first
//
// ioredis returns: [member, score, member, score, ...]
// We reshape into [[price, qty_placeholder], ...] pairs.
// Note: sorted sets only store (score=price, member=order_id).
// We don't have qty here — for the browser display we show price
// levels only, not per-order qty. Good enough for a dashboard.
async function getBookSnapshot() {
  const [bidsRaw, asksRaw, mid] = await Promise.all([
    queryClient.zrevrange(BIDS_KEY, 0, BOOK_DEPTH - 1, "WITHSCORES"),
    queryClient.zrange(ASKS_KEY,  0, BOOK_DEPTH - 1, "WITHSCORES"),
    queryClient.get(MID_KEY),
  ]);

  // Reshape [member, score, member, score] → [[price, orderId], ...]
  const parse = (raw) => {
    const result = [];
    for (let i = 0; i < raw.length; i += 2) {
      result.push({
        orderId: raw[i],
        price:   parseFloat(raw[i + 1]),
      });
    }
    return result;
  };

  return {
    type: "book",
    bids: parse(bidsRaw),
    asks: parse(asksRaw),
    mid:  mid ? parseFloat(mid) : null,
  };
}

// ── 4. Subscribe to trades:channel ───────────────────────────────
//
// subClient.subscribe puts this client into subscriber mode.
// The "message" event fires every time the Python engine calls
// PUBLISH trades:channel <payload>.
//
// payload is a JSON string (the trade dict from Trade.to_hash_dict())
// We parse it, reshape it, and broadcast to all browsers.
subClient.subscribe(TRADES_CHANNEL, (err) => {
  if (err) {
    console.error("[redis] Failed to subscribe:", err.message);
    return;
  }
  console.log(`[redis] Subscribed to '${TRADES_CHANNEL}'`);
});

subClient.on("message", (channel, message) => {
  if (channel !== TRADES_CHANNEL) return;

  try {
    // The Python engine publishes: json.dumps(trade.to_hash_dict())
    // which is a dict with string values (price, qty as strings)
    const raw = JSON.parse(message);
    const trade = {
      type:      "trade",
      tradeId:   raw.trade_id,
      price:     parseFloat(raw.price),
      qty:       parseFloat(raw.qty),
      buyer:     raw.buyer_id,
      seller:    raw.seller_id,
      timestamp: parseFloat(raw.timestamp),
    };
    broadcast(trade);
    console.log(`[trade] ${trade.qty} @ ${trade.price}  ${trade.buyer} ← ${trade.seller}`);
  } catch (e) {
    console.error("[redis] Failed to parse trade message:", e.message);
  }
});

// ── 5. Book snapshot broadcast loop ──────────────────────────────
//
// Every 200ms: read sorted sets, broadcast current book to everyone.
// setInterval is Node's way of scheduling recurring work.
// The callback is async because getBookSnapshot uses await.
//
// 200ms is fast enough to feel live, cheap enough not to matter
// (two ZRANGE calls on a local Redis = ~0.5ms total).
setInterval(async () => {
  try {
    if (wss.clients.size === 0) return; // nobody connected, skip
    const snapshot = await getBookSnapshot();
    broadcast(snapshot);
  } catch (e) {
    console.error("[book] Snapshot error:", e.message);
  }
}, 200);

// ── 6. On new browser connection ─────────────────────────────────
//
// When a browser first connects, send it the current book immediately
// so it doesn't sit blank waiting for the next interval.
//
// The "connection" event fires once per new WebSocket client.
// ws.on("close") fires when that client disconnects.
wss.on("connection", async (ws) => {
  console.log(`[ws] Client connected  (total: ${wss.clients.size})`);

  try {
    const snapshot = await getBookSnapshot();
    ws.send(JSON.stringify(snapshot));
  } catch (e) {
    console.error("[ws] Failed to send initial snapshot:", e.message);
  }

  ws.on("close", () => {
    console.log(`[ws] Client disconnected  (total: ${wss.clients.size})`);
  });

  ws.on("error", (err) => {
    console.error("[ws] Client error:", err.message);
  });
});

// ── 7. Start listening ────────────────────────────────────────────
//
// httpServer.listen starts the HTTP server. The WebSocket server
// is already attached to it, so both are live on the same port.
httpServer.listen(PORT, () => {
  console.log(`[server] Running on http://localhost:${PORT}`);
  console.log(`[server] WebSocket on  ws://localhost:${PORT}`);
  console.log(`[server] Redis         ${REDIS_HOST}:${REDIS_PORT}`);
});

// ── Graceful shutdown ─────────────────────────────────────────────
process.on("SIGINT", async () => {
  console.log("\n[server] Shutting down...");
  await subClient.quit();
  await queryClient.quit();
  process.exit(0);
});