import assert from "node:assert/strict";
import { test } from "node:test";

import { BridgeHub, bridgeToken } from "../src/bridge.js";
import { handle } from "../src/core.js";
import { makeD1 } from "../dev/d1.mjs";

// A fake socket that records what it was sent.
function sock(deviceId, name = "") {
  const ws = { sent: [], send(t) { this.sent.push(JSON.parse(t)); }, last() { return this.sent.at(-1); } };
  return { ws, meta: { deviceId, name, role: null, pub: null } };
}

function hub(...peers) {
  return new BridgeHub(() => peers, (ws, meta) => { peers.find((p) => p.ws === ws).meta = meta; });
}

const PUB = "B".repeat(87);

test("presence lists PCs (with their public key) and phones after hello", () => {
  const pc = sock("pc1", "Desk"), phone = sock("ph1", "Pixel");
  const h = hub(pc, phone);
  h.message(pc.ws, pc.meta, JSON.stringify({ t: "hello", role: "pc", name: "Desk", pub: PUB }));
  h.message(phone.ws, phone.meta, JSON.stringify({ t: "hello", role: "phone", name: "Pixel" }));
  assert.deepEqual(phone.ws.last(), { t: "presence", pcs: [{ id: "pc1", name: "Desk", pub: PUB }], phones: [{ id: "ph1", name: "Pixel" }] });
});

test("a PC must announce a public key", () => {
  const pc = sock("pc1");
  hub(pc).message(pc.ws, pc.meta, JSON.stringify({ t: "hello", role: "pc" }));
  assert.equal(pc.ws.last().code, "bad_key");
});

test("messages are routed phone to PC and back, opaque", () => {
  const pc = sock("pc1"), phone = sock("ph1");
  const h = hub(pc, phone);
  h.message(pc.ws, pc.meta, JSON.stringify({ t: "hello", role: "pc", pub: PUB }));
  h.message(phone.ws, phone.meta, JSON.stringify({ t: "hello", role: "phone" }));
  h.message(phone.ws, phone.meta, JSON.stringify({ t: "to", to: "pc1", data: { c: "ciphertext" } }));
  assert.deepEqual(pc.ws.last(), { t: "from", from: "ph1", role: "phone", data: { c: "ciphertext" } });
  h.message(pc.ws, pc.meta, JSON.stringify({ t: "to", to: "ph1", data: "reply" }));
  assert.deepEqual(phone.ws.last(), { t: "from", from: "pc1", role: "pc", data: "reply" });
});

test("no hello, offline targets, same-role and oversized frames are refused", () => {
  const pc = sock("pc1"), phone = sock("ph1"), phone2 = sock("ph2");
  const h = hub(pc, phone, phone2);
  h.message(phone.ws, phone.meta, JSON.stringify({ t: "to", to: "pc1", data: 1 }));
  assert.equal(phone.ws.last().code, "no_hello");
  h.message(phone.ws, phone.meta, JSON.stringify({ t: "hello", role: "phone" }));
  h.message(phone2.ws, phone2.meta, JSON.stringify({ t: "hello", role: "phone" }));
  h.message(phone.ws, phone.meta, JSON.stringify({ t: "to", to: "pc1", data: 1 }));
  assert.equal(phone.ws.last().code, "offline");
  h.message(phone.ws, phone.meta, JSON.stringify({ t: "to", to: "ph2", data: 1 }));
  assert.equal(phone.ws.last().code, "same_role");
  h.message(phone.ws, phone.meta, "x".repeat(1024 * 1024 + 1));
  assert.equal(phone.ws.last().code, "too_large");
});

test("token comes from the Authorization header or the WebSocket subprotocols", () => {
  assert.deepEqual(bridgeToken(new Request("https://x/bridge", { headers: { authorization: "Bearer abc" } })), { token: "abc", protocol: null });
  assert.deepEqual(bridgeToken(new Request("https://x/bridge", { headers: { "sec-websocket-protocol": "mtrini.v1, bearer.xyz" } })),
    { token: "xyz", protocol: "mtrini.v1" });
  assert.equal(bridgeToken(new Request("https://x/bridge")).token, null);
});

// ---- the Worker side: /bridge authenticates, and revoking a device kicks it off the bridge

async function signedIn() {
  const db = makeD1();
  const now = Date.UTC(2026, 10, 1, 12);
  const calls = [];
  const deps = {
    db, now: () => now,
    bridge: (userId) => ({ fetch: async (req) => { calls.push({ userId, url: req.url, headers: Object.fromEntries(req.headers) }); return new Response("ok"); } }),
  };
  const t = Math.floor(now / 1000);
  const { sha256 } = await import("../src/core.js");
  await db.prepare("INSERT INTO users (id, name, email, avatar, created_at) VALUES ('u1', 'A', '', '', ?)").bind(t).run();
  for (const [dev, tok] of [["d1", "tok1"], ["d2", "tok2"]]) {
    await db.prepare("INSERT INTO devices (id, user_id, name, platform, created_at, last_seen) VALUES (?, 'u1', ?, 'windows', ?, ?)").bind(dev, dev + "-name", t, t).run();
    await db.prepare("INSERT INTO sessions (token_hash, device_id, user_id, expires_at) VALUES (?, ?, 'u1', ?)").bind(await sha256(tok), dev, t + 3600).run();
  }
  const call = (path, init = {}) => handle(new Request("https://cloud.test" + path, init), {}, deps);
  return { call, calls };
}

test("/bridge forwards an authenticated socket to the account's bridge", async () => {
  const { call, calls } = await signedIn();
  assert.equal((await call("/bridge")).status, 401);
  assert.equal((await call("/bridge", { headers: { "sec-websocket-protocol": "mtrini.v1, bearer.nope" } })).status, 401);
  const r = await call("/bridge", { headers: { upgrade: "websocket", "sec-websocket-protocol": "mtrini.v1, bearer.tok1" } });
  assert.equal(r.status, 200);
  assert.equal(calls[0].userId, "u1");
  assert.equal(calls[0].headers["x-mtrini-device"], "d1");
  assert.equal(calls[0].headers["x-mtrini-device-name"], "d1-name");
  assert.equal(calls[0].headers["x-mtrini-protocol"], "mtrini.v1");
  assert.equal(calls[0].headers.authorization, undefined);
});

test("revoking a device disconnects it from the bridge", async () => {
  const { call, calls } = await signedIn();
  const r = await call("/devices/d2/revoke", { method: "POST", headers: { authorization: "Bearer tok1" } });
  assert.equal(r.status, 200);
  assert.ok(calls.some((c) => c.url === "https://bridge/kick?device=d2"));
});
