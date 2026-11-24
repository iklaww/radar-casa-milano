"""Funzioni condivise: configurazione, HTTP, log, normalizzazione."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import ssl
import sys
import time
import tomllib
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = "RadarCasaMilano/1.0 (uso personale)"


def log(*parts) -> None:
    print("[radar]", *parts, file=sys.stderr, flush=True)


def load_config(path: Path | None = None) -> dict:
    path = path or ROOT / "config.toml"
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def today() -> str:
    """Data odierna, ora di Roma."""
    if os.environ.get("RADAR_OGGI"):
        return os.environ["RADAR_OGGI"]
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("Europe/Rome")).date().isoformat()
    except Exception:
        return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).date().isoformat()


def days_between(a: str, b: str) -> int:
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def http_request(url: str, *, data: bytes | dict | None = None, headers: dict | None = None,
                 method: str | None = None, timeout: int = 30, retries: int = 2) -> bytes:
    hdrs = {"User-Agent": USER_AGENT}
    hdrs.update(headers or {})
    body = None
    if isinstance(data, dict):
        body = urllib.parse.urlencode(data).encode()
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif data is not None:
        body = data
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
            with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last_err = exc
            if exc.code in (400, 401, 403, 404):
                break
        except (urllib.error.URLError, TimeoutError) as exc:
            last_err = exc
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Richiesta fallita {url[:80]}: {last_err}")


def http_json(url: str, **kw):
    return json.loads(http_request(url, **kw).decode("utf-8"))


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def norm_text(s: str | None) -> str:
    return re.sub(r"\s+", " ", strip_accents((s or "").lower())).strip()


def parse_price(text: str) -> int | None:
    """'€ 350.000' / '350.000 €' / '350000' -> 350000"""
    m = re.search(r"€\s*([\d][\d\.\s]{2,})|([\d][\d\.\s]{2,})\s*€", text)
    if not m:
        return None
    raw = re.sub(r"[^\d]", "", m.group(1) or m.group(2))
    try:
        val = int(raw)
    except ValueError:
        return None
    return val if 10_000 <= val <= 50_000_000 else None


def parse_sqm(text: str) -> float | None:
    m = re.search(r"(\d{2,4})(?:[,\.]\d+)?\s*(?:m²|m2|mq|metri quadr)", text, re.I)
    if not m:
        return None
    val = float(m.group(1))
    return val if 10 <= val <= 2000 else None


def parse_rooms(text: str) -> int | None:
    m = re.search(r"(\d{1,2})\s*(?:local|vani|camere)", text, re.I)
    if m:
        return int(m.group(1))
    words = {"monolocale": 1, "bilocale": 2, "trilocale": 3, "quadrilocale": 4, "pentalocale": 5}
    low = text.lower()
    for w, n in words.items():
        if w in low:
            return n
    return None


def to_float(v):
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else None
    except ValueError:
        return None


def to_int(v):
    """'350.000' -> 350000, '3' -> 3, '1.234,50' -> 1234"""
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    digits = re.sub(r"[^\d,]", "", str(v)).split(",")[0]
    return int(digits) if digits else None
