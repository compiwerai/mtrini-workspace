import assert from "node:assert/strict";
import { test } from "node:test";

import { costOf, handle, Limiter, usageScanner } from "../src/core.js";

const USER = "a".repeat(32);
const OTHER = "b".repeat(32);

class MemStorage {
  constructor() { this.m = new Map(); }
  async get(k) { return this.m.get(k); }
  async put(k, v) { this.m.set(k, v); }
  async deleteAll() { this.m.clear(); }
}

function setup(envOver = {}, upstreamReply) {
  const env = { HEABSY_KEY: "sk-test", ...envOver };
  const limiter = new Limiter(new MemStorage(), env);
  const calls = [];
  const fetch = async (url, init) => {
    calls.push({ url, init, body: JSON.parse(init.body) });
    return upstreamReply ? upstreamReply(JSON.parse(init.body)) : Response.json({
      choices: [{ message: { role: "assistant", content: "hi" } }],
      usage: { prompt_tokens: 10000, completion_tokens: 2000, prompt_tokens_details: { cached_tokens: 8000 } },
    });
  };
  const send = (body, headers = {}) => handle(new Request("https://relay.test/v1/chat/completions", {
    method: "POST",
    headers: { "content-type": "application/json", "x-mtrini-install": USER, "cf-connecting-ip": "1.2.3.4", ...headers },
    body: JSON.stringify(body),
  }), env, { limiter, fetch });
  return { env, limiter, calls, send };
}

const MSG = { messages: [{ role: "user", content: "hello" }] };

test("prices fresh, cached and output tokens separately", () => {
  const cfg = { PRICE_INPUT_PER_M: "1.00", PRICE_CACHED_PER_M: "0.0761", PRICE_OUTPUT_PER_M: "3.00" };
  const c = costOf({ prompt_tokens: 10000, completion_tokens: 2000, prompt_tokens_details: { cached_tokens: 8000 } }, cfg);
  assert.equal(Math.round(c * 1e7), Math.round((2000 * 1 + 8000 * 0.0761 + 2000 * 3) / 1e6 * 1e7));
  assert.equal(costOf(null, cfg), null);
});

test("forwards with the sponsored key, forces the model and caps max_tokens", async () => {
  const { send, calls } = setup();
  const r = await send({ ...MSG, model: "something-expensive", max_tokens: 100000, user: "x", stream: false });
  assert.equal(r.status, 200);
  assert.equal(calls[0].url, "https://api.heabsy.com/v1/chat/completions");
  assert.equal(calls[0].init.headers.authorization, "Bearer sk-test");
  assert.equal(calls[0].body.model, "qwen38");
  assert.equal(calls[0].body.max_tokens, 8192);
  assert.equal(calls[0].body.user, undefined); // only known fields go upstream
});

test("needs a valid install id and the key", async () => {
  assert.equal((await setup().send(MSG, { "x-mtrini-install": "nope" })).status, 400);
  assert.equal((await setup({ HEABSY_KEY: "" }).send(MSG)).status, 503);
});

test("stops a user at their daily allowance, others continue", async () => {
  const { send, limiter } = setup({ USER_DAILY_USD: "0.01", USER_RPM: "100" });
  let r;
  for (let i = 0; i < 5; i++) r = await send(MSG); // each response costs ~0.0086
  assert.equal(r.status, 429);
  assert.equal((await r.json()).error.code, "daily_limit");
  const other = await handle(new Request("https://relay.test/v1/chat/completions", {
    method: "POST", headers: { "x-mtrini-install": OTHER, "cf-connecting-ip": "5.6.7.8" }, body: JSON.stringify(MSG),
  }), { HEABSY_KEY: "k" }, { limiter, fetch: async () => Response.json({ choices: [], usage: { prompt_tokens: 1, completion_tokens: 1 } }) });
  assert.equal(other.status, 200);
});

test("the global ceiling holds for everyone", async () => {
  const { send } = setup({ GLOBAL_DAILY_USD: "0.02", USER_DAILY_USD: "1", IP_DAILY_USD: "1", USER_RPM: "100" });
  const codes = [];
  for (let i = 0; i < 5; i++) codes.push((await send(MSG)).status);
  assert.deepEqual(codes.slice(0, 3), [200, 200, 200]);
  assert.equal(codes[4], 429);
});

test("the same IP can't get more by changing install ids", async () => {
  const { send } = setup({ USER_DAILY_USD: "1", IP_DAILY_USD: "0.01", USER_RPM: "100" });
  for (let i = 0; i < 2; i++) await send(MSG);
  const r = await send(MSG, { "x-mtrini-install": "c".repeat(32) });
  assert.equal(r.status, 429);
});

test("per-minute limit", async () => {
  const { send } = setup({ USER_RPM: "2" });
  assert.equal((await send(MSG)).status, 200);
  assert.equal((await send(MSG)).status, 200);
  assert.equal((await send(MSG)).status, 429);
});

test("no more than 8 requests run at once across everyone", async () => {
  const lim = new Limiter(new MemStorage(), { GLOBAL_CONCURRENCY: "3", GLOBAL_RPM: "100" });
  const ids = ["1", "2", "3", "4"].map((d) => d.repeat(32));
  const v = [];
  for (const id of ids) v.push((await lim.reserve(id, `ip${id}`)).ok);
  assert.deepEqual(v, [true, true, true, false]);
  await lim.record(ids[0], "ip", 0); // one finishes, a slot frees up
  assert.ok((await lim.reserve(ids[3], "ip4")).ok);
});

test("counters reset on a new UTC day", async () => {
  const lim = new Limiter(new MemStorage(), { USER_DAILY_USD: "0.01" });
  const day1 = Date.UTC(2026, 9, 30, 23, 0);
  assert.ok((await lim.reserve(USER, "ip", day1)).ok);
  await lim.record(USER, "ip", 0.05, day1);
  assert.equal((await lim.reserve(USER, "ip", day1)).ok, false);
  assert.ok((await lim.reserve(USER, "ip", day1 + 2 * 3600e3)).ok);
});

test("upstream out of credit becomes a clear 'paused' message and costs nothing", async () => {
  const { send, limiter } = setup({}, () => new Response('{"error":{"message":"insufficient_balance"}}', { status: 402 }));
  const r = await send(MSG);
  assert.equal(r.status, 503);
  assert.match((await r.json()).error.message, /paused/);
  assert.equal((await limiter.usage(USER)).total, 0);
});

test("streams through and charges from the final usage chunk", async () => {
  const sse = [
    'data: {"choices":[{"delta":{"content":"He"}}]}\n\n',
    'data: {"choices":[{"delta":{"content":"llo"}}]}\n\n',
    'data: {"choices":[],"usage":{"prompt_tokens":1000,"completion_tokens":100}}\n\n',
    "data: [DONE]\n\n",
  ];
  const { send, limiter, calls } = setup({}, () => new Response(new ReadableStream({
    start(c) { for (const s of sse) c.enqueue(new TextEncoder().encode(s)); c.close(); },
  }), { headers: { "content-type": "text/event-stream" } }));
  const r = await send({ ...MSG, stream: true });
  assert.equal(await r.text(), sse.join(""));
  assert.deepEqual(calls[0].body.stream_options, { include_usage: true });
  await new Promise((res) => setTimeout(res, 10));
  assert.equal((await limiter.usage(USER)).user, (1000 * 1 + 100 * 3) / 1e6);
});

test("usage scanner copes with chunks split mid-line", () => {
  const s = usageScanner();
  s.push('data: {"choices":[],"usa');
  s.push('ge":{"prompt_tokens":5,"completion_tokens":1}}\n\n');
  assert.deepEqual(s.usage, { prompt_tokens: 5, completion_tokens: 1 });
});

test("health and models answer without a key", async () => {
  const r = await handle(new Request("https://relay.test/health"), {}, {});
  assert.deepEqual(await r.json(), { ok: true, service: "mtrini-free", model: "qwen38", configured: false });
  const m = await (await handle(new Request("https://relay.test/v1/models"), {}, {})).json();
  assert.equal(m.data[0].id, "qwen38");
});
