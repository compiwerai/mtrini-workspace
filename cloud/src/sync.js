// Cloud sync: sessions saved to Mtrini Cloud so they open on any device, even when the PC is off,
// and tasks queued from the phone that the PC runs when it's back.
//
//   GET    /sync/threads?since=REV      changed sessions (metadata only) and the newest rev
//   GET    /sync/threads/:id            one session with its messages
//   PUT    /sync/threads/:id            save {thread, workspace?, pc?, base_rev?}; 409 + current copy on conflict
//   DELETE /sync/threads/:id            remove from the cloud (the PC keeps its own copy)
//   POST   /sync/tasks                  queue {pc, thread_id, workspace, prompt (sealed for that PC), mode?}
//   GET    /sync/tasks?pc=me            queued tasks for this PC; without pc: this account's recent tasks
//   POST   /sync/tasks/:id              the PC reports {status, error?}
//   DELETE /sync/tasks/:id              cancel a task that hasn't started
//
// `rev` grows with every change in the account, so a device asks only for what changed since it last looked.
// A task's prompt is sealed by the phone with its pairing key for that PC, so the cloud can queue work but
// can't write or change it: the PC runs only tasks it can open (backend/mtrini/remote.py: open_task).

import { all, body, err, json, one, run } from "./http.js";

export const MAX_THREAD = 1_500_000; // characters of JSON per session
const MAX_PROMPT = 60_000; // the sealed message, so a bit more than the text
const MAX_QUEUED = 50;
const MODES = new Set(["ask", "auto", "readonly", "plan"]);
const ID = /^[\w-]{1,64}$/;

const meta = (r) => ({ id: r.id, pc: r.device_id, workspace: r.workspace, title: r.title, preview: r.preview,
  messages: r.messages, created: r.created, updated: r.updated, rev: r.rev, deleted: Boolean(r.deleted) });

function summary(thread) {
  const msgs = Array.isArray(thread.messages) ? thread.messages : [];
  const last = [...msgs].reverse().find((m) => (m.role === "user" || m.role === "assistant") && typeof m.content === "string");
  return { title: String(thread.title || "Untitled").slice(0, 200), preview: last ? last.content.slice(0, 160) : "",
    messages: msgs.length, created: Number(thread.created) || 0, updated: Number(thread.updated) || 0 };
}

const NEXT_REV = "MAX(?, COALESCE((SELECT MAX(rev) FROM threads WHERE user_id = ?), 0) + 1)";

export async function route(method, path, url, request, db, who, nowMs) {
  const now = Math.floor(nowMs / 1000);
  let m;

  if (method === "GET" && path === "/sync/threads") {
    const since = Number(url.searchParams.get("since")) || 0;
    const rows = await all(db, `SELECT id, device_id, workspace, title, preview, messages, created, updated, rev, deleted
      FROM threads WHERE user_id = ? AND rev > ? ORDER BY rev LIMIT 500`, who.userId, since);
    const top = await one(db, "SELECT MAX(rev) AS rev FROM threads WHERE user_id = ?", who.userId);
    return json({ threads: rows.map(meta), rev: (rows.length === 500 ? rows.at(-1).rev : top?.rev) || since, more: rows.length === 500 });
  }

  if ((m = /^\/sync\/threads\/([\w-]+)$/.exec(path))) {
    const id = m[1];
    if (!ID.test(id)) return err(400, "bad_id", "Bad session id.");
    const cur = await one(db, "SELECT * FROM threads WHERE user_id = ? AND id = ?", who.userId, id);

    if (method === "GET") {
      if (!cur || cur.deleted) return err(404, "not_found", "That session isn't in the cloud.");
      return json({ ...meta(cur), thread: JSON.parse(cur.data) });
    }

    if (method === "PUT") {
      const raw = await request.text();
      if (raw.length > MAX_THREAD + 4096) return err(413, "too_large", "This session is too big to save to the cloud.");
      let b;
      try { b = JSON.parse(raw); } catch { return err(400, "bad_json", "Send JSON."); }
      const thread = b.thread;
      if (!thread || typeof thread !== "object" || !Array.isArray(thread.messages)) return err(400, "bad_thread", "Send {thread: {messages: [...]}}.");
      if (cur && !cur.deleted && b.base_rev !== undefined && Number(b.base_rev) !== cur.rev) {
        return err(409, "conflict", "This session changed on another device.", { rev: cur.rev, thread: JSON.parse(cur.data) });
      }
      // a session stays with the PC it came from; a new one belongs to the PC that saved it, or the one named
      let pc = cur?.device_id || "";
      if (!cur) {
        if (b.pc) {
          const d = await one(db, "SELECT id FROM devices WHERE id = ? AND user_id = ?", String(b.pc), who.userId);
          if (!d) return err(400, "unknown_pc", "That PC isn't on your account.");
          pc = d.id;
        } else if (b.from_pc) {
          pc = who.deviceId;
        }
      }
      const s = summary({ ...thread, updated: thread.updated || now });
      const data = JSON.stringify({ ...thread, id });
      if (data.length > MAX_THREAD) return err(413, "too_large", "This session is too big to save to the cloud.");
      await run(db, `INSERT INTO threads (user_id, id, device_id, workspace, title, preview, messages, created, updated, rev, deleted, data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ${NEXT_REV}, 0, ?)
        ON CONFLICT (user_id, id) DO UPDATE SET workspace = excluded.workspace, title = excluded.title, preview = excluded.preview,
          messages = excluded.messages, updated = excluded.updated, rev = excluded.rev, deleted = 0, data = excluded.data`,
        who.userId, id, pc, String(b.workspace ?? thread.workspace ?? cur?.workspace ?? "").slice(0, 500), s.title, s.preview,
        s.messages, s.created || now, s.updated, nowMs, who.userId, data);
      const saved = await one(db, "SELECT rev FROM threads WHERE user_id = ? AND id = ?", who.userId, id);
      return json({ ok: true, rev: saved.rev, pc });
    }

    if (method === "DELETE") {
      if (cur && !cur.deleted) {
        await run(db, `UPDATE threads SET deleted = 1, data = '{}', preview = '', rev = ${NEXT_REV} WHERE user_id = ? AND id = ?`,
          nowMs, who.userId, who.userId, id);
      }
      return json({ ok: true });
    }
  }

  if (method === "POST" && path === "/sync/tasks") {
    const b = await body(request);
    const prompt = String(b.prompt || "").trim();
    if (!prompt) return err(400, "empty", "Write what the PC should do.");
    if (prompt.length > MAX_PROMPT) return err(413, "too_large", "That message is too long.");
    if (!ID.test(String(b.thread_id || ""))) return err(400, "bad_id", "Bad session id.");
    const pc = await one(db, "SELECT id FROM devices WHERE id = ? AND user_id = ?", String(b.pc || ""), who.userId);
    if (!pc) return err(400, "unknown_pc", "That PC isn't on your account.");
    const n = await one(db, "SELECT COUNT(*) AS n FROM tasks WHERE device_id = ? AND status = 'queued'", pc.id);
    if (n.n >= MAX_QUEUED) return err(429, "too_many", "That PC already has a lot of queued work. Wait for it to catch up.");
    const id = crypto.randomUUID().replace(/-/g, "").slice(0, 16);
    await run(db, `INSERT INTO tasks (id, user_id, device_id, from_device, thread_id, workspace, prompt, mode, provider, model, status, created, updated)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)`, id, who.userId, pc.id, who.deviceId, b.thread_id, String(b.workspace || "").slice(0, 500),
      prompt, MODES.has(b.mode) ? b.mode : "ask", String(b.provider || "").slice(0, 60), String(b.model || "").slice(0, 200), now, now);
    return json({ ok: true, task: await one(db, "SELECT * FROM tasks WHERE id = ?", id) });
  }

  if (method === "GET" && path === "/sync/tasks") {
    if (url.searchParams.get("pc") === "me") {
      return json({ tasks: await all(db, "SELECT * FROM tasks WHERE device_id = ? AND status = 'queued' ORDER BY created LIMIT 20", who.deviceId) });
    }
    return json({ tasks: await all(db, "SELECT * FROM tasks WHERE user_id = ? ORDER BY created DESC LIMIT 50", who.userId) });
  }

  if ((m = /^\/sync\/tasks\/(\w+)$/.exec(path))) {
    const t = await one(db, "SELECT * FROM tasks WHERE id = ? AND user_id = ?", m[1], who.userId);
    if (!t) return err(404, "not_found", "Unknown task.");
    if (method === "POST") {
      if (t.device_id !== who.deviceId) return err(403, "not_yours", "Only the PC running this task can update it.");
      const b = await body(request);
      if (!["running", "waiting", "done", "failed"].includes(b.status)) return err(400, "bad_status", "Unknown status.");
      await run(db, "UPDATE tasks SET status = ?, error = ?, updated = ? WHERE id = ?", b.status, String(b.error || "").slice(0, 500), now, t.id);
      return json({ ok: true });
    }
    if (method === "DELETE") {
      if (t.status !== "queued") return err(409, "started", "That task already started.");
      await run(db, "UPDATE tasks SET status = 'cancelled', updated = ? WHERE id = ?", now, t.id);
      return json({ ok: true });
    }
  }

  return null;
}
