CREATE TABLE IF NOT EXISTS replies (
  comment_id TEXT PRIMARY KEY,
  igsid TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
