-- Device credentials are source-scoped; raw credentials and enrollment secrets never enter D1.
CREATE TABLE IF NOT EXISTS device_enrollment_requests (
  request_id TEXT PRIMARY KEY,
  user_code TEXT NOT NULL UNIQUE,
  request_secret_hash TEXT NOT NULL,
  credential_hash TEXT NOT NULL UNIQUE,
  source_ids TEXT NOT NULL,
  machine TEXT NOT NULL,
  os_user TEXT NOT NULL,
  platform TEXT NOT NULL CHECK(platform IN ('linux','darwin')),
  read_requested INTEGER NOT NULL CHECK(read_requested IN (0,1)),
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','denied')),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS device_enrollment_expiry ON device_enrollment_requests(expires_at);
CREATE TABLE IF NOT EXISTS device_credentials (
  credential_hash TEXT PRIMARY KEY,
  request_id TEXT NOT NULL UNIQUE,
  source_ids TEXT NOT NULL,
  read_allowed INTEGER NOT NULL CHECK(read_allowed IN (0,1)),
  approved_at TEXT NOT NULL,
  revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS device_enrollment_budget (
  hour TEXT PRIMARY KEY,
  count INTEGER NOT NULL CHECK(count BETWEEN 0 AND 32)
);
