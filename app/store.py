"""SQLite in memory; authenticated encrypted snapshots and encrypted originals on disk."""
import base64
import json
import os
import secrets
import sqlite3
import threading
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

SCHEMA = '''
CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, name TEXT, sha TEXT UNIQUE, mime TEXT, text TEXT, created TEXT, status TEXT, candidates TEXT, synthetic INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY, date TEXT, metric TEXT, value REAL, unit TEXT, source TEXT, locator TEXT, note TEXT, UNIQUE(date,metric,value,unit));
CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, kind TEXT, title TEXT, date TEXT, detail TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY, source TEXT, locator TEXT, text TEXT, vector TEXT);
CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY, created TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS chats(id TEXT PRIMARY KEY, created TEXT, question TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS diagnostics(sequence INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, payload TEXT);
'''

def atomic(path, data):
    tmp = path.with_suffix('.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)

def password_key(password, salt):
    return base64.urlsafe_b64encode(Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode()))

class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        (self.root / 'originals').mkdir(exist_ok=True, mode=0o700)
        self.mutex = threading.RLock()
        self.db = self.key = self.fernet = None
        if not (self.root / 'key.json').exists():
            atomic(self.root / 'key.json', json.dumps({'plain': Fernet.generate_key().decode()}).encode())
        if not self.protected:
            self.unlock('')

    @property
    def protected(self):
        return 'wrapped' in json.loads((self.root / 'key.json').read_text())

    def unlock(self, password):
        cfg = json.loads((self.root / 'key.json').read_text())
        if 'wrapped' in cfg:
            key = Fernet(password_key(password, base64.b64decode(cfg['salt']))).decrypt(cfg['wrapped'].encode())
        else:
            key = cfg['plain'].encode()
        with self.mutex:
            if self.db is not None:
                return
            cipher = Fernet(key)
            db = sqlite3.connect(':memory:', check_same_thread=False)
            db.row_factory = sqlite3.Row
            try:
                if (self.root / 'vault.bin').exists():
                    db.deserialize(cipher.decrypt((self.root / 'vault.bin').read_bytes()))
                    db.execute('PRAGMA trusted_schema=OFF')
                    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise ValueError('Bóveda dañada')
                    if db.execute("SELECT count(*) FROM sqlite_master WHERE type IN ('trigger','view')").fetchone()[0]:
                        raise ValueError('Esquema no admitido')
                db.executescript(SCHEMA)
            except Exception:
                db.close()
                raise
            self.key = key; self.fernet = cipher; self.db = db
            self.save()

    def lock(self):
        with self.mutex:
            if self.db:
                self.db.close()
            self.db = self.key = self.fernet = None

    def save(self):
        self.db.commit()
        atomic(self.root / 'vault.bin', self.fernet.encrypt(self.db.serialize()))

    def rows(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def setting(self, key, default=None):
        row = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value)))

    def set_password(self, password):
        salt = secrets.token_bytes(16)
        wrapped = Fernet(password_key(password, salt)).encrypt(self.key).decode()
        atomic(self.root / 'key.json', json.dumps({'salt': base64.b64encode(salt).decode(), 'wrapped': wrapped}).encode())

    def original(self, doc_id, data=None):
        path = self.root / 'originals' / (doc_id + '.bin')
        if data is not None:
            atomic(path, self.fernet.encrypt(data))
        else:
            return self.fernet.decrypt(path.read_bytes())
