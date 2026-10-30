import assert from "node:assert/strict";
import { test } from "node:test";

import { handle } from "../src/core.js";
import { makeD1 } from "../dev/d1.mjs";

const BASE = "https://cloud.test";
const ENV = {
  BASE_URL: BASE,
  GOOGLE_CLIENT_ID: "g-id", GOOGLE_CLIENT_SECRET: "g-secret",
  DISCORD_CLIENT_ID: "d-id", DISCORD_CLIENT_SECRET: "d-secret",
  GITHUB_CLIENT_ID: "h-id", GITHUB_CLIENT_SECRET: "h-secret",
};

// Stand-in providers: each code maps to a profile; records what the token endpoints received.
function fakeProviders() {
  const codes = new Map();
  const tokenCalls = [];
  const fetch = async (url, init = {}) => {
    const u = String(url);
    if (/oauth2\.googleapis|discord\.com\/api\/oauth2\/token|github\.com\/login\/oauth\/access_token/.test(u)) {
      const form = new URLSearchParams(String(init.body));
      tokenCalls.push({ url: u, form: Object.fromEntries(form) });
      const prof = codes.get(form.get("code"));
      return prof ? Response.json({ access_token: `tok-${form.get("code")}` }) : Response.json({ error: "bad_code" }, { status: 400 });
    }
    const auth = (init.headers || {}).authorization || "";
    const prof = codes.get(auth.replace("Bearer tok-", ""));
    if (u.endsWith("/user/emails")) return Response.json(prof.emails || []);
    return Response.json(prof.body);
  };
  return { fetch, codes, tokenCalls };
}

function setup(envOver = {}) {
  const db = makeD1();
  const fp = fakeProviders();
  let clock = Date.UTC(2026, 9, 30, 12);
  const deps = { db, fetch: fp.fetch, now: () => clock };
  const env = { ...ENV, ...envOver };
  const call = (method, path, { body, token } = {}) => handle(new Request(BASE + path, {
    method, headers: { "content-type": "application/json", ...(token ? { authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  }), env, deps);

  // Full sign-in: app starts, browser goes through the provider, app polls.
  async function signIn(provider, profileBody, { token, emails } = {}) {
    const start = await (await call("POST", "/auth/device", { body: { device_name: "Test PC", platform: "windows" }, token })).json();
    const login = await call("GET", `/login/${start.login_id}`);
    assert.equal(login.status, 200);
    const go = await call("GET", `/auth/${provider}/start?login=${start.login_id}`);
    assert.equal(go.status, 302);
    const to = new URL(go.headers.get("location"));
    const code = `code-${provider}-${fp.codes.size}`;
    fp.codes.set(code, { body: profileBody, emails });
    const cb = await call("GET", `/auth/${provider}/callback?code=${code}&state=${to.searchParams.get("state")}`);
    const poll = await (await call("POST", "/auth/device/poll", { body: { login_id: start.login_id, poll_secret: start.poll_secret } })).json();
    return { start, to, cb, poll };
  }
  return { db, fp, env, call, signIn, tick: (s) => { clock += s * 1000; } };
}

const GOOGLE = { sub: "g-1", email: "ayham@example.com", email_verified: true, name: "Ayham", picture: "https://p/a.png" };

test("Google sign-in creates an account and a device, and the token is collected only once", async () => {
  const t = setup();
  const { start, to, cb, poll } = await t.signIn("google", GOOGLE);
  assert.equal(to.origin + to.pathname, "https://accounts.google.com/o/oauth2/v2/auth");
  assert.equal(to.searchParams.get("redirect_uri"), `${BASE}/auth/google/callback`);
  assert.equal(to.searchParams.get("code_challenge_method"), "S256");
  assert.match(await cb.text(), /signed in as Ayham/);
  assert.equal(poll.status, "done");
  assert.equal(poll.user.email, "ayham@example.com");
  assert.equal(poll.devices.length, 1);
  assert.ok(poll.devices[0].current);
  assert.equal(t.fp.tokenCalls[0].form.code_verifier.length > 40, true); // PKCE verifier sent to Google
  const me = await (await t.call("GET", "/me", { token: poll.session_token })).json();
  assert.equal(me.identities[0].provider, "google");
  const again = await t.call("POST", "/auth/device/poll", { body: { login_id: start.login_id, poll_secret: start.poll_secret } });
  assert.equal(again.status, 404); // collected once
  const stored = t.db.raw.prepare("SELECT token_hash FROM sessions").all();
  assert.ok(stored.every((s) => s.token_hash !== poll.session_token)); // only hashes are stored
});

test("polling: pending, wrong secret, expired", async () => {
  const t = setup();
  const start = await (await t.call("POST", "/auth/device", { body: {} })).json();
  const p1 = await (await t.call("POST", "/auth/device/poll", { body: { login_id: start.login_id, poll_secret: start.poll_secret } })).json();
  assert.equal(p1.status, "pending");
  assert.equal((await t.call("POST", "/auth/device/poll", { body: { login_id: start.login_id, poll_secret: "nope" } })).status, 404);
  t.tick(11 * 60);
  assert.equal((await t.call("GET", `/login/${start.login_id}`)).status, 410);
  const p2 = await (await t.call("POST", "/auth/device/poll", { body: { login_id: start.login_id, poll_secret: start.poll_secret } })).json();
  assert.equal(p2.status, "expired");
});

test("signing in again with the same Google account reaches the same account from a second device", async () => {
  const t = setup();
  const a = await t.signIn("google", GOOGLE);
  const b = await t.signIn("google", GOOGLE);
  assert.equal(a.poll.user.id, b.poll.user.id);
  assert.equal(b.poll.devices.length, 2);
});

test("a different provider with the same email is a separate account (no linking by email)", async () => {
  const t = setup();
  const a = await t.signIn("google", GOOGLE);
  const d = await t.signIn("discord", { id: "d-1", username: "ayham", email: "ayham@example.com", verified: true });
  assert.notEqual(a.poll.user.id, d.poll.user.id);
  assert.equal(t.fp.tokenCalls[1].form.code_verifier, undefined); // Discord: no PKCE
});

test("linking another sign-in to a signed-in account, and refusing one owned by another account", async () => {
  const t = setup();
  const a = await t.signIn("google", GOOGLE);
  const link = await t.signIn("github", { id: 7, login: "ayham", name: null, email: null },
    { token: a.poll.session_token, emails: [{ email: "a@gh.test", primary: true, verified: true }] });
  assert.equal(link.poll.status, "linked");
  const me = await (await t.call("GET", "/me", { token: a.poll.session_token })).json();
  assert.deepEqual(me.identities.map((i) => i.provider), ["google", "github"]);
  assert.equal(me.identities[1].email, "a@gh.test"); // fetched from /user/emails

  const other = await t.signIn("discord", { id: "d-9", username: "x" });
  const steal = await t.signIn("github", { id: 7, login: "ayham" }, { token: other.poll.session_token });
  assert.equal(steal.cb.status, 400);
  assert.match(await steal.cb.text(), /already used by a different Mtrini account/);
  assert.equal(steal.poll.status, "failed");
});

test("revoking a device signs it out; signing out removes this device", async () => {
  const t = setup();
  const pc = await t.signIn("google", GOOGLE);
  const phone = await t.signIn("google", GOOGLE);
  const r = await t.call("POST", `/devices/${phone.poll.device_id}/revoke`, { token: pc.poll.session_token });
  assert.equal(r.status, 200);
  assert.equal((await t.call("GET", "/me", { token: phone.poll.session_token })).status, 401);
  await t.call("POST", "/auth/logout", { token: pc.poll.session_token });
  assert.equal((await t.call("GET", "/me", { token: pc.poll.session_token })).status, 401);
});

test("unlinking keeps at least one sign-in; deleting the account removes everything", async () => {
  const t = setup();
  const a = await t.signIn("google", GOOGLE);
  assert.equal((await t.call("DELETE", "/me/identities/google", { token: a.poll.session_token })).status, 400);
  await t.signIn("discord", { id: "d-2", username: "y" }, { token: a.poll.session_token });
  const after = await (await t.call("DELETE", "/me/identities/google", { token: a.poll.session_token })).json();
  assert.deepEqual(after.identities.map((i) => i.provider), ["discord"]);
  const del = await (await t.call("DELETE", "/me", { token: a.poll.session_token })).json();
  assert.equal(del.deleted, true);
  for (const table of ["users", "identities", "devices", "sessions"]) {
    assert.equal(t.db.raw.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get().n, 0, table);
  }
});

test("a forged or reused state is rejected", async () => {
  const t = setup();
  const start = await (await t.call("POST", "/auth/device", { body: {} })).json();
  await t.call("GET", `/auth/google/start?login=${start.login_id}`);
  assert.equal((await t.call("GET", "/auth/google/callback?code=x&state=forged")).status, 410);
});

test("only configured providers are offered", async () => {
  const t = setup({ DISCORD_CLIENT_ID: "", GITHUB_CLIENT_SECRET: "" });
  const h = await (await t.call("GET", "/health")).json();
  assert.deepEqual(h.providers, ["google"]);
  const start = await (await t.call("POST", "/auth/device", { body: { provider: "google" } })).json();
  assert.match(start.url, /\?provider=google$/);
  const page = await t.call("GET", new URL(start.url).pathname + new URL(start.url).search);
  assert.equal(page.status, 302); // straight to Google
});

test("abandoned sign-ins are cleared out", async () => {
  const t = setup();
  await t.call("POST", "/auth/device", { body: {} });
  t.tick(25 * 60);
  await t.call("POST", "/auth/device", { body: {} });
  assert.equal(t.db.raw.prepare("SELECT COUNT(*) AS n FROM logins").get().n, 1);
});
