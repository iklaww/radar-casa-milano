"""API ufficiale Idealista (https://developers.idealista.com).

Richiede i secret IDEALISTA_API_KEY e IDEALISTA_API_SECRET.
"""
from __future__ import annotations

import base64
import os

from ..common import http_json, log

TOKEN_URL = "https://api.idealista.com/oauth/token"
SEARCH_URL = "https://api.idealista.com/3.5/it/search"

STATUS_IT = {"good": "buono stato", "renew": "da ristrutturare", "newdevelopment": "nuova costruzione"}


def _token(key: str, secret: str) -> str:
    basic = base64.b64encode(f"{key}:{secret}".encode()).decode()
    res = http_json(TOKEN_URL, data={"grant_type": "client_credentials", "scope": "read"},
                    headers={"Authorization": f"Basic {basic}"}, method="POST")
    return res["access_token"]


def _map(el: dict) -> dict:
    status = el.get("status")
    return {
        "source": "idealista",
        "source_id": str(el.get("propertyCode")),
        "url": el.get("url"),
        "title": el.get("suggestedTexts", {}).get("title") or el.get("address"),
        "price": int(el["price"]) if el.get("price") else None,
        "sqm": float(el["size"]) if el.get("size") else None,
        "rooms": el.get("rooms"),
        "bathrooms": el.get("bathrooms"),
        "floor": str(el["floor"]) if el.get("floor") is not None else None,
        "condition": STATUS_IT.get(status, status),
        "has_lift": 1 if el.get("hasLift") else (0 if el.get("hasLift") is False else None),
        "address": el.get("address"),
        "lat": el.get("latitude"),
        "lon": el.get("longitude"),
        "quartiere_fonte": el.get("neighborhood") or el.get("district"),
        "description": (el.get("description") or "")[:1500],
        "thumbnail": el.get("thumbnail"),
        "is_auction": 1 if el.get("isAuction") else 0,
    }


def fetch(cfg: dict) -> list[dict]:
    scfg = cfg.get("fonti", {}).get("idealista", {})
    if not scfg.get("attiva", True):
        return []
    key, secret = os.environ.get("IDEALISTA_API_KEY"), os.environ.get("IDEALISTA_API_SECRET")
    if not key or not secret:
        log("Idealista: chiavi API non impostate, salto questa fonte")
        return []
    ric = cfg.get("ricerca", {})
    token = _token(key, secret)
    items: list[dict] = []
    for page in range(1, int(scfg.get("pagine_per_giorno", 3)) + 1):
        params = {
            "country": "it", "operation": "sale", "propertyType": "homes", "locale": "it",
            "center": scfg.get("centro", "45.4642,9.1900"),
            "distance": str(scfg.get("raggio_metri", 9000)),
            "maxItems": "50", "numPage": str(page),
            "order": "publicationDate", "sort": "desc",
        }
        if ric.get("prezzo_max"):
            params["maxPrice"] = str(ric["prezzo_max"])
        if ric.get("prezzo_min"):
            params["minPrice"] = str(ric["prezzo_min"])
        if ric.get("mq_min"):
            params["minSize"] = str(ric["mq_min"])
        if ric.get("mq_max"):
            params["maxSize"] = str(ric["mq_max"])
        try:
            res = http_json(SEARCH_URL, data=params, headers={"Authorization": f"Bearer {token}"}, method="POST")
        except RuntimeError as exc:
            log("Idealista: errore", exc)
            break
        elements = res.get("elementList", [])
        items.extend(_map(e) for e in elements if e.get("propertyCode"))
        if page >= int(res.get("totalPages", 1)) or not elements:
            break
    log(f"Idealista: {len(items)} annunci")
    return items
