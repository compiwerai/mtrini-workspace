// Mtrini Cloud, phase 1: accounts. Sign in with Google, Discord or GitHub; devices and sessions.
//
// Sign-in works without the app listening on any port:
//   1. the app calls POST /auth/device and opens the returned link in a browser;
//   2. the person picks a provider there and signs in;
//   3. the app polls POST /auth/device/poll until it receives its session token (once).
// Session tokens and poll secrets are stored only as SHA-256 hashes. Plain JavaScript (Web Crypto,
// fetch, a D1-style database), so the same code runs in the Worker and in Node tests.

const LOGIN_TTL = 10 * 60; // seconds
const SESSION_TTL = 90 * 24 * 3600;
const enc = new TextEncoder();

export const PROVIDERS = {
  google: {
    label: "Google",
    auth: "https://accounts.google.com/o/oauth2/v2/auth",
    token: "https://oauth2.googleapis.com/token",
    profile: "https://openidconnect.googleapis.com/v1/userinfo",
    scope: "openid email profile",
    pkce: true,
    extra: { prompt: "select_account" },
    map: (p) => ({ id: String(p.sub), email: p.email_verified ? p.email || "" : "", name: p.name || "",
      username: p.email || "", avatar: p.picture || "" }),
  },
  discord: {
    label: "Discord",
    auth: "https://discord.com/oauth2/authorize",
    token: "https://discord.com/api/oauth2/token",
    profile: "https://discord.com/api/users/@me",
    scope: "identify email",
    pkce: false,
    map: (p) => ({ id: String(p.id), email: p.verified ? p.email || "" : "", name: p.global_name || p.username || "",
      username: p.username || "", avatar: p.avatar ? `https://cdn.discordapp.com/avatars/${p.id}/${p.avatar}.png` : "" }),
  },
  github: {
    label: "GitHub",
    auth: "https://github.com/login/oauth/authorize",
    token: "https://github.com/login/oauth/access_token",
    profile: "https://api.github.com/user",
    emails: "https://api.github.com/user/emails",
    scope: "read:user user:email",
    pkce: true,
    map: (p) => ({ id: String(p.id), email: p.email || "", name: p.name || p.login || "", username: p.login || "",
      avatar: p.avatar_url || "" }),
  },
};

// ---------------------------------------------------------------- helpers

const b64url = (bytes) => btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
export const random = (n = 32) => b64url(crypto.getRandomValues(new Uint8Array(n)));

export async function sha256(text) {
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(text)));
  return [...d].map((b) => b.toString(16).padStart(2, "0")).join("");
}

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const err = (status, code, message) => json({ error: { code, message } }, status);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function page(title, body, status = 200) {
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)} · Mtrini</title><style>
:root{--bg:#f7f7f5;--card:#fff;--ink:#14161a;--muted:#5d6470;--rule:#e3e4e8;--accent:#0e7490}
@media (prefers-color-scheme:dark){:root{--bg:#0b0f14;--card:#141a21;--ink:#e8ebef;--muted:#9aa3ae;--rule:#26303b;--accent:#5ad1e6}}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{width:min(420px,calc(100% - 32px));background:var(--card);border:1px solid var(--rule);border-radius:18px;padding:28px}
h1{font-size:22px;margin:0 0 6px}p{color:var(--muted);margin:0 0 18px}
a.btn{display:block;text-align:center;padding:12px;border:1px solid var(--rule);border-radius:12px;margin:10px 0;color:var(--ink);text-decoration:none;font-weight:600}
a.btn:hover{border-color:var(--accent)}small{color:var(--muted)}</style></head><body><main>${body}</main></body></html>`;
  return new Response(html, { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
}

function config(env) {
  const overrides = env.PROVIDER_OVERRIDES ? JSON.parse(env.PROVIDER_OVERRIDES) : {};
  const out = {};
  for (const [name, p] of Object.entries(PROVIDERS)) {
    const id = env[`${name.toUpperCase()}_CLIENT_ID`];
    const secret = env[`${name.toUpperCase()}_CLIENT_SECRET`];
    if (id && secret) out[name] = { ...p, ...(overrides[name] || {}), clientId: id, clientSecret: secret };
  }
  return out;
}

const base = (env, request) => (env.BASE_URL || new URL(request.url).origin).replace(/\/+$/, "");

// ---------------------------------------------------------------- database

const one = (db, sql, ...args) => db.prepare(sql).bind(...args).first();
const all = async (db, sql, ...args) => (await db.prepare(sql).bind(...args).all()).results || [];
const run = (db, sql, ...args) => db.prepare(sql).bind(...args).run();

async function authUser(request, db, now) {
  const m = /^Bearer\s+(\S+)$/.exec(request.headers.get("authorization") || "");
  if (!m) return null;
  const s = await one(db, "SELECT * FROM sessions WHERE token_hash = ?", await sha256(m[1]));
  if (!s || s.expires_at < now) return null;
  await run(db, "UPDATE devices SET last_seen = ? WHERE id = ?", now, s.device_id);
  return { userId: s.user_id, deviceId: s.device_id, tokenHash: s.token_hash };
}

async function profile(db, userId, deviceId) {
  const u = await one(db, "SELECT id, name, email, avatar, created_at FROM users WHERE id = ?", userId);
  const ids = await all(db, "SELECT provider, email, username FROM identities WHERE user_id = ? ORDER BY created_at", userId);
  const devs = await all(db, "SELECT id, name, platform, created_at, last_seen FROM devices WHERE user_id = ? ORDER BY last_seen DESC", userId);
  return { user: u, identities: ids, devices: devs.map((d) => ({ ...d, current: d.id === deviceId })) };
}

async function deleteDevice(db, deviceId) {
  await run(db, "DELETE FROM sessions WHERE device_id = ?", deviceId);
  await run(db, "DELETE FROM devices WHERE id = ?", deviceId);
}

// ---------------------------------------------------------------- OAuth

async function exchange(p, code, redirectUri, verifier, fetchFn) {
  const form = new URLSearchParams({ client_id: p.clientId, client_secret: p.clientSecret, code,
    redirect_uri: redirectUri, grant_type: "authorization_code" });
  if (p.pkce && verifier) form.set("code_verifier", verifier);
  const r = await fetchFn(p.token, { method: "POST", body: form,
    headers: { "content-type": "application/x-www-form-urlencoded", accept: "application/json" } });
  const data = await r.json().catch(() => ({}));
  if (!r.ok || !data.access_token) throw new Error(data.error_description || data.error || `token exchange failed (${r.status})`);
  return data.access_token;
}

async function fetchProfile(name, p, accessToken, fetchFn) {
  const headers = { authorization: `Bearer ${accessToken}`, accept: "application/json", "user-agent": "Mtrini-Cloud" };
  const r = await fetchFn(p.profile, { headers });
  if (!r.ok) throw new Error(`profile request failed (${r.status})`);
  const prof = p.map(await r.json());
  if (name === "github" && !prof.email && p.emails) {
    const er = await fetchFn(p.emails, { headers });
    if (er.ok) {
      const list = await er.json();
      prof.email = (list.find((e) => e.primary && e.verified) || {}).email || "";
    }
  }
  return prof;
}

// ---------------------------------------------------------------- routes

export async function handle(request, env, deps) {
  const db = deps.db;
  const fetchFn = deps.fetch || fetch;
  const now = Math.floor((deps.now ? deps.now() : Date.now()) / 1000);
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";
  const providers = config(env);
  const method = request.method;
  let m;

  if (method === "GET" && (path === "/" || path === "/health")) {
    return json({ ok: true, service: "mtrini-cloud", providers: Object.keys(providers) });
  }

  // 1. The app starts a sign-in (with its session token when linking another sign-in).
  if (method === "POST" && path === "/auth/device") {
    const body = await request.json().catch(() => ({}));
    const who = await authUser(request, db, now);
    await run(db, "DELETE FROM logins WHERE created_at < ?", now - 2 * LOGIN_TTL);  // abandoned sign-ins
    const id = random(18);
    const secret = random(32);
    await run(db, `INSERT INTO logins (id, poll_hash, device_name, platform, link_user_id, created_at)
      VALUES (?, ?, ?, ?, ?, ?)`, id, await sha256(secret), String(body.device_name || "").slice(0, 80),
      String(body.platform || "").slice(0, 20), who ? who.userId : null, now);
    const provider = providers[body.provider] ? `?provider=${body.provider}` : "";
    return json({ login_id: id, poll_secret: secret, url: `${base(env, request)}/login/${id}${provider}`,
      interval: 2, expires_in: LOGIN_TTL, providers: Object.keys(providers) });
  }

  // 2a. The browser page: pick a provider (or go straight to the one the app asked for).
  if (method === "GET" && (m = /^\/login\/([\w-]+)$/.exec(path))) {
    const login = await one(db, "SELECT * FROM logins WHERE id = ?", m[1]);
    if (!login || login.created_at + LOGIN_TTL < now || login.status !== "pending") {
      return page("Link expired", "<h1>This sign-in link has expired</h1><p>Go back to Mtrini Workspace and start again.</p>", 410);
    }
    const want = url.searchParams.get("provider");
    if (want && providers[want]) return Response.redirect(`${base(env, request)}/auth/${want}/start?login=${m[1]}`, 302);
    const buttons = Object.entries(providers).map(([n, p]) =>
      `<a class="btn" href="/auth/${n}/start?login=${m[1]}">Continue with ${esc(p.label)}</a>`).join("");
    const what = login.link_user_id ? "Link another sign-in to your Mtrini account" : "Sign in to Mtrini";
    return page(what, `<h1>${what}</h1><p>For <strong>${esc(login.device_name || "Mtrini Workspace")}</strong>. Only continue if you just started this from the app.</p>${buttons || "<p>No sign-in providers are set up yet.</p>"}<small>Mtrini only receives your name, email and picture.</small>`);
  }

  // 2b. Off to the provider, with state and (where supported) PKCE.
  if (method === "GET" && (m = /^\/auth\/(\w+)\/start$/.exec(path))) {
    const p = providers[m[1]];
    const login = await one(db, "SELECT * FROM logins WHERE id = ?", url.searchParams.get("login") || "");
    if (!p) return page("Not available", "<h1>That sign-in isn't available</h1>", 404);
    if (!login || login.created_at + LOGIN_TTL < now || login.status !== "pending") {
      return page("Link expired", "<h1>This sign-in link has expired</h1><p>Go back to Mtrini Workspace and start again.</p>", 410);
    }
    const state = random(24);
    const verifier = random(48);
    await run(db, "UPDATE logins SET provider = ?, state = ?, verifier = ? WHERE id = ?", m[1], state, verifier, login.id);
    const q = new URLSearchParams({ client_id: p.clientId, redirect_uri: `${base(env, request)}/auth/${m[1]}/callback`,
      response_type: "code", scope: p.scope, state, ...(p.extra || {}) });
    if (p.pkce) {
      const challenge = b64url(new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(verifier))));
      q.set("code_challenge", challenge);
      q.set("code_challenge_method", "S256");
    }
    return Response.redirect(`${p.auth}?${q}`, 302);
  }

  // 2c. Back from the provider: find or create the account, make the device and its session.
  if (method === "GET" && (m = /^\/auth\/(\w+)\/callback$/.exec(path))) {
    const name = m[1];
    const p = providers[name];
    const state = url.searchParams.get("state") || "";
    const login = state ? await one(db, "SELECT * FROM logins WHERE state = ? AND provider = ?", state, name) : null;
    if (!p || !login || login.created_at + LOGIN_TTL < now || login.status !== "pending") {
      return page("Link expired", "<h1>This sign-in has expired</h1><p>Go back to Mtrini Workspace and start again.</p>", 410);
    }
    const fail = async (msg) => {
      await run(db, "UPDATE logins SET status = 'failed', error = ? WHERE id = ?", msg, login.id);
      return page("Sign-in failed", `<h1>Sign-in didn't work</h1><p>${esc(msg)}</p><p>Go back to Mtrini Workspace and try again.</p>`, 400);
    };
    if (url.searchParams.get("error")) return fail("The sign-in was cancelled.");
    let prof;
    try {
      const token = await exchange(p, url.searchParams.get("code") || "", `${base(env, request)}/auth/${name}/callback`, login.verifier, fetchFn);
      prof = await fetchProfile(name, p, token, fetchFn);
    } catch (e) {
      return fail(`${p.label} didn't confirm the sign-in (${String(e.message || e).slice(0, 120)}).`);
    }

    const existing = await one(db, "SELECT user_id FROM identities WHERE provider = ? AND provider_user_id = ?", name, prof.id);
    let userId;
    if (login.link_user_id) {
      if (existing && existing.user_id !== login.link_user_id) {
        return fail(`That ${p.label} account is already used by a different Mtrini account.`);
      }
      userId = login.link_user_id;
      if (!existing) {
        await run(db, `INSERT INTO identities (provider, provider_user_id, user_id, email, username, created_at)
          VALUES (?, ?, ?, ?, ?, ?)`, name, prof.id, userId, prof.email, prof.username, now);
      }
    } else if (existing) {
      userId = existing.user_id;
    } else {
      // A new sign-in is a new account; other sign-ins are linked explicitly, never by matching email.
      userId = random(16);
      await run(db, "INSERT INTO users (id, name, email, avatar, created_at) VALUES (?, ?, ?, ?, ?)",
        userId, prof.name, prof.email, prof.avatar, now);
      await run(db, `INSERT INTO identities (provider, provider_user_id, user_id, email, username, created_at)
        VALUES (?, ?, ?, ?, ?, ?)`, name, prof.id, userId, prof.email, prof.username, now);
    }

    // The session token is made only when the app collects it with its poll secret, so no usable
    // token is ever stored; until then the login just remembers which account signed in.
    const result = JSON.stringify(login.link_user_id ? { linked: name } : { user_id: userId });
    await run(db, "UPDATE logins SET status = 'done', result = ?, state = NULL, verifier = NULL WHERE id = ?", result, login.id);
    const done = login.link_user_id ? `${esc(p.label)} is now linked to your Mtrini account.` : `You're signed in${prof.name ? ` as ${esc(prof.name)}` : ""}.`;
    return page("Done", `<h1>${done}</h1><p>You can close this tab and go back to Mtrini Workspace.</p>`);
  }

  // 3. The app collects the result (once).
  if (method === "POST" && path === "/auth/device/poll") {
    const body = await request.json().catch(() => ({}));
    const login = await one(db, "SELECT * FROM logins WHERE id = ?", String(body.login_id || ""));
    if (!login || login.poll_hash !== await sha256(String(body.poll_secret || ""))) return err(404, "unknown_login", "Unknown sign-in.");
    if (login.status === "failed") {
      await run(db, "DELETE FROM logins WHERE id = ?", login.id);
      return json({ status: "failed", message: login.error || "Sign-in failed." });
    }
    if (login.status !== "done") {
      if (login.created_at + LOGIN_TTL < now) {
        await run(db, "DELETE FROM logins WHERE id = ?", login.id);
        return json({ status: "expired" });
      }
      return json({ status: "pending" });
    }
    const result = JSON.parse(login.result);
    await run(db, "DELETE FROM logins WHERE id = ?", login.id);  // one collection only
    if (result.linked) return json({ status: "linked", provider: result.linked });
    const deviceId = random(12);
    const token = random(32);
    await run(db, "INSERT INTO devices (id, user_id, name, platform, created_at, last_seen) VALUES (?, ?, ?, ?, ?, ?)",
      deviceId, result.user_id, login.device_name, login.platform, now, now);
    await run(db, "INSERT INTO sessions (token_hash, device_id, user_id, expires_at) VALUES (?, ?, ?, ?)",
      await sha256(token), deviceId, result.user_id, now + SESSION_TTL);
    return json({ status: "done", session_token: token, device_id: deviceId, ...(await profile(db, result.user_id, deviceId)) });
  }

  // Signed-in routes.
  const who = await authUser(request, db, now);
  if (!who) return err(401, "signed_out", "Sign in again.");

  if (method === "GET" && path === "/me") return json(await profile(db, who.userId, who.deviceId));

  if (method === "POST" && path === "/auth/logout") {
    await deleteDevice(db, who.deviceId);
    return json({ ok: true });
  }

  if (method === "POST" && (m = /^\/devices\/([\w-]+)\/revoke$/.exec(path))) {
    const d = await one(db, "SELECT id FROM devices WHERE id = ? AND user_id = ?", m[1], who.userId);
    if (!d) return err(404, "unknown_device", "Unknown device.");
    await deleteDevice(db, d.id);
    return json({ ok: true });
  }

  if (method === "DELETE" && (m = /^\/me\/identities\/(\w+)$/.exec(path))) {
    const ids = await all(db, "SELECT provider FROM identities WHERE user_id = ?", who.userId);
    if (ids.length <= 1) return err(400, "last_sign_in", "This is your only sign-in. Link another one first.");
    await run(db, "DELETE FROM identities WHERE user_id = ? AND provider = ?", who.userId, m[1]);
    return json(await profile(db, who.userId, who.deviceId));
  }

  if (method === "DELETE" && path === "/me") {
    for (const d of await all(db, "SELECT id FROM devices WHERE user_id = ?", who.userId)) await deleteDevice(db, d.id);
    await run(db, "DELETE FROM identities WHERE user_id = ?", who.userId);
    await run(db, "DELETE FROM logins WHERE link_user_id = ?", who.userId);
    await run(db, "DELETE FROM users WHERE id = ?", who.userId);
    return json({ ok: true, deleted: true });
  }

  return err(404, "not_found", "Not found.");
}
