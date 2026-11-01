import assert from "node:assert/strict";
import { test } from "node:test";

import { handle } from "../src/core.js";
import { makeD1 } from "../dev/d1.mjs";

// Accounts and devices are made directly in the database; sign-in itself is covered in core.test.mjs.
async function setup() {
  const db = makeD1();
  let clock = Date.UTC(2026, 10, 1, 12);
  const deps = { db, now: () => clock };
  const { sha256 } = await import("../src/core.js");
  async function account(id, devices) {
    db.raw.prepare("INSERT INTO users (id, name, created_at) VALUES (?, ?, 0)").run(id, id);
    const tokens = {};
    for (const d of devices) {
      db.raw.prepare("INSERT INTO devices (id, user_id, name, platform, created_at, last_seen) VALUES (?, ?, ?, '', 0, 0)").run(d, id, d);
      db.raw.prepare("INSERT INTO sessions (token_hash, device_id, user_id, expires_at) VALUES (?, ?, ?, ?)").run(await sha256(`t-${d}`), d, id, 2 ** 40);
      tokens[d] = `t-${d}`;
    }
    return tokens;
  }
  const call = async (method, path, token, body) => {
    const r = await handle(new Request("https://cloud.test" + path, {
      method, headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
      body: body === undefined ? undefined : JSON.stringify(body),
    }), {}, deps);
    return { status: r.status, body: await r.json() };
  };
  return { db, call, account, tick: (ms) => { clock += ms; } };
}

const thread = (title, msgs) => ({ title, created: 1, updated: 2, messages: msgs.map((c, i) => ({ role: i % 2 ? "assistant" : "user", content: c, ts: i })) });

test("a PC saves sessions; the phone lists what changed and opens one", async () => {
  const t = await setup();
  const k = await t.account("u1", ["pc", "phone"]);
  const put = await t.call("PUT", "/sync/threads/abc", k.pc, { thread: thread("Fix login", ["hi", "hello"]), workspace: "C:/shop", from_pc: true });
  assert.equal(put.status, 200);
  assert.equal(put.body.pc, "pc");
  const list = await t.call("GET", "/sync/threads?since=0", k.phone);
  assert.equal(list.body.threads.length, 1);
  assert.deepEqual({ ...list.body.threads[0], rev: 0 }, { id: "abc", pc: "pc", workspace: "C:/shop", title: "Fix login", preview: "hello",
    messages: 2, created: 1, updated: 2, rev: 0, deleted: false });
  const again = await t.call("GET", `/sync/threads?since=${list.body.rev}`, k.phone);
  assert.equal(again.body.threads.length, 0);
  const one = await t.call("GET", "/sync/threads/abc", k.phone);
  assert.equal(one.body.thread.messages[1].content, "hello");
});

test("a save based on an old copy is refused with the current one", async () => {
  const t = await setup();
  const k = await t.account("u1", ["pc", "phone"]);
  const a = await t.call("PUT", "/sync/threads/abc", k.pc, { thread: thread("T", ["one"]), from_pc: true });
  t.tick(5);
  const b = await t.call("PUT", "/sync/threads/abc", k.phone, { thread: thread("T", ["one", "two"]), base_rev: a.body.rev });
  assert.equal(b.status, 200);
  assert.ok(b.body.rev > a.body.rev);
  const stale = await t.call("PUT", "/sync/threads/abc", k.pc, { thread: thread("T", ["one", "pc"]), base_rev: a.body.rev });
  assert.equal(stale.status, 409);
  assert.equal(stale.body.rev, b.body.rev);
  assert.equal(stale.body.thread.messages.length, 2);
});

test("revs keep growing within the same millisecond, and deleted sessions show up as deleted", async () => {
  const t = await setup();
  const k = await t.account("u1", ["pc"]);
  const a = await t.call("PUT", "/sync/threads/a", k.pc, { thread: thread("A", ["x"]), from_pc: true });
  const b = await t.call("PUT", "/sync/threads/b", k.pc, { thread: thread("B", ["x"]), from_pc: true });
  assert.ok(b.body.rev > a.body.rev);
  await t.call("DELETE", "/sync/threads/a", k.pc);
  const list = await t.call("GET", `/sync/threads?since=${b.body.rev}`, k.pc);
  assert.deepEqual(list.body.threads.map((x) => [x.id, x.deleted]), [["a", true]]);
  assert.equal((await t.call("GET", "/sync/threads/a", k.pc)).status, 404);
});

test("accounts never see each other's sessions or PCs", async () => {
  const t = await setup();
  const a = await t.account("u1", ["pc"]);
  const b = await t.account("u2", ["other"]);
  await t.call("PUT", "/sync/threads/abc", a.pc, { thread: thread("Mine", ["secret"]), from_pc: true });
  assert.equal((await t.call("GET", "/sync/threads?since=0", b.other)).body.threads.length, 0);
  assert.equal((await t.call("GET", "/sync/threads/abc", b.other)).status, 404);
  const q = await t.call("POST", "/sync/tasks", b.other, { pc: "pc", thread_id: "abc", workspace: "C:/x", prompt: "rm -rf" });
  assert.equal(q.body.error.code, "unknown_pc");
  // the same id in another account is a separate session
  await t.call("PUT", "/sync/threads/abc", b.other, { thread: thread("Theirs", ["x"]), from_pc: true });
  assert.equal((await t.call("GET", "/sync/threads/abc", a.pc)).body.title, "Mine");
});

test("the phone queues work for the PC; only that PC picks it up and reports back", async () => {
  const t = await setup();
  const k = await t.account("u1", ["pc", "pc2", "phone"]);
  const q = await t.call("POST", "/sync/tasks", k.phone, { pc: "pc", thread_id: "abc", workspace: "C:/shop", prompt: "add tests", mode: "auto" });
  assert.equal(q.status, 200);
  assert.equal(q.body.task.mode, "auto");
  assert.equal((await t.call("GET", "/sync/tasks?pc=me", k.pc2)).body.tasks.length, 0);
  const mine = await t.call("GET", "/sync/tasks?pc=me", k.pc);
  assert.equal(mine.body.tasks[0].prompt, "add tests");
  const id = mine.body.tasks[0].id;
  assert.equal((await t.call("POST", `/sync/tasks/${id}`, k.phone, { status: "done" })).status, 403);
  await t.call("POST", `/sync/tasks/${id}`, k.pc, { status: "running" });
  assert.equal((await t.call("DELETE", `/sync/tasks/${id}`, k.phone)).status, 409);
  await t.call("POST", `/sync/tasks/${id}`, k.pc, { status: "done" });
  assert.equal((await t.call("GET", "/sync/tasks", k.phone)).body.tasks[0].status, "done");
  assert.equal((await t.call("GET", "/sync/tasks?pc=me", k.pc)).body.tasks.length, 0);
});

test("mail: claim a name, send, read, reply in the same conversation", async () => {
  const t = await setup();
  const a = await t.account("u1", ["a"]);
  const b = await t.account("u2", ["b"]);
  assert.equal((await t.call("GET", "/mail?box=inbox", a.a)).body.error.code, "no_name");
  assert.equal((await t.call("POST", "/mail/name", a.a, { name: "Ayham" })).body.name, "ayham");
  assert.equal((await t.call("POST", "/mail/name", b.b, { name: "ayham" })).body.error.code, "taken");
  assert.equal((await t.call("POST", "/mail/name", b.b, { name: "support" })).body.error.code, "reserved");
  assert.equal((await t.call("POST", "/mail/name", b.b, { name: "-x" })).body.error.code, "bad_name");
  await t.call("POST", "/mail/name", b.b, { name: "sara" });
  assert.equal((await t.call("POST", "/mail/name", b.b, { name: "sara2" })).body.error.code, "has_name");

  const bad = await t.call("POST", "/mail/send", a.a, { to: "sara, nobody", subject: "Hi", body: "x" });
  assert.deepEqual(bad.body.unknown, ["nobody"]);
  const sent = await t.call("POST", "/mail/send", a.a, { to: "sara@mtrini", subject: "Hi", body: "Want to test the app?" });
  assert.equal(sent.status, 200);
  assert.equal((await t.call("GET", "/mail/me", b.b)).body.unread, 1);
  const inbox = await t.call("GET", "/mail?box=inbox", b.b);
  assert.equal(inbox.body.messages[0].from, "ayham");
  assert.equal(inbox.body.messages[0].snippet, "Want to test the app?");
  const open = await t.call("GET", `/mail/${inbox.body.messages[0].id}`, b.b);
  assert.equal(open.body.message.body, "Want to test the app?");
  assert.equal((await t.call("GET", "/mail/me", b.b)).body.unread, 0);
  // the sender's copy isn't the recipient's: ids don't cross accounts
  assert.equal((await t.call("GET", `/mail/${sent.body.message.id}`, b.b)).status, 404);

  await t.call("POST", "/mail/send", b.b, { to: ["ayham"], subject: "Re: Hi", body: "Yes!", reply_to: inbox.body.messages[0].id });
  const conv = await t.call("GET", `/mail/${sent.body.message.id}`, a.a);
  assert.deepEqual(conv.body.conversation.map((m) => m.body), ["Want to test the app?", "Yes!"]);
  const found = await t.call("GET", "/mail?box=inbox&q=yes", a.a);
  assert.equal(found.body.messages.length, 1);
  assert.equal((await t.call("GET", "/mail?box=inbox&q=%25", a.a)).body.messages.length, 0); // % is literal
});

test("mail: star, archive, trash then delete for good; blocked senders never arrive", async () => {
  const t = await setup();
  const a = await t.account("u1", ["a"]);
  const b = await t.account("u2", ["b"]);
  await t.call("POST", "/mail/name", a.a, { name: "ayham" });
  await t.call("POST", "/mail/name", b.b, { name: "spammer" });
  await t.call("POST", "/mail/send", b.b, { to: "ayham", subject: "1", body: "one" });
  const id = (await t.call("GET", "/mail?box=inbox", a.a)).body.messages[0].id;
  await t.call("POST", `/mail/${id}`, a.a, { starred: true });
  assert.equal((await t.call("GET", "/mail?box=starred", a.a)).body.messages.length, 1);
  await t.call("POST", `/mail/${id}`, a.a, { box: "archive" });
  assert.equal((await t.call("GET", "/mail?box=inbox", a.a)).body.messages.length, 0);
  assert.equal((await t.call("DELETE", `/mail/${id}`, a.a)).body.deleted, false);
  assert.equal((await t.call("GET", "/mail?box=trash", a.a)).body.messages.length, 1);
  assert.equal((await t.call("DELETE", `/mail/${id}`, a.a)).body.deleted, true);
  assert.equal((await t.call("GET", `/mail/${id}`, a.a)).status, 404);

  await t.call("POST", "/mail/blocks", a.a, { name: "spammer" });
  const s = await t.call("POST", "/mail/send", b.b, { to: "ayham", subject: "2", body: "two" });
  assert.equal(s.status, 200); // the sender can't tell
  assert.equal((await t.call("GET", "/mail?box=inbox", a.a)).body.messages.length, 0);
  assert.deepEqual((await t.call("GET", "/mail/blocks", a.a)).body.blocked, ["spammer"]);
});

test("deleting an account removes its sessions, tasks, mail and name", async () => {
  const t = await setup();
  const a = await t.account("u1", ["pc"]);
  await t.call("POST", "/mail/name", a.pc, { name: "ayham" });
  await t.call("POST", "/mail/send", a.pc, { to: "ayham", subject: "note", body: "to self" });
  await t.call("PUT", "/sync/threads/x", a.pc, { thread: thread("T", ["x"]), from_pc: true });
  await t.call("POST", "/sync/tasks", a.pc, { pc: "pc", thread_id: "x", workspace: "C:/x", prompt: "go" });
  assert.equal((await t.call("DELETE", "/me", a.pc)).status, 200);
  for (const table of ["threads", "tasks", "mail", "mail_names"]) {
    assert.equal(t.db.raw.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get().n, 0, table);
  }
});
