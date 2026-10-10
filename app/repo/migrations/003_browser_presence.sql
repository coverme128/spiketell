CREATE TABLE IF NOT EXISTS browser_presence (client_id TEXT NOT NULL, observed_at TEXT NOT NULL, visible INTEGER NOT NULL, PRIMARY KEY(client_id,observed_at));
CREATE INDEX IF NOT EXISTS presence_time ON browser_presence(observed_at);
