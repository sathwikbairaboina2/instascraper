CREATE TABLE IF NOT EXISTS profiles (
  username        TEXT PRIMARY KEY,
  ig_user_id      TEXT,
  full_name       TEXT,
  biography       TEXT,
  is_private      INTEGER NOT NULL DEFAULT 0,
  post_count      INTEGER,
  avatar_path     TEXT,
  next_cursor     TEXT,
  tracked         INTEGER NOT NULL DEFAULT 0,
  last_synced_at  TEXT,
  created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS media_items (
  shortcode     TEXT PRIMARY KEY,
  username      TEXT NOT NULL REFERENCES profiles(username) ON DELETE CASCADE,
  kind          TEXT NOT NULL,
  taken_at      TEXT NOT NULL,
  caption       TEXT,
  is_video      INTEGER NOT NULL,
  child_count   INTEGER NOT NULL DEFAULT 1,
  full_status   TEXT NOT NULL DEFAULT 'none',
  full_error    TEXT,
  ig_url        TEXT NOT NULL,
  discovered_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_media_profile ON media_items(username, taken_at DESC);

CREATE TABLE IF NOT EXISTS media_files (
  id         INTEGER PRIMARY KEY,
  shortcode  TEXT NOT NULL REFERENCES media_items(shortcode) ON DELETE CASCADE,
  role       TEXT NOT NULL,
  child_idx  INTEGER NOT NULL DEFAULT 0,
  path       TEXT NOT NULL,
  mime       TEXT,
  bytes      INTEGER,
  width      INTEGER,
  height     INTEGER,
  UNIQUE(shortcode, role, child_idx)
);

CREATE TABLE IF NOT EXISTS jobs (
  id           INTEGER PRIMARY KEY,
  kind         TEXT NOT NULL,
  payload      TEXT NOT NULL,
  priority     INTEGER NOT NULL,
  status       TEXT NOT NULL,
  attempts     INTEGER NOT NULL DEFAULT 0,
  error        TEXT,
  created_at   TEXT NOT NULL,
  started_at   TEXT,
  finished_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_pickup ON jobs(status, priority, created_at);

CREATE TABLE IF NOT EXISTS activity_log (
  id      INTEGER PRIMARY KEY,
  ts      TEXT NOT NULL,
  action  TEXT NOT NULL,
  target  TEXT,
  detail  TEXT
);
CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity_log(ts DESC);
