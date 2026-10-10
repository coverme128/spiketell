import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('CREATE TABLE IF NOT EXISTS schema_versions (version INTEGER PRIMARY KEY)')
        upgrading = bool(self.db.execute('SELECT COUNT(*) FROM schema_versions').fetchone()[0])
        for migration in sorted((Path(__file__).parent / 'migrations').glob('*.sql')):
            version = int(migration.name.split('_')[0])
            if not self.db.execute('SELECT 1 FROM schema_versions WHERE version=?', (version,)).fetchone():
                if version == 4 and upgrading:
                    # SQLite backup includes the WAL and is complete before any migration.
                    backup = Path(self.path).with_name(Path(self.path).stem + '-before-v102.sqlite3')
                    if backup.exists():
                        import time
                        backup = backup.with_name(backup.stem + f'-{time.time_ns()}.sqlite3')
                    self.backup(backup)
                try:
                    sql = '\n'.join(line for line in migration.read_text().splitlines() if not line.startswith('PRAGMA '))
                    self.db.executescript('BEGIN IMMEDIATE;\n'+sql+f'\nINSERT OR IGNORE INTO schema_versions VALUES ({version});\nCOMMIT;')
                except Exception:
                    self.db.rollback()
                    raise

    @contextmanager
    def transaction(self):
        with self.lock, self.db:
            yield self.db

    def rows(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def counter(self, key):
        self.db.execute("INSERT INTO counters VALUES (?,1) ON CONFLICT(key) DO UPDATE SET value=value+1", (key,))

    def settings(self):
        result = {"quiet_mode": False, "notification_enabled": True, "max_watchlist": 30, "retention_days":90}
        result.update({r["key"]: json.loads(r["value"]) for r in self.rows("SELECT * FROM settings")})
        return result

    def sequence(self):
        return self.rows("SELECT COALESCE(MAX(sequence),0) FROM episode_events")[0][0]

    def backup(self, path):
        with self.lock, sqlite3.connect(path) as target:
            self.db.backup(target)

    def close(self):
        self.db.close()

    def evidence(self, key, default=None):
        rows = self.rows('SELECT payload FROM runtime_evidence WHERE key=?', (key,))
        return json.loads(rows[0][0]) if rows else default

    def save_evidence(self, key, value):
        with self.transaction() as db:
            db.execute('INSERT INTO runtime_evidence VALUES (?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload', (key,dump(value)))
