"""Legge le email di avviso delle ricerche salvate sui portali (Immobiliare.it, Idealista, Casa.it, …).

Secret richiesti: EMAIL_USER, EMAIL_PASSWORD (per Gmail: una "password per le app").
Facoltativo: EMAIL_IMAP_HOST (predefinito imap.gmail.com).
"""
from __future__ import annotations

import datetime as dt
import email
import html
import imaplib
import os
import re
import urllib.request
from email.header import decode_header
from html.parser import HTMLParser

from ..common import log, parse_price, parse_rooms, parse_sqm

# Riconosce l'URL di un singolo annuncio e ne estrae il codice
LISTING_PATTERNS = [
    ("immobiliare", re.compile(r"immobiliare\.it/annunci/(\d+)")),
    ("idealista", re.compile(r"idealista\.(?:it|com)/(?:immobile|inmueble)/(\d+)")),
    ("casa.it", re.compile(r"casa\.it/immobili/(\d+)")),
    ("wikicasa", re.compile(r"wikicasa\.it/[^\s\"']*?-(\d{6,})")),
    ("trovacasa", re.compile(r"trovacasa\.it/[^\s\"']*?/(\d{6,})")),
    ("subito", re.compile(r"subito\.it/[^\s\"']*?-(\d{7,})\.htm")),
]
# Link di tracciamento da risolvere seguendo il redirect
TRACKING_PREFIXES = ("click.", "links.", "link.", "email.", "mail.", "t.", "r.", "e.", "go.", "clk.", "ct.")
MAX_RESOLVE = 400


def match_listing(url: str):
    for source, rx in LISTING_PATTERNS:
        m = rx.search(url)
        if m:
            return source, m.group(1)
    return None


class _Tokenizer(HTMLParser):
    """Trasforma l'HTML in una sequenza di ('link', href) e ('text', testo)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tokens: list[tuple[str, str]] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head"):
            self._skip += 1
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if href.startswith("http"):
                self.tokens.append(("link", html.unescape(href)))
        if tag == "img":
            src = dict(attrs).get("src") or ""
            if src.startswith("http"):
                self.tokens.append(("img", src))

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.tokens.append(("text", re.sub(r"\s+", " ", data.strip())))


_redirect_cache: dict[str, str] = {}


def resolve_url(url: str) -> str:
    if match_listing(url):
        return url
    host = url.split("/")[2] if "//" in url else ""
    if not (host.startswith(TRACKING_PREFIXES) or "track" in host or "click" in host):
        return url
    if url in _redirect_cache:
        return _redirect_cache[url]
    if len(_redirect_cache) >= MAX_RESOLVE:
        return url
    final = url
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            final = resp.geturl()
    except Exception as exc:  # redirect verso un sito che blocca: l'URL è comunque nell'eccezione
        final = getattr(exc, "url", None) or getattr(exc, "filename", None) or url
    _redirect_cache[url] = final
    return final


def parse_alert_html(body: str, resolve: bool = True) -> list[dict]:
    tok = _Tokenizer()
    tok.feed(body)
    groups: list[dict] = []
    current = None
    for kind, val in tok.tokens:
        if kind == "link":
            target = resolve_url(val) if resolve else val
            m = match_listing(target)
            if m:
                if current and (current["source"], current["source_id"]) == m:
                    continue
                current = {"source": m[0], "source_id": m[1],
                           "url": target.split("?")[0], "texts": [], "img": None}
                groups.append(current)
                continue
        if current is None:
            continue
        if kind == "text":
            current["texts"].append(val)
        elif kind == "img" and not current["img"]:
            current["img"] = val

    merged: dict[tuple, dict] = {}
    for g in groups:  # lo stesso annuncio può comparire più volte (foto + titolo)
        key = (g["source"], g["source_id"])
        if key in merged:
            merged[key]["texts"] += g["texts"]
            merged[key]["img"] = merged[key]["img"] or g["img"]
        else:
            merged[key] = g

    items = []
    for g in merged.values():
        blob = " | ".join(g["texts"][:25])
        title = next((t for t in g["texts"] if len(t) > 12 and not parse_price(t) and "€" not in t), None)
        items.append({
            "source": g["source"], "source_id": g["source_id"], "url": g["url"],
            "title": title, "price": parse_price(blob), "sqm": parse_sqm(blob), "rooms": parse_rooms(blob),
            "address": title, "thumbnail": g["img"], "description": blob[:600],
            "is_auction": 1 if re.search(r"\basta\b", blob, re.I) else 0,
        })
    return items


def _decode(s) -> str:
    out = ""
    for part, enc in decode_header(s or ""):
        out += part.decode(enc or "utf-8", errors="replace") if isinstance(part, bytes) else part
    return out


def _html_of(msg) -> str:
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            text = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
            return re.sub(r"(https?://\S+)", r'<a href="\1">\1</a>', html.escape(text)).replace("\n", "<br>")
    return ""


def fetch(cfg: dict) -> list[dict]:
    scfg = cfg.get("fonti", {}).get("email", {})
    if not scfg.get("attiva", True):
        return []
    user, pwd = os.environ.get("EMAIL_USER"), os.environ.get("EMAIL_PASSWORD")
    if not user or not pwd:
        log("Email: credenziali non impostate, salto questa fonte")
        return []
    host = os.environ.get("EMAIL_IMAP_HOST", "imap.gmail.com")
    since = (dt.date.today() - dt.timedelta(days=int(scfg.get("giorni_indietro", 3)))).strftime("%d-%b-%Y")
    items: list[dict] = []
    with imaplib.IMAP4_SSL(host) as imap:
        imap.login(user, pwd)
        imap.select(f'"{scfg.get("cartella", "INBOX")}"', readonly=True)
        ids: set[bytes] = set()
        for sender in scfg.get("mittenti", []):
            typ, data = imap.search(None, "SINCE", since, "FROM", f'"{sender}"')
            if typ == "OK" and data and data[0]:
                ids.update(data[0].split())
        log(f"Email: {len(ids)} messaggi da analizzare")
        for mid in sorted(ids):
            typ, data = imap.fetch(mid, "(RFC822)")
            if typ != "OK" or not data or not isinstance(data[0], tuple):
                continue
            msg = email.message_from_bytes(data[0][1])
            try:
                found = parse_alert_html(_html_of(msg))
            except Exception as exc:
                log("Email: messaggio non leggibile:", _decode(msg.get("Subject")), exc)
                continue
            items.extend(found)
    log(f"Email: {len(items)} annunci trovati")
    return items
