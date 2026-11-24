"""Database SQLite: annunci, storico prezzi, statistiche per quartiere, cache."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .common import ROOT, days_between

DB_PATH = ROOT / "data" / "radar.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    uid TEXT PRIMARY KEY,          -- fonte:id
    source TEXT NOT NULL,
    url TEXT,
    title TEXT,
    price INTEGER,
    sqm REAL,
    rooms INTEGER,
    bathrooms INTEGER,
    floor TEXT,
    condition TEXT,
    has_lift INTEGER,
    address TEXT,
    lat REAL,
    lon REAL,
    quartiere TEXT,
    quartiere_fonte TEXT,          -- quartiere indicato dal portale
    omi_zona TEXT,
    description TEXT,
    thumbnail TEXT,
    is_auction INTEGER DEFAULT 0,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    active INTEGER DEFAULT 1,
    dup_of TEXT,                   -- stesso immobile pubblicato su un'altra fonte
    score REAL,
    score_detail TEXT              -- JSON
);
CREATE TABLE IF NOT EXISTS price_history (
    uid TEXT NOT NULL,
    date TEXT NOT NULL,
    price INTEGER NOT NULL,
    PRIMARY KEY (uid, date)
);
CREATE TABLE IF NOT EXISTS quartiere_stats (
    date TEXT NOT NULL,
    quartiere TEXT NOT NULL,
    n INTEGER,
    median_ppsqm REAL,
    PRIMARY KEY (date, quartiere)
);
CREATE TABLE IF NOT EXISTS geocache (
    query TEXT PRIMARY KEY,
    lat REAL,
    lon REAL
);
CREATE TABLE IF NOT EXISTS notified (
    uid TEXT NOT NULL,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    date TEXT NOT NULL,
    PRIMARY KEY (uid, kind, key)
);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""

FIELDS = ["url", "title", "price", "sqm", "rooms", "bathrooms", "floor", "condition", "has_lift",
          "address", "lat", "lon", "quartiere_fonte", "description", "thumbnail", "is_auction"]


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def upsert(con: sqlite3.Connection, item: dict, day: str) -> str:
    """Inserisce o aggiorna un annuncio. Ritorna 'new', 'price_change' o 'seen'."""
    uid = f"{item['source']}:{item['source_id']}"
    row = con.execute("SELECT * FROM listings WHERE uid=?", (uid,)).fetchone()
    status = "seen"
    if row is None:
        cols = ["uid", "source", "first_seen", "last_seen", "active"] + FIELDS
        vals = [uid, item["source"], day, day, 1] + [item.get(f) for f in FIELDS]
        con.execute(f"INSERT INTO listings ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
        status = "new"
    else:
        updates = {f: item[f] for f in FIELDS if item.get(f) not in (None, "")}
        updates["last_seen"] = day
        updates["active"] = 1
        sets = ",".join(f"{k}=?" for k in updates)
        con.execute(f"UPDATE listings SET {sets} WHERE uid=?", [*updates.values(), uid])
        if item.get("price") and row["price"] and int(item["price"]) != int(row["price"]):
            status = "price_change"
    if item.get("price"):  # salva solo quando il prezzo cambia, per tenere il database leggero
        last = con.execute("SELECT price FROM price_history WHERE uid=? ORDER BY date DESC LIMIT 1",
                           (uid,)).fetchone()
        if last is None or int(last["price"]) != int(item["price"]):
            con.execute("INSERT OR REPLACE INTO price_history (uid, date, price) VALUES (?,?,?)",
                        (uid, day, int(item["price"])))
    return status


def expire_old(con: sqlite3.Connection, day: str, max_days: int) -> int:
    n = 0
    for r in con.execute("SELECT uid, last_seen FROM listings WHERE active=1").fetchall():
        if days_between(r["last_seen"], day) > max_days:
            con.execute("UPDATE listings SET active=0 WHERE uid=?", (r["uid"],))
            n += 1
    return n


def history(con: sqlite3.Connection, uid: str) -> list[tuple[str, int]]:
    rows = con.execute("SELECT date, price FROM price_history WHERE uid=? ORDER BY date", (uid,)).fetchall()
    out: list[tuple[str, int]] = []
    for r in rows:  # tiene solo i cambi di prezzo
        if not out or out[-1][1] != r["price"]:
            out.append((r["date"], r["price"]))
    return out


def kv_get(con, k, default=None):
    r = con.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return json.loads(r["v"]) if r else default


def kv_set(con, k, v):
    con.execute("INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)", (k, json.dumps(v)))
