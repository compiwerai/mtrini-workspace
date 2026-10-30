// Mtrini free-model relay: holds the sponsored Heabsy key, forwards chat requests from
// Mtrini Workspace, and keeps spending inside daily limits. Plain JavaScript with no
// Cloudflare imports, so the same logic runs in the Worker and in Node tests.
//
// Stored per UTC day, erased when the day changes: spend per install id (a random id the
// app makes), spend per hashed IP address, and total spend. Prompts are never stored.

export const DEFAULTS = {
  UPSTREAM_URL: "https://api.heabsy.com/v1",
  MODEL: "qwen38",
  PRICE_INPUT_PER_M: "1.00", // fresh input tokens, USD per million
  PRICE_CACHED_PER_M: "0.0761", // cached input tokens
  PRICE_OUTPUT_PER_M: "3.00",
  USER_DAILY_USD: "0.10",
  IP_DAILY_USD: "0.30", // stops one machine from resetting its install id to get more
  GLOBAL_DAILY_USD: "1.60", // 30 days x 1.60 stays under the $50 monthly sponsorship
  USER_RPM: "10",
  GLOBAL_RPM: "50", // the sponsored key allows 60 a minute; keep some headroom
  USER_CONCURRENCY: "2",
  GLOBAL_CONCURRENCY: "8", // the sponsored key allows 8 requests in parallel
  MAX_TOKENS: "8192",
  MAX_BODY_BYTES: "300000",
  UPGRADE_URL: "https://platform.heabsy.com/r/mtrini",
};

const ALLOWED_FIELDS = ["messages", "tools", "tool_choice", "temperature", "top_p", "stop", "stream",
  "response_format", "parallel_tool_calls", "seed", "presence_penalty", "frequency_penalty"];

export function config(env) {
  const c = {};
  for (const [k, v] of Object.entries(DEFAULTS)) c[k] = env?.[k] ?? v;
  return c;
}

const num = (v) => Number.parseFloat(v);

export function utcDay(now = Date.now()) {
  return new Date(now).toISOString().slice(0, 10);
}

/** Cost in USD of one response, from its OpenAI-style usage block. */
export function costOf(usage, cfg) {
  if (!usage) return null;
  const prompt = usage.prompt_tokens || 0;
  const cached = usage.prompt_tokens_details?.cached_tokens ?? usage.cached_tokens ?? 0;
  const fresh = Math.max(0, prompt - cached);
  const out = usage.completion_tokens || 0;
  return (fresh * num(cfg.PRICE_INPUT_PER_M) + cached * num(cfg.PRICE_CACHED_PER_M)
    + out * num(cfg.PRICE_OUTPUT_PER_M)) / 1e6;
}

/** Used when a response carries no usage: price the request as all-fresh input plus 1,000 output tokens. */
export function estimateCost(bodyBytes, cfg) {
  return ((bodyBytes / 3.5) * num(cfg.PRICE_INPUT_PER_M) + 1000 * num(cfg.PRICE_OUTPUT_PER_M)) / 1e6;
}

const round = (x) => Math.round(x * 1e6) / 1e6;

/**
 * Daily counters behind one storage (a Durable Object in production, a Map in tests).
 * storage: { get(key), put(key, value), deleteAll() }
 */
export class Limiter {
  constructor(storage, env) {
    this.storage = storage;
    this.cfg = config(env);
    this.minute = new Map(); // "user:minute" / "*:minute" -> request count (memory only)
    this.inflight = new Map(); // user -> [start times]
  }

  async _today(now) {
    const day = utcDay(now);
    if ((await this.storage.get("day")) !== day) {
      await this.storage.deleteAll();
      await this.storage.put("day", day);
    }
    return day;
  }

  /** Check every limit for one request; on success it counts as in flight until record(). */
  async reserve(user, ip, now = Date.now()) {
    const c = this.cfg;
    await this._today(now);
    const total = (await this.storage.get("total")) || 0;
    if (total >= num(c.GLOBAL_DAILY_USD)) {
      return deny("global_limit", "The free model has reached today's limit for everyone. It resets at "
        + `midnight UTC. To keep going now, add your own Heabsy key: ${c.UPGRADE_URL}`);
    }
    if (((await this.storage.get(`u:${user}`)) || 0) >= num(c.USER_DAILY_USD)
        || ((await this.storage.get(`ip:${ip}`)) || 0) >= num(c.IP_DAILY_USD)) {
      return deny("daily_limit", "You've used today's free model allowance. It resets at midnight UTC. "
        + `For more, add your own Heabsy key: ${c.UPGRADE_URL}`);
    }
    const m = Math.floor(now / 60000);
    if ((this.minute.get(`*:${m}`) || 0) >= num(c.GLOBAL_RPM)) {
      return deny("busy", "The free model is busy right now. Try again in a minute.");
    }
    if ((this.minute.get(`${user}:${m}`) || 0) >= num(c.USER_RPM)) {
      return deny("rate_limit", "Too many requests in a minute. Wait a moment and try again.");
    }
    const live = (this.inflight.get(user) || []).filter((t) => now - t < 5 * 60000);
    if (live.length >= num(c.USER_CONCURRENCY)) {
      return deny("concurrency", "Another request is still running. Try again when it finishes.");
    }
    let running = 0;
    for (const [u, times] of this.inflight) {
      running += (u === user ? live : times.filter((t) => now - t < 5 * 60000)).length;
    }
    if (running >= num(c.GLOBAL_CONCURRENCY)) {
      return deny("busy", "The free model is busy right now. Try again in a minute.");
    }
    for (const k of [...this.minute.keys()]) if (!k.endsWith(`:${m}`)) this.minute.delete(k);
    this.minute.set(`*:${m}`, (this.minute.get(`*:${m}`) || 0) + 1);
    this.minute.set(`${user}:${m}`, (this.minute.get(`${user}:${m}`) || 0) + 1);
    this.inflight.set(user, [...live, now]);
    return { ok: true };
  }

  /** Add a finished request's cost (0 if it failed) and release its in-flight slot. */
  async record(user, ip, cost, now = Date.now()) {
    const live = this.inflight.get(user) || [];
    live.shift();
    if (live.length) this.inflight.set(user, live); else this.inflight.delete(user);
    if (!(cost > 0)) return;
    await this._today(now);
    for (const key of ["total", `u:${user}`, `ip:${ip}`]) {
      await this.storage.put(key, round(((await this.storage.get(key)) || 0) + cost));
    }
  }

  async usage(user) {
    await this._today(Date.now());
    return { user: (await this.storage.get(`u:${user}`)) || 0, total: (await this.storage.get("total")) || 0 };
  }
}

function deny(code, message) {
  return { ok: false, code, message };
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function error(status, code, message) {
  return json({ error: { message, type: code, code } }, status);
}

export async function hashIp(ip, day, salt = "") {
  const data = new TextEncoder().encode(`${salt}|${day}|${ip}`);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)].slice(0, 12).map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Pull the usage block out of an OpenAI-style SSE stream, chunk by chunk. */
export function usageScanner() {
  let buf = "";
  let usage = null;
  return {
    push(text) {
      buf += text;
      const lines = buf.split("\n");
      buf = lines.pop();
      for (const line of lines) {
        const s = line.trim();
        if (!s.startsWith("data:") || !s.includes('"usage"')) continue;
        try {
          const u = JSON.parse(s.slice(5).trim()).usage;
          if (u) usage = u;
        } catch { /* partial or non-JSON line */ }
      }
    },
    get usage() { return usage; },
  };
}

/**
 * Handle one request. deps: { limiter: {reserve, record}, fetch, waitUntil? }
 */
export async function handle(request, env, deps) {
  const cfg = config(env);
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "");

  if (request.method === "GET" && (path === "" || path === "/health")) {
    return json({ ok: true, service: "mtrini-free", model: cfg.MODEL, configured: Boolean(env?.HEABSY_KEY) });
  }
  if (request.method === "GET" && path === "/v1/models") {
    return json({ object: "list", data: [{ id: cfg.MODEL, object: "model", owned_by: "heabsy" }] });
  }
  if (path !== "/v1/chat/completions") return error(404, "not_found", "Not found.");
  if (request.method !== "POST") return error(405, "method_not_allowed", "Use POST.");
  if (!env?.HEABSY_KEY) return error(503, "not_configured", "The free model isn't set up yet.");

  const user = request.headers.get("x-mtrini-install") || "";
  if (!/^[0-9a-f]{32}$/.test(user)) {
    return error(400, "bad_install_id", "Update Mtrini Workspace to use the free model.");
  }
  const raw = await request.text();
  if (raw.length > num(cfg.MAX_BODY_BYTES)) {
    return error(413, "too_large", "This conversation is too long for the free model. Start a new session "
      + "or run /compact.");
  }
  let body;
  try {
    body = JSON.parse(raw);
  } catch {
    return error(400, "bad_json", "Request body must be JSON.");
  }
  if (!Array.isArray(body.messages) || !body.messages.length) {
    return error(400, "bad_request", "messages is required.");
  }

  const day = utcDay();
  const ip = await hashIp(request.headers.get("cf-connecting-ip") || "unknown", day, env.IP_SALT || "");
  const verdict = await deps.limiter.reserve(user, ip);
  if (!verdict.ok) return error(429, verdict.code, verdict.message);

  const out = { model: cfg.MODEL };
  for (const k of ALLOWED_FIELDS) if (body[k] !== undefined) out[k] = body[k];
  out.max_tokens = Math.min(Number(body.max_tokens || body.max_completion_tokens) || num(cfg.MAX_TOKENS),
    num(cfg.MAX_TOKENS));
  if (out.stream) out.stream_options = { include_usage: true };

  let upstream;
  try {
    upstream = await deps.fetch(`${cfg.UPSTREAM_URL.replace(/\/+$/, "")}/chat/completions`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${env.HEABSY_KEY}` },
      body: JSON.stringify(out),
    });
  } catch {
    await deps.limiter.record(user, ip, 0);
    return error(502, "upstream_unreachable", "The free model is unreachable right now. Try again shortly.");
  }

  if (!upstream.ok) {
    await deps.limiter.record(user, ip, 0);
    if (upstream.status === 402) {
      return error(503, "paused", "The free model is paused for now. To keep going, add your own Heabsy "
        + `key: ${cfg.UPGRADE_URL}`);
    }
    if (upstream.status === 429) return error(429, "busy", "The free model is busy right now. Try again in a minute.");
    if (upstream.status >= 400 && upstream.status < 500) {
      let msg = "";
      try { msg = (await upstream.json())?.error?.message || ""; } catch { /* not JSON */ }
      return error(upstream.status, "bad_request", msg || "The model rejected this request.");
    }
    return error(502, "upstream_error", "The free model had a problem. Try again shortly.");
  }

  if (!out.stream) {
    const data = await upstream.json();
    const cost = costOf(data.usage, cfg) ?? estimateCost(raw.length, cfg);
    await deps.limiter.record(user, ip, cost);
    return json(data);
  }

  const scan = usageScanner();
  const decoder = new TextDecoder();
  const recordWhenDone = async () => {
    await deps.limiter.record(user, ip, costOf(scan.usage, cfg) ?? estimateCost(raw.length, cfg));
  };
  const { readable, writable } = new TransformStream({
    transform(chunk, controller) {
      scan.push(decoder.decode(chunk, { stream: true }));
      controller.enqueue(chunk);
    },
    async flush() {
      await recordWhenDone();
    },
  });
  const piping = upstream.body.pipeTo(writable).catch(recordWhenDone);
  if (deps.waitUntil) deps.waitUntil(piping);
  return new Response(readable, {
    status: 200,
    headers: { "content-type": upstream.headers.get("content-type") || "text/event-stream", "cache-control": "no-cache" },
  });
}
