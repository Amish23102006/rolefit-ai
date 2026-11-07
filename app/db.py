"""SQLite persistence (PostgreSQL in production). Every user-owned row carries owner_id and every read goes
through get_owned()/list_owned(), which enforce object-level authorization at the data layer."""
import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import closing

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, pw_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'candidate', created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(jti TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_records_owner ON records(owner_id, kind);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, actor TEXT, action TEXT NOT NULL,
  object TEXT, result TEXT NOT NULL, meta TEXT);
"""


def _clean_meta(meta: dict) -> dict:
    """Audit/logs hold IDs, hashes and short values only - never raw document or CV text."""
    out = {}
    for k, v in (meta or {}).items():
        if isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        else:
            s = str(v)
            out[k] = s if len(s) <= 40 else "sha256:" + hashlib.sha256(s.encode()).hexdigest()[:16]
    return out


class DB:
    def __init__(self, path: str):
        self.path = path
        with closing(self._c()) as c, c:
            c.executescript(SCHEMA)

    def _c(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    # users / sessions
    def create_user(self, email, pw_hash, role="candidate"):
        uid = uuid.uuid4().hex
        with closing(self._c()) as c, c:
            c.execute("INSERT INTO users VALUES(?,?,?,?,?)", (uid, email, pw_hash, role, time.time()))
        return uid

    def user_by_email(self, email):
        with closing(self._c()) as c:
            r = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        return dict(r) if r else None

    def user_by_id(self, uid):
        with closing(self._c()) as c:
            r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return dict(r) if r else None

    def add_session(self, jti, uid, exp):
        with closing(self._c()) as c, c:
            c.execute("INSERT INTO sessions VALUES(?,?,?,0)", (jti, uid, exp))

    def session_valid(self, jti, uid):
        with closing(self._c()) as c:
            r = c.execute("SELECT revoked, expires_at FROM sessions WHERE jti=? AND user_id=?", (jti, uid)).fetchone()
        return bool(r) and not r["revoked"] and r["expires_at"] > time.time()

    def revoke_session(self, jti):
        with closing(self._c()) as c, c:
            c.execute("UPDATE sessions SET revoked=1 WHERE jti=?", (jti,))

    # owned records
    def put(self, kind, owner_id, data, rid=None):
        rid = rid or uuid.uuid4().hex
        with closing(self._c()) as c, c:
            c.execute("INSERT INTO records VALUES(?,?,?,?,?)", (rid, owner_id, kind, json.dumps(data), time.time()))
        return rid

    def get_owned(self, kind, rid, owner_id):
        with closing(self._c()) as c:
            r = c.execute("SELECT data FROM records WHERE id=? AND owner_id=? AND kind=?", (rid, owner_id, kind)).fetchone()
        return json.loads(r["data"]) if r else None  # None => caller returns 404 (no existence leak)

    def update_owned(self, kind, rid, owner_id, data):
        with closing(self._c()) as c, c:
            cur = c.execute("UPDATE records SET data=? WHERE id=? AND owner_id=? AND kind=?", (json.dumps(data), rid, owner_id, kind))
        return cur.rowcount == 1

    def delete_owned(self, kind, rid, owner_id):
        with closing(self._c()) as c, c:
            cur = c.execute("DELETE FROM records WHERE id=? AND owner_id=? AND kind=?", (rid, owner_id, kind))
        return cur.rowcount == 1

    def list_owned(self, kind, owner_id):
        with closing(self._c()) as c:
            rows = c.execute("SELECT id, data FROM records WHERE owner_id=? AND kind=? ORDER BY created_at", (owner_id, kind)).fetchall()
        return [dict(json.loads(r["data"]), id=r["id"]) for r in rows]

    def owners_of(self, kind):
        with closing(self._c()) as c:
            return [r["owner_id"] for r in c.execute("SELECT DISTINCT owner_id FROM records WHERE kind=?", (kind,)).fetchall()]

    def all_owned(self, owner_id):
        with closing(self._c()) as c:
            rows = c.execute("SELECT id, kind, data FROM records WHERE owner_id=?", (owner_id,)).fetchall()
        return [{"id": r["id"], "kind": r["kind"], "data": json.loads(r["data"])} for r in rows]

    def delete_user_data(self, uid):
        """Delete active data; pseudonymise audit rows (retained separately for security review)."""
        pseudo = "deleted:" + hashlib.sha256(uid.encode()).hexdigest()[:16]
        with closing(self._c()) as c, c:
            n = c.execute("DELETE FROM records WHERE owner_id=?", (uid,)).rowcount
            c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            c.execute("DELETE FROM users WHERE id=?", (uid,))
            c.execute("UPDATE audit SET actor=? WHERE actor=?", (pseudo, uid))
        return n, pseudo

    def audit(self, actor, action, obj=None, result="ok", meta=None):
        with closing(self._c()) as c, c:
            c.execute("INSERT INTO audit(ts,actor,action,object,result,meta) VALUES(?,?,?,?,?,?)",
                      (time.time(), actor, action, obj, result, json.dumps(_clean_meta(meta))))

    def audit_for(self, actor):
        with closing(self._c()) as c:
            rows = c.execute("SELECT ts, action, object, result, meta FROM audit WHERE actor=? ORDER BY id", (actor,)).fetchall()
        return [dict(r) for r in rows]
