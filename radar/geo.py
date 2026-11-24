"""Coordinate degli indirizzi (OpenStreetMap) e assegnazione del quartiere (NIL) e della zona OMI."""
from __future__ import annotations

import json
import math
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

from .common import ROOT, http_json, http_request, log, norm_text

# Riquadro del comune di Milano
BBOX = (9.04, 45.39, 9.28, 45.54)  # lon_min, lat_min, lon_max, lat_max
NOMINATIM = "https://nominatim.openstreetmap.org/search"


def in_milano(lat, lon) -> bool:
    return lat is not None and lon is not None and BBOX[1] <= lat <= BBOX[3] and BBOX[0] <= lon <= BBOX[2]


# ── Poligoni ──────────────────────────────────────────────────
def _point_in_ring(x, y, ring) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _point_in_polygon(x, y, polygon) -> bool:
    """polygon = [outer_ring, hole1, ...]"""
    if not polygon or not _point_in_ring(x, y, polygon[0]):
        return False
    return not any(_point_in_ring(x, y, hole) for hole in polygon[1:])


class Areas:
    """Insieme di aree con nome; trova l'area che contiene un punto."""

    def __init__(self, areas: list[tuple[str, list]]):
        self.areas = []  # (nome, [polygons], bbox)
        for name, polys in areas:
            xs = [p[0] for poly in polys for p in poly[0]]
            ys = [p[1] for poly in polys for p in poly[0]]
            if xs:
                self.areas.append((name, polys, (min(xs), min(ys), max(xs), max(ys))))

    def __len__(self):
        return len(self.areas)

    def find(self, lat, lon) -> str | None:
        if lat is None or lon is None:
            return None
        for name, polys, bb in self.areas:
            if bb[0] <= lon <= bb[2] and bb[1] <= lat <= bb[3]:
                if any(_point_in_polygon(lon, lat, p) for p in polys):
                    return name
        return None

    def names(self):
        return [a[0] for a in self.areas]


def load_geojson_areas(path, name_field: str) -> Areas:
    gj = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for feat in gj.get("features", []):
        props = feat.get("properties") or {}
        name = props.get(name_field)
        if name is None:  # prova nomi di campo comuni
            for alt in ("NIL", "nil", "NOME_NIL", "nome", "name", "quartiere", "QUARTIERE"):
                if props.get(alt):
                    name = props[alt]
                    break
        geom = feat.get("geometry") or {}
        if not name or not geom:
            continue
        if geom["type"] == "Polygon":
            polys = [geom["coordinates"]]
        elif geom["type"] == "MultiPolygon":
            polys = geom["coordinates"]
        else:
            continue
        out.append((str(name).strip().upper(), polys))
    return Areas(out)


def load_kml_areas(path) -> Areas:
    """Zone OMI esportate da GEOPOI (KML). Il nome della zona è nel tag <name> del Placemark."""
    tree = ET.parse(path)
    ns = {"k": tree.getroot().tag.split("}")[0].strip("{")} if "}" in tree.getroot().tag else {}
    q = (lambda t: f"k:{t}") if ns else (lambda t: t)
    out = []
    for pm in tree.getroot().iter(("{%s}" % ns["k"] if ns else "") + "Placemark"):
        name_el = pm.find(q("name"), ns)
        name = (name_el.text or "").strip() if name_el is not None else ""
        m = re.search(r"\b([A-Z]\d{1,2})\b", name)
        zona = m.group(1) if m else name
        polys = []
        for poly in pm.iter(("{%s}" % ns["k"] if ns else "") + "Polygon"):
            rings = []
            for coords in poly.iter(("{%s}" % ns["k"] if ns else "") + "coordinates"):
                ring = [tuple(map(float, c.split(",")[:2])) for c in coords.text.split()]
                rings.append(ring)
            if rings:
                polys.append(rings)
        if zona and polys:
            out.append((zona, polys))
    return Areas(out)


def load_quartieri(cfg: dict) -> Areas | None:
    gcfg = cfg.get("geo", {})
    path = ROOT / gcfg.get("file_quartieri", "data/quartieri.geojson")
    if not path.exists() and gcfg.get("url_quartieri"):
        try:
            path.write_bytes(http_request(gcfg["url_quartieri"], timeout=60))
            log("Quartieri: file scaricato")
        except RuntimeError as exc:
            log("Quartieri: download non riuscito", exc)
    if not path.exists():
        log("Quartieri: file GeoJSON assente, uso i quartieri indicati dai portali")
        return None
    areas = load_geojson_areas(path, gcfg.get("campo_nome_quartiere", "NIL"))
    log(f"Quartieri: {len(areas)} aree caricate")
    return areas


def load_omi_zones() -> Areas | None:
    files = sorted((ROOT / "data" / "omi").glob("*.kml"))
    if not files:
        return None
    areas = []
    for f in files:
        areas.extend((n, p) for n, p, _ in load_kml_areas(f).areas)
    return Areas(areas)


# ── Geocoding ─────────────────────────────────────────────────
def _clean_address(text: str) -> str | None:
    if not text:
        return None
    t = re.sub(r"(?i)\b(monolocale|bilocale|trilocale|quadrilocale|pentalocale|appartamento|attico|loft|villa|"
               r"casa indipendente|in vendita|vendita)\b", " ", text)
    t = re.sub(r"\s+", " ", t).strip(" ,-|")
    if not re.search(r"(?i)\b(via|viale|corso|piazza|piazzale|largo|vicolo|alzaia|ripa|strada|bastioni|"
                     r"galleria|foro|porta|v\.le|p\.za|c\.so)\b", t):
        return t if len(t) > 3 else None
    return t


def geocode(con, cfg: dict, text: str, budget: list[int]) -> tuple[float, float] | None:
    query = _clean_address(text)
    if not query:
        return None
    if "milano" not in query.lower():
        query += ", Milano"
    key = norm_text(query)
    hit = con.execute("SELECT lat, lon FROM geocache WHERE query=?", (key,)).fetchone()
    if hit:
        return (hit["lat"], hit["lon"]) if hit["lat"] is not None else None
    if budget[0] <= 0:
        return None
    budget[0] -= 1
    params = {"q": query, "format": "json", "limit": "1", "countrycodes": "it",
              "viewbox": f"{BBOX[0]},{BBOX[3]},{BBOX[2]},{BBOX[1]}", "bounded": "1"}
    email = cfg.get("generale", {}).get("contatto_email")
    if email and "example.com" not in email:
        params["email"] = email
    try:
        time.sleep(1.1)  # regole d'uso di Nominatim: massimo 1 richiesta al secondo
        res = http_json(f"{NOMINATIM}?{urllib.parse.urlencode(params)}", timeout=20)
    except RuntimeError as exc:
        log("Geocoding non riuscito:", exc)
        return None
    lat = lon = None
    if res:
        lat, lon = float(res[0]["lat"]), float(res[0]["lon"])
        if not in_milano(lat, lon):
            lat = lon = None
    con.execute("INSERT OR REPLACE INTO geocache (query, lat, lon) VALUES (?,?,?)", (key, lat, lon))
    return (lat, lon) if lat is not None else None


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def enrich_locations(con, cfg: dict) -> None:
    """Completa coordinate, quartiere e zona OMI per gli annunci attivi."""
    quartieri = load_quartieri(cfg)
    omi = load_omi_zones()
    budget = [int(cfg.get("geo", {}).get("max_geocoding", 150))]
    rows = con.execute("SELECT * FROM listings WHERE active=1").fetchall()
    for r in rows:
        lat, lon = r["lat"], r["lon"]
        if not in_milano(lat, lon):
            lat = lon = None
            for text in (r["address"], r["title"]):
                found = geocode(con, cfg, text, budget) if text else None
                if found:
                    lat, lon = found
                    break
        q = quartieri.find(lat, lon) if quartieri else None
        q = q or (r["quartiere_fonte"].strip().upper() if r["quartiere_fonte"] else None)
        z = omi.find(lat, lon) if omi else None
        con.execute("UPDATE listings SET lat=?, lon=?, quartiere=COALESCE(?, quartiere), omi_zona=COALESCE(?, omi_zona) "
                    "WHERE uid=?", (lat, lon, q, z, r["uid"]))

    # Annunci senza quartiere: prendi quello dell'annuncio localizzato più vicino (entro 400 m)
    known = con.execute("SELECT lat, lon, quartiere FROM listings WHERE quartiere IS NOT NULL AND lat IS NOT NULL").fetchall()
    for r in con.execute("SELECT uid, lat, lon FROM listings WHERE active=1 AND quartiere IS NULL AND lat IS NOT NULL").fetchall():
        best = min(known, key=lambda k: haversine_m(r["lat"], r["lon"], k["lat"], k["lon"]), default=None)
        if best and haversine_m(r["lat"], r["lon"], best["lat"], best["lon"]) < 400:
            con.execute("UPDATE listings SET quartiere=? WHERE uid=?", (best["quartiere"], r["uid"]))
    if budget[0] <= 0:
        log("Geocoding: limite giornaliero raggiunto, il resto domani")


def mark_duplicates(con) -> int:
    """Lo stesso immobile su più portali: stessa zona (≤150 m), superficie ±4%, prezzo ±6%."""
    rows = con.execute("SELECT uid, source, lat, lon, sqm, price, first_seen FROM listings "
                       "WHERE active=1 AND lat IS NOT NULL AND sqm IS NOT NULL AND price IS NOT NULL "
                       "ORDER BY first_seen, uid").fetchall()
    con.execute("UPDATE listings SET dup_of=NULL WHERE active=1")
    n = 0
    primaries: list = []
    for r in rows:
        dup = None
        for p in primaries:
            if p["source"] == r["source"]:
                continue
            if (abs(p["sqm"] - r["sqm"]) <= 0.04 * p["sqm"] and abs(p["price"] - r["price"]) <= 0.06 * p["price"]
                    and haversine_m(p["lat"], p["lon"], r["lat"], r["lon"]) <= 150):
                dup = p["uid"]
                break
        if dup:
            con.execute("UPDATE listings SET dup_of=? WHERE uid=?", (dup, r["uid"]))
            n += 1
        else:
            primaries.append(r)
    return n
