// Mtrini Cloud, phase 2: the live bridge between a phone and the PCs on the same account.
//
// One bridge per account (a Durable Object). Every device connects with its normal session token and
// sends JSON frames:
//   {t: "hello", role: "pc" | "phone", name, pub?}  pub: the PC's public key (base64url, ECDH P-256)
//   {t: "to", to: <deviceId>, data}                  data is opaque, end-to-end encrypted by the devices
// and receives:
//   {t: "presence", pcs: [{id, name, pub}], phones: [{id, name}]}  whenever someone comes or goes
//   {t: "from", from: <deviceId>, role, data}
//   {t: "error", code, message}
// The bridge only routes; it never reads or stores `data`. Pairing (keys, the 6-digit code) happens between
// the devices inside `data`, so a bridge that swapped keys would be caught by the code check.

export const MAX_FRAME = 1024 * 1024; // bytes
const MAX_NAME = 80;

function send(ws, obj) {
  try {
    ws.send(JSON.stringify(obj));
  } catch {
    // the socket is closing; presence will catch up
  }
}

// Routing logic, independent of Cloudflare so it can be tested in Node. `peers()` returns the open
// sockets as [{ws, meta}], and `save(ws, meta)` stores a socket's metadata (survives hibernation).
export class BridgeHub {
  constructor(peers, save) {
    this.peers = peers;
    this.save = save;
  }

  presence() {
    const pcs = [], phones = [];
    for (const { meta } of this.peers()) {
      if (meta.role === "pc" && meta.pub) pcs.push({ id: meta.deviceId, name: meta.name, pub: meta.pub });
      else if (meta.role === "phone") phones.push({ id: meta.deviceId, name: meta.name });
    }
    const msg = { t: "presence", pcs, phones };
    for (const { ws, meta } of this.peers()) if (meta.role) send(ws, msg);
  }

  message(ws, meta, text) {
    if (typeof text !== "string" || text.length > MAX_FRAME) return send(ws, { t: "error", code: "too_large", message: "Message too large." });
    let msg;
    try {
      msg = JSON.parse(text);
    } catch {
      return send(ws, { t: "error", code: "bad_json", message: "Not JSON." });
    }
    if (msg.t === "hello") {
      if (msg.role !== "pc" && msg.role !== "phone") return send(ws, { t: "error", code: "bad_role", message: "role must be pc or phone." });
      if (msg.role === "pc" && !(typeof msg.pub === "string" && /^[\w-]{40,200}$/.test(msg.pub))) {
        return send(ws, { t: "error", code: "bad_key", message: "A PC must announce its public key." });
      }
      const next = { ...meta, role: msg.role, name: String(msg.name || meta.name || "").slice(0, MAX_NAME), pub: msg.role === "pc" ? msg.pub : null };
      this.save(ws, next);
      return this.presence();
    }
    if (msg.t === "to") {
      if (!meta.role) return send(ws, { t: "error", code: "no_hello", message: "Say hello first." });
      const target = this.peers().find((p) => p.meta.deviceId === msg.to && p.meta.role);
      if (!target) return send(ws, { t: "error", code: "offline", message: "That device is not connected." });
      if (target.meta.role === meta.role) return send(ws, { t: "error", code: "same_role", message: "Phones talk to PCs." });
      return send(target.ws, { t: "from", from: meta.deviceId, role: meta.role, data: msg.data });
    }
    if (msg.t === "ping") return send(ws, { t: "pong" });
    return send(ws, { t: "error", code: "unknown", message: "Unknown message type." });
  }
}

// Picks the session token from `Authorization: Bearer …` (desktop) or from the WebSocket subprotocols
// `mtrini.v1, bearer.<token>` (browsers and the phone app can't set headers on a WebSocket).
export function bridgeToken(request) {
  const m = /^Bearer\s+(\S+)$/.exec(request.headers.get("authorization") || "");
  if (m) return { token: m[1], protocol: null };
  const protos = (request.headers.get("sec-websocket-protocol") || "").split(",").map((s) => s.trim());
  const b = protos.find((p) => p.startsWith("bearer."));
  return b ? { token: b.slice(7), protocol: protos.includes("mtrini.v1") ? "mtrini.v1" : null } : { token: null, protocol: null };
}

// The Durable Object: one per account. Uses WebSocket hibernation, so idle connections cost nothing.
export class Bridge {
  constructor(state) {
    this.state = state;
    this.hub = new BridgeHub(
      () => this.state.getWebSockets().filter((ws) => ws.readyState === undefined || ws.readyState === 1)
        .map((ws) => ({ ws, meta: ws.deserializeAttachment() || {} })),
      (ws, meta) => ws.serializeAttachment(meta),
    );
  }

  async fetch(request) {
    // Internal: the Worker asks to disconnect a device that was revoked or signed out.
    if (new URL(request.url).pathname === "/kick") {
      const device = new URL(request.url).searchParams.get("device");
      for (const ws of this.state.getWebSockets()) {
        if ((ws.deserializeAttachment() || {}).deviceId === device) ws.close(4001, "Device signed out");
      }
      this.hub.presence();
      return new Response("ok");
    }
    if (request.headers.get("upgrade") !== "websocket") return new Response("Expected a WebSocket.", { status: 426 });
    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);
    this.state.acceptWebSocket(server);
    server.serializeAttachment({
      deviceId: request.headers.get("x-mtrini-device"),
      name: request.headers.get("x-mtrini-device-name") || "",
      role: null,
      pub: null,
    });
    const headers = {};
    const protocol = request.headers.get("x-mtrini-protocol");
    if (protocol) headers["sec-websocket-protocol"] = protocol;
    return new Response(null, { status: 101, webSocket: client, headers });
  }

  webSocketMessage(ws, message) {
    this.hub.message(ws, ws.deserializeAttachment() || {}, typeof message === "string" ? message : "");
  }

  webSocketClose(ws) {
    try {
      ws.close();
    } catch {
      // already closed
    }
    this.hub.presence();
  }

  webSocketError(ws) {
    this.webSocketClose(ws);
  }
}
