-- Cloud sync: every session saved on a signed-in PC (and chats started on the phone), readable from any device.
CREATE TABLE threads (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  id TEXT NOT NULL,
  device_id TEXT NOT NULL DEFAULT '',   -- the PC the session belongs to ('' for a chat not tied to a PC)
  workspace TEXT NOT NULL DEFAULT '',   -- the project folder on that PC
  title TEXT NOT NULL DEFAULT '',
  preview TEXT NOT NULL DEFAULT '',
  messages INTEGER NOT NULL DEFAULT 0,
  created INTEGER NOT NULL DEFAULT 0,
  updated INTEGER NOT NULL DEFAULT 0,   -- when the session last changed (seconds, client clock)
  rev INTEGER NOT NULL,                 -- server change counter: list ?since=rev, and PUT base_rev to catch conflicts
  deleted INTEGER NOT NULL DEFAULT 0,
  data TEXT NOT NULL DEFAULT '{}',      -- the session itself (title, messages, ...)
  PRIMARY KEY (user_id, id)
);
CREATE INDEX threads_rev ON threads(user_id, rev);

-- Work sent from the phone while the PC is offline; the PC runs it when it reconnects.
CREATE TABLE tasks (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  device_id TEXT NOT NULL,              -- the PC that should run it
  from_device TEXT NOT NULL,            -- the phone that sent it (the PC checks the phone's seal)
  thread_id TEXT NOT NULL,
  workspace TEXT NOT NULL,
  prompt TEXT NOT NULL,                 -- sealed by the phone for that PC (remote_crypto); the PC refuses anything else
  mode TEXT NOT NULL DEFAULT 'ask',
  provider TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'queued', -- queued | running | waiting (for your OK) | done | failed | cancelled
  error TEXT NOT NULL DEFAULT '',
  created INTEGER NOT NULL,
  updated INTEGER NOT NULL
);
CREATE INDEX tasks_device ON tasks(device_id, status);
CREATE INDEX tasks_user ON tasks(user_id, created);

-- Mtrini Mail: mail between Mtrini accounts (no outside email). Each account claims one name.
CREATE TABLE mail_names (
  name TEXT PRIMARY KEY,
  user_id TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  created INTEGER NOT NULL
);

-- One row per mailbox copy: the sender's copy lives in 'sent', each recipient's in 'inbox'.
CREATE TABLE mail (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  box TEXT NOT NULL,                    -- inbox | sent | archive | trash
  conv TEXT NOT NULL,                   -- shared by a message, its copies and its replies
  sender TEXT NOT NULL,
  recipients TEXT NOT NULL,             -- JSON array of names
  subject TEXT NOT NULL DEFAULT '',
  body TEXT NOT NULL DEFAULT '',
  unread INTEGER NOT NULL DEFAULT 0,
  starred INTEGER NOT NULL DEFAULT 0,
  created INTEGER NOT NULL
);
CREATE INDEX mail_box ON mail(owner_id, box, created);
CREATE INDEX mail_conv ON mail(owner_id, conv);

CREATE TABLE mail_blocks (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  PRIMARY KEY (user_id, name)
);
