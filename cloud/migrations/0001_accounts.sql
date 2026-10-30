-- Mtrini Cloud accounts. Tokens and poll secrets are stored only as SHA-256 hashes.
CREATE TABLE users (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '',
  avatar TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL
);

-- One row per linked sign-in (Google, Discord, GitHub). A sign-in belongs to exactly one account.
CREATE TABLE identities (
  provider TEXT NOT NULL,
  provider_user_id TEXT NOT NULL,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  email TEXT NOT NULL DEFAULT '',
  username TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  PRIMARY KEY (provider, provider_user_id)
);
CREATE INDEX identities_user ON identities(user_id);

CREATE TABLE devices (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL DEFAULT '',
  platform TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  last_seen INTEGER NOT NULL
);
CREATE INDEX devices_user ON devices(user_id);

CREATE TABLE sessions (
  token_hash TEXT PRIMARY KEY,
  device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at INTEGER NOT NULL
);
CREATE INDEX sessions_device ON sessions(device_id);

-- A sign-in in progress: made by the app, finished in the browser, collected by the app's polling.
CREATE TABLE logins (
  id TEXT PRIMARY KEY,
  poll_hash TEXT NOT NULL,
  device_name TEXT NOT NULL DEFAULT '',
  platform TEXT NOT NULL DEFAULT '',
  link_user_id TEXT,            -- set when a signed-in app links another sign-in to its account
  provider TEXT,
  state TEXT,
  verifier TEXT,
  status TEXT NOT NULL DEFAULT 'pending',  -- pending | done | failed
  error TEXT,
  result TEXT,                  -- which account signed in (no token: the app gets one when it polls)
  created_at INTEGER NOT NULL
);
CREATE INDEX logins_state ON logins(state);
