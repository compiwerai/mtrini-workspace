// Mtrini Mail: mail between Mtrini accounts. There is no outside email: addresses are Mtrini names.
//
//   GET    /mail/me                    your name (or null) and unread count
//   POST   /mail/name                  claim your name {name} (once)
//   GET    /mail?box=inbox&q=&before=  a page of messages (inbox | sent | archive | trash | starred)
//   GET    /mail/:id                   one message, marked read; with its conversation
//   POST   /mail/send                  {to, subject, body, reply_to?}
//   POST   /mail/:id                   change {unread?, starred?, box?}
//   DELETE /mail/:id                   to the trash; from the trash, gone for good
//   GET    /mail/blocks, POST /mail/blocks {name, blocked}   names whose mail you never receive

import { all, body, err, json, one, run } from "./http.js";

export const NAME = /^[a-z0-9](?:[a-z0-9._-]{1,28}[a-z0-9])?$/;
const RESERVED = new Set(["admin", "administrator", "support", "help", "mtrini", "compiwer", "compiwerai", "postmaster",
  "abuse", "noreply", "no-reply", "root", "security", "team", "official", "staff", "mod", "moderator", "system", "billing"]);
const BOXES = new Set(["inbox", "sent", "archive", "trash"]);
const MAX_TO = 20;
const MAX_BODY = 50_000;
const MAX_SUBJECT = 200;
const DAILY_SENDS = 100;
const PAGE = 50;

const newId = () => crypto.randomUUID().replace(/-/g, "");
const row = (r, full = false) => ({
  id: r.id, box: r.box, conv: r.conv, from: r.sender, to: JSON.parse(r.recipients), subject: r.subject,
  ...(full ? { body: r.body } : { snippet: r.body.replace(/\s+/g, " ").slice(0, 140) }),
  unread: Boolean(r.unread), starred: Boolean(r.starred), created: r.created,
});

export function parseNames(to) {
  const list = Array.isArray(to) ? to : String(to || "").split(/[\s,;]+/);
  return [...new Set(list.map((s) => String(s).trim().toLowerCase().replace(/@mtrini$/, "")).filter(Boolean))];
}

export async function route(method, path, url, request, db, who, nowMs) {
  const now = Math.floor(nowMs / 1000);
  const mine = await one(db, "SELECT name FROM mail_names WHERE user_id = ?", who.userId);
  let m;

  if (method === "GET" && path === "/mail/me") {
    const u = await one(db, "SELECT COUNT(*) AS n FROM mail WHERE owner_id = ? AND box = 'inbox' AND unread = 1", who.userId);
    return json({ name: mine ? mine.name : null, unread: u.n });
  }

  if (method === "POST" && path === "/mail/name") {
    if (mine) return err(409, "has_name", `You already have the name ${mine.name}.`);
    const name = String((await body(request)).name || "").trim().toLowerCase();
    if (!NAME.test(name)) return err(400, "bad_name", "Use 3 to 30 letters, numbers, dots, dashes or underscores, starting and ending with a letter or number.");
    if (RESERVED.has(name)) return err(400, "reserved", "That name is reserved. Pick another.");
    if (await one(db, "SELECT name FROM mail_names WHERE name = ?", name)) return err(409, "taken", "That name is taken. Pick another.");
    await run(db, "INSERT INTO mail_names (name, user_id, created) VALUES (?, ?, ?)", name, who.userId, now);
    return json({ name, unread: 0 });
  }

  if (!path.startsWith("/mail")) return null;
  if (!mine) return err(403, "no_name", "Pick your Mtrini Mail name first.");

  if (method === "GET" && path === "/mail") {
    const box = url.searchParams.get("box") || "inbox";
    const q = (url.searchParams.get("q") || "").trim().slice(0, 100);
    const before = Number(url.searchParams.get("before")) || 2 ** 52;
    const where = ["owner_id = ?", "created < ?"];
    const args = [who.userId, before];
    if (box === "starred") where.push("starred = 1 AND box != 'trash'");
    else if (BOXES.has(box)) { where.push("box = ?"); args.push(box); }
    else return err(400, "bad_box", "Unknown folder.");
    if (q) {
      where.push("(subject LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\' OR sender LIKE ? ESCAPE '\\' OR recipients LIKE ? ESCAPE '\\')");
      const like = `%${q.replace(/[\\%_]/g, (c) => "\\" + c)}%`;
      args.push(like, like, like, like);
    }
    const rows = await all(db, `SELECT * FROM mail WHERE ${where.join(" AND ")} ORDER BY created DESC, rowid DESC LIMIT ${PAGE}`, ...args);
    return json({ messages: rows.map((r) => row(r)), more: rows.length === PAGE });
  }

  if (method === "POST" && path === "/mail/send") {
    const b = await body(request);
    const to = parseNames(b.to);
    const subject = String(b.subject || "").trim().slice(0, MAX_SUBJECT);
    const text = String(b.body || "");
    if (!to.length) return err(400, "no_recipients", "Add at least one Mtrini name to send to.");
    if (to.length > MAX_TO) return err(400, "too_many", `Send to at most ${MAX_TO} people at once.`);
    if (!text.trim() && !subject) return err(400, "empty", "Write something first.");
    if (text.length > MAX_BODY) return err(413, "too_large", "That message is too long.");
    const sent = await one(db, "SELECT COUNT(*) AS n FROM mail WHERE owner_id = ? AND box IN ('sent','archive','trash') AND sender = ? AND created > ?",
      who.userId, mine.name, now - 86400);
    if (sent.n >= DAILY_SENDS) return err(429, "daily_limit", "You've sent a lot of mail today. Try again tomorrow.");
    const found = await all(db, `SELECT name, user_id FROM mail_names WHERE name IN (${to.map(() => "?").join(",")})`, ...to);
    const unknown = to.filter((n) => !found.some((f) => f.name === n));
    if (unknown.length) return err(400, "unknown_names", `No Mtrini Mail user named ${unknown.join(", ")}.`, { unknown });
    let conv = newId();
    if (b.reply_to) {
      const orig = await one(db, "SELECT conv FROM mail WHERE id = ? AND owner_id = ?", String(b.reply_to), who.userId);
      if (orig) conv = orig.conv;
    }
    const recipients = JSON.stringify(to);
    const mineId = newId();
    await run(db, `INSERT INTO mail (id, owner_id, box, conv, sender, recipients, subject, body, unread, starred, created)
      VALUES (?, ?, 'sent', ?, ?, ?, ?, ?, 0, 0, ?)`, mineId, who.userId, conv, mine.name, recipients, subject, text, now);
    for (const f of found) {
      const blocked = await one(db, "SELECT 1 AS b FROM mail_blocks WHERE user_id = ? AND name = ?", f.user_id, mine.name);
      if (blocked) continue; // dropped quietly, so a blocked sender can't tell
      await run(db, `INSERT INTO mail (id, owner_id, box, conv, sender, recipients, subject, body, unread, starred, created)
        VALUES (?, ?, 'inbox', ?, ?, ?, ?, ?, 1, 0, ?)`, newId(), f.user_id, conv, mine.name, recipients, subject, text, now);
    }
    return json({ ok: true, message: row(await one(db, "SELECT * FROM mail WHERE id = ?", mineId), true) });
  }

  if (path === "/mail/blocks") {
    if (method === "GET") return json({ blocked: (await all(db, "SELECT name FROM mail_blocks WHERE user_id = ? ORDER BY name", who.userId)).map((r) => r.name) });
    if (method === "POST") {
      const b = await body(request);
      const name = parseNames([b.name])[0] || "";
      if (!NAME.test(name)) return err(400, "bad_name", "Unknown name.");
      if (b.blocked === false) await run(db, "DELETE FROM mail_blocks WHERE user_id = ? AND name = ?", who.userId, name);
      else await run(db, "INSERT OR IGNORE INTO mail_blocks (user_id, name) VALUES (?, ?)", who.userId, name);
      return json({ ok: true });
    }
  }

  if ((m = /^\/mail\/(\w+)$/.exec(path))) {
    const msg = await one(db, "SELECT * FROM mail WHERE id = ? AND owner_id = ?", m[1], who.userId);
    if (!msg) return err(404, "not_found", "That message isn't in your mail.");

    if (method === "GET") {
      if (msg.unread) await run(db, "UPDATE mail SET unread = 0 WHERE id = ?", msg.id);
      const conv = await all(db, "SELECT * FROM mail WHERE owner_id = ? AND conv = ? AND box != 'trash' ORDER BY created, rowid", who.userId, msg.conv);
      return json({ message: row({ ...msg, unread: 0 }, true), conversation: conv.map((r) => row(r, true)) });
    }
    if (method === "POST") {
      const b = await body(request);
      if (b.box !== undefined && !BOXES.has(b.box)) return err(400, "bad_box", "Unknown folder.");
      if (b.box === "sent" && msg.sender !== mine.name) return err(400, "bad_box", "Only mail you sent goes in Sent.");
      if (b.box === "inbox" && msg.sender === mine.name && msg.box === "sent") return err(400, "bad_box", "Sent mail stays in Sent.");
      await run(db, "UPDATE mail SET unread = ?, starred = ?, box = ? WHERE id = ?",
        b.unread === undefined ? msg.unread : b.unread ? 1 : 0, b.starred === undefined ? msg.starred : b.starred ? 1 : 0,
        b.box || msg.box, msg.id);
      return json({ ok: true, message: row(await one(db, "SELECT * FROM mail WHERE id = ?", msg.id)) });
    }
    if (method === "DELETE") {
      if (msg.box === "trash") await run(db, "DELETE FROM mail WHERE id = ?", msg.id);
      else await run(db, "UPDATE mail SET box = 'trash' WHERE id = ?", msg.id);
      return json({ ok: true, deleted: msg.box === "trash" });
    }
  }

  return err(404, "not_found", "Not found.");
}
