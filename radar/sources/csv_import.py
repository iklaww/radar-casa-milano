"""Importa annunci da file CSV in data/import/ (aste, agenzie, annunci trovati a mano…).

Colonne riconosciute (intestazione obbligatoria, separatore , oppure ;):
fonte, id, url, titolo, prezzo, mq, locali, bagni, piano, stato, indirizzo, quartiere,
lat, lon, asta, descrizione
Solo 'prezzo' e almeno uno tra 'url', 'id' o 'indirizzo' sono necessari.
"""
from __future__ import annotations

import csv
import hashlib

from ..common import ROOT, log, to_float, to_int

IMPORT_DIR = ROOT / "data" / "import"


def _rows(path):
    text = path.read_text(encoding="utf-8-sig")
    dialect = ";" if text.split("\n", 1)[0].count(";") > text.split("\n", 1)[0].count(",") else ","
    return csv.DictReader(text.splitlines(), delimiter=dialect)


def fetch(cfg: dict) -> list[dict]:
    if not cfg.get("fonti", {}).get("csv", {}).get("attiva", True):
        return []
    items = []
    for path in sorted(IMPORT_DIR.glob("*.csv")):
        if path.name.startswith("esempio"):
            continue
        for row in _rows(path):
            r = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            if not r.get("prezzo"):
                continue
            ident = r.get("id") or hashlib.sha1((r.get("url") or r.get("indirizzo") or "").encode()).hexdigest()[:12]
            items.append({
                "source": r.get("fonte") or path.stem,
                "source_id": ident,
                "url": r.get("url") or None,
                "title": r.get("titolo") or r.get("indirizzo"),
                "price": to_int(r.get("prezzo")),
                "sqm": to_float(r.get("mq")),
                "rooms": to_int(r.get("locali")),
                "bathrooms": to_int(r.get("bagni")),
                "floor": r.get("piano") or None,
                "condition": r.get("stato") or None,
                "address": r.get("indirizzo") or None,
                "quartiere_fonte": r.get("quartiere") or None,
                "lat": to_float(r.get("lat")),
                "lon": to_float(r.get("lon")),
                "is_auction": 1 if r.get("asta", "").lower() in ("1", "si", "sì", "true", "x") else 0,
                "description": r.get("descrizione") or None,
            })
    if items:
        log(f"CSV: {len(items)} annunci")
    return items
