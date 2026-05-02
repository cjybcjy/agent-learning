PRAGMA journal_mode=WAL;

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
CREATE INDEX IF NOT EXISTS idx_raw_platform ON raw_messages(platform);

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
CREATE INDEX IF NOT EXISTS idx_mentions_message ON mentions(message_id);

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

CREATE TABLE IF NOT EXISTS rollup_30min (
  symbol TEXT NOT NULL,
  window_start TEXT NOT NULL,
  market TEXT NOT NULL,
  mention_count INTEGER NOT NULL,
  weighted_score REAL NOT NULL,
  source_count INTEGER NOT NULL,
  PRIMARY KEY (symbol, window_start)
);
CREATE INDEX IF NOT EXISTS idx_rollup_30min_symbol ON rollup_30min(symbol);
CREATE INDEX IF NOT EXISTS idx_rollup30_market_window ON rollup_30min(market, window_start);

CREATE TABLE IF NOT EXISTS rollup_4h (
  symbol TEXT NOT NULL,
  window_start TEXT NOT NULL,
  market TEXT NOT NULL,
  mention_count INTEGER NOT NULL,
  weighted_score REAL NOT NULL,
  source_count INTEGER NOT NULL,
  PRIMARY KEY (symbol, window_start)
);
CREATE INDEX IF NOT EXISTS idx_rollup_4h_symbol ON rollup_4h(symbol);
CREATE INDEX IF NOT EXISTS idx_rollup4h_market_window ON rollup_4h(market, window_start);

CREATE TABLE IF NOT EXISTS rollup_daily (
  symbol TEXT NOT NULL,
  date TEXT NOT NULL,
  market TEXT NOT NULL,
  mention_count INTEGER NOT NULL,
  weighted_score REAL NOT NULL,
  source_count INTEGER NOT NULL,
  alpha REAL,
  beta REAL,
  composite REAL,
  PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_rollup_daily_symbol ON rollup_daily(symbol);
CREATE INDEX IF NOT EXISTS idx_rollup_daily_date ON rollup_daily(date);

CREATE TABLE IF NOT EXISTS ai_signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  window_start TEXT NOT NULL,
  model_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  anomaly_score REAL,
  sentiment_shift REAL,
  sentiment_confidence REAL,
  key_driver TEXT,
  key_driver_confidence REAL,
  driver_keywords TEXT,
  raw_analysis TEXT,
  pe_ratio REAL,
  pb_ratio REAL,
  roe_ttm REAL,
  dividend_yield REAL
);
CREATE INDEX IF NOT EXISTS idx_ai_signals_symbol ON ai_signals(symbol);
CREATE INDEX IF NOT EXISTS idx_ai_signals_window ON ai_signals(window_start);

CREATE TABLE IF NOT EXISTS ai_call_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  window_start TEXT NOT NULL,
  model_version TEXT NOT NULL,
  called_at TEXT NOT NULL,
  cost_estimate REAL
);
CREATE INDEX IF NOT EXISTS idx_ai_call_log_called_at ON ai_call_log(called_at);
