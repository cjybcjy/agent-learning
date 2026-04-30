CREATE TABLE IF NOT EXISTS raw_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT NOT NULL,
  channel TEXT NOT NULL,
  author_id TEXT,
  content TEXT NOT NULL,
  posted_at TEXT NOT NULL,   -- ISO8601 UTC
  fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_posted_at ON raw_messages(posted_at);

CREATE TABLE IF NOT EXISTS mentions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  matched_alias TEXT NOT NULL,
  is_ambiguous INTEGER NOT NULL,
  confidence REAL NOT NULL DEFAULT 1.0,
  FOREIGN KEY (message_id) REFERENCES raw_messages(id)
);
CREATE INDEX IF NOT EXISTS idx_mentions_symbol ON mentions(symbol);

CREATE TABLE IF NOT EXISTS daily_scores (
  symbol TEXT NOT NULL,
  date TEXT NOT NULL,        -- YYYY-MM-DD UTC
  mention_count INTEGER NOT NULL,
  weighted_score REAL NOT NULL,
  alpha REAL,
  beta REAL,
  composite REAL,
  PRIMARY KEY (symbol, date)
);
