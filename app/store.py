"""SQLite persistence layer for Coffee Super-Agent OS.

One file, one writer lock, WAL mode.  Every table carries a concept of the
Super-agent framework (see docs/001-framework-map.md):

    Source / Thread / Trigger / Decision / Ticket / Assignment /
    Report / Input / Effect / Outbox / Ledger

The store knows nothing about policy or execution: it only reads and writes
records.  Domain rules live in engine.py.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policy (
  version INTEGER PRIMARY KEY,
  doc     TEXT NOT NULL,
  hash    TEXT NOT NULL,
  at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS thread (
  key        TEXT PRIMARY KEY,
  source     TEXT NOT NULL,
  label      TEXT NOT NULL,
  meta       TEXT NOT NULL DEFAULT '{}',
  queued     INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trigger (
  id          TEXT PRIMARY KEY,
  source      TEXT NOT NULL,
  thread_key  TEXT NOT NULL,
  kind        TEXT NOT NULL,
  at          TEXT NOT NULL,
  actor       TEXT NOT NULL,
  text        TEXT NOT NULL DEFAULT '',
  payload     TEXT NOT NULL DEFAULT '{}',
  severity    TEXT NOT NULL DEFAULT 'info',
  disposition TEXT NOT NULL DEFAULT 'queued'
);
CREATE INDEX IF NOT EXISTS idx_trigger_thread ON trigger(thread_key, at);
CREATE INDEX IF NOT EXISTS idx_trigger_at ON trigger(at);

CREATE TABLE IF NOT EXISTS decision (
  id         TEXT PRIMARY KEY,
  trigger_id TEXT NOT NULL,
  thread_key TEXT NOT NULL,
  outcome    TEXT NOT NULL,
  strength   TEXT,
  reason     TEXT NOT NULL,
  ticket_id  TEXT,
  at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ticket (
  id             TEXT PRIMARY KEY,
  title          TEXT NOT NULL,
  thread_key     TEXT NOT NULL,
  kind           TEXT NOT NULL,
  mandate        TEXT NOT NULL,
  scope          TEXT NOT NULL,
  status         TEXT NOT NULL,
  strength       TEXT NOT NULL,
  policy_version INTEGER NOT NULL,
  created_at     TEXT NOT NULL,
  ended_at       TEXT,
  ended_by       TEXT,
  outcome        TEXT,
  latest_report  TEXT,
  dir            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ticket_status ON ticket(status);

CREATE TABLE IF NOT EXISTS assignment (
  id           TEXT PRIMARY KEY,
  ticket_id    TEXT NOT NULL,
  status       TEXT NOT NULL,
  started_at   TEXT,
  ended_at     TEXT,
  attempts     INTEGER NOT NULL DEFAULT 1,
  heartbeat_at TEXT NOT NULL,
  worker       TEXT NOT NULL DEFAULT 'dsh-worker',
  error        TEXT
);
CREATE INDEX IF NOT EXISTS idx_assignment_ticket ON assignment(ticket_id);

CREATE TABLE IF NOT EXISTS report (
  id            TEXT PRIMARY KEY,
  ticket_id     TEXT NOT NULL,
  assignment_id TEXT NOT NULL,
  state         TEXT NOT NULL,
  summary       TEXT NOT NULL,
  question      TEXT,
  at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS input (
  id         TEXT PRIMARY KEY,
  ticket_id  TEXT NOT NULL,
  kind       TEXT NOT NULL,
  text       TEXT NOT NULL,
  at         TEXT NOT NULL,
  delivered  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS effect (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  kind       TEXT NOT NULL,
  key        TEXT NOT NULL,
  payload    TEXT NOT NULL,
  due_at     TEXT NOT NULL,
  attempts   INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  status     TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_effect_due ON effect(status, due_at);

CREATE TABLE IF NOT EXISTS outbox (
  id        TEXT PRIMARY KEY,
  ticket_id TEXT,
  channel   TEXT NOT NULL,
  body      TEXT NOT NULL,
  status    TEXT NOT NULL DEFAULT 'pending',
  at        TEXT NOT NULL,
  error     TEXT
);

CREATE TABLE IF NOT EXISTS reading (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  cabin      TEXT NOT NULL,
  at         TEXT NOT NULL,
  ec         REAL NOT NULL,
  ph         REAL NOT NULL,
  water_l    REAL NOT NULL,
  temp_c     REAL NOT NULL,
  rh         REAL NOT NULL,
  ppfd       REAL NOT NULL,
  energy_kwh REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reading_cabin ON reading(cabin, at);

CREATE TABLE IF NOT EXISTS batch (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  cabin         TEXT NOT NULL,
  kg_green      REAL NOT NULL,
  harvest_at    TEXT NOT NULL,
  kwh           REAL NOT NULL,
  water_l       REAL NOT NULL,
  nutrient_kg   REAL NOT NULL,
  substrate_kg  REAL NOT NULL,
  freight_tkm   REAL NOT NULL,
  region        TEXT NOT NULL,
  notes         TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS ledger_entry (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id    TEXT NOT NULL,
  at          TEXT NOT NULL,
  kind        TEXT NOT NULL,
  scope       TEXT NOT NULL,
  kgco2e      REAL NOT NULL,
  factor_id   TEXT NOT NULL DEFAULT '',
  factor_value REAL NOT NULL DEFAULT 0,
  note        TEXT NOT NULL DEFAULT '',
  prev_hash   TEXT NOT NULL,
  hash        TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS event (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  at      TEXT NOT NULL,
  kind    TEXT NOT NULL,
  subject TEXT NOT NULL DEFAULT '',
  data    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS feishu_event (
  id         TEXT PRIMARY KEY,
  at         TEXT NOT NULL,
  event_type TEXT NOT NULL,
  msg_id     TEXT NOT NULL DEFAULT '',
  chat_id    TEXT NOT NULL DEFAULT '',
  actor      TEXT NOT NULL DEFAULT '',
  text       TEXT NOT NULL DEFAULT '',
  handled    TEXT NOT NULL DEFAULT 'received'
);

CREATE TABLE IF NOT EXISTS feishu_out (
  id      TEXT PRIMARY KEY,
  at      TEXT NOT NULL,
  chat_id TEXT NOT NULL,
  kind    TEXT NOT NULL,
  body    TEXT NOT NULL,
  status  TEXT NOT NULL DEFAULT 'queued',
  error   TEXT
);
"""


def utcnow() -> str:
    """One time format everywhere: ISO-8601 UTC, second precision, Z suffix."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def loads(text: str, default=None):
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


class Store:
    def __init__(self, path: str):
        self.path = path
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        with self.lock:
            self.conn.executescript(SCHEMA)
            self.conn.execute(
                "INSERT OR IGNORE INTO kv(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self.conn.commit()

    @contextmanager
    def tx(self):
        with self.lock:
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def q(self, sql: str, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def q1(self, sql: str, args=()):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def close(self):
        with self.lock:
            self.conn.close()
