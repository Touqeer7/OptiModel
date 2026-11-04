"""Local SQLite metadata with an explicit, versioned migration."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def new_id():
    return uuid4().hex


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "studio.sqlite3"
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("Database is newer than this application; use a compatible version.")
            if version < 1:
                db.executescript("""
                BEGIN;
                CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, created TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE models (id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), name TEXT NOT NULL,
                    created TEXT NOT NULL, xml TEXT NOT NULL, ir TEXT NOT NULL, diagnostics TEXT NOT NULL);
                CREATE TABLE scenarios (id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), name TEXT NOT NULL,
                    created TEXT NOT NULL, config TEXT NOT NULL);
                CREATE TABLE runs (id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), model_id TEXT NOT NULL REFERENCES models(id),
                    created TEXT NOT NULL, updated TEXT NOT NULL, state TEXT NOT NULL, stage TEXT NOT NULL, config TEXT NOT NULL,
                    mode TEXT NOT NULL, result TEXT, error TEXT, deleted INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX model_project ON models(project_id, created);
                CREATE INDEX run_project ON runs(project_id, created);
                PRAGMA user_version=1;
                COMMIT;
                """)
            db.execute(
                "UPDATE runs SET state='failed', stage='interrupted', error='Application restarted before the run completed.', updated=? WHERE state IN ('queued','running')",
                (now(),),
            )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def list(self, table, project_id=None):
        if table not in ("projects", "models", "runs", "scenarios"):
            raise ValueError("Invalid collection")
        query, args = f"SELECT * FROM {table}", []
        clauses = []
        if table in ("projects", "runs"):
            clauses.append("deleted=0")
        if project_id:
            clauses.append("project_id=?")
            args.append(project_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created DESC, rowid DESC"
        with self.connect() as db:
            return [self.decode(row) for row in db.execute(query, args)]

    def get(self, table, ident):
        if table not in ("projects", "models", "runs", "scenarios"):
            raise ValueError("Invalid collection")
        with self.connect() as db:
            row = db.execute(f"SELECT * FROM {table} WHERE id=?", (ident,)).fetchone()
        if row is None or ("deleted" in row.keys() and row["deleted"]):
            return None
        return self.decode(row)

    @staticmethod
    def decode(row):
        record = dict(row)
        for key in ("ir", "diagnostics", "config", "result"):
            if key in record and record[key] is not None:
                record[key] = json.loads(record[key])
        return record

    def insert(self, table, record):
        if table not in ("projects", "models", "runs", "scenarios"):
            raise ValueError("Invalid collection")
        data = {
            k: json.dumps(v, ensure_ascii=False, allow_nan=False) if isinstance(v, (dict, list)) else v
            for k, v in record.items()
        }
        with self.connect() as db:
            db.execute(
                f"INSERT INTO {table} ({','.join(data)}) VALUES ({','.join('?' for _ in data)})",
                list(data.values()),
            )
        return self.get(table, record["id"])

    def update_run(self, ident, **fields):
        allowed = {"state", "stage", "result", "error", "deleted"}
        if set(fields) - allowed:
            raise ValueError("Invalid fields")
        fields["updated"] = now()
        values = [
            json.dumps(v, ensure_ascii=False, allow_nan=False) if isinstance(v, dict) else v
            for v in fields.values()
        ]
        with self.connect() as db:
            guard = (
                " AND state!='canceled'" if fields.get("state") in ("running", "succeeded", "failed") else ""
            )
            db.execute(
                f"UPDATE runs SET {','.join(k + '=?' for k in fields)} WHERE id=?{guard}", [*values, ident]
            )

    def project_name(self, ident, name):
        with self.connect() as db:
            db.execute("UPDATE projects SET name=? WHERE id=? AND deleted=0", (name, ident))

    def delete_project(self, ident):
        with self.connect() as db:
            db.execute("UPDATE projects SET deleted=1 WHERE id=?", (ident,))

    def run_dir(self, project_id, run_id):
        # IDs are generated by the server, and checked even when loaded from the DB.
        for ident in (project_id, run_id):
            if len(ident) != 32 or any(c not in "0123456789abcdef" for c in ident):
                raise ValueError("Invalid storage ID")
        path = (self.root / "artifacts" / project_id / run_id).resolve()
        path.relative_to(self.root)
        return path
