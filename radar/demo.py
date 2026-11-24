"""Dati di ESEMPIO (inventati) per provare la dashboard senza chiavi API."""
from __future__ import annotations

import datetime as dt
import random

# Centri indicativi e €/m² di esempio (valori inventati, solo per la demo)
ZONE = {
    "DUOMO": (45.4642, 9.1900, 11500), "BRERA": (45.4719, 9.1873, 11000), "ISOLA": (45.4875, 9.1890, 7600),
    "NAVIGLI": (45.4520, 9.1765, 7200), "TICINESE": (45.4570, 9.1810, 8200), "PORTA ROMANA": (45.4505, 9.2035, 7400),
    "CITTA' STUDI": (45.4785, 9.2275, 5600), "LORETO": (45.4865, 9.2160, 5400), "BUENOS AIRES - VENEZIA": (45.4775, 9.2060, 7000),
    "TRE TORRI": (45.4780, 9.1560, 8800), "SARPI": (45.4800, 9.1755, 7300), "LAMBRATE": (45.4845, 9.2400, 4700),
    "BICOCCA": (45.5150, 9.2110, 4300), "BOVISA": (45.5030, 9.1605, 3900), "SAN SIRO": (45.4790, 9.1240, 4200),
    "CORVETTO": (45.4385, 9.2235, 3700), "BARONA": (45.4335, 9.1590, 3600), "GRECO": (45.5005, 9.2130, 4400),
    "DE ANGELI - MONTE ROSA": (45.4700, 9.1500, 6800), "MAGENTA - S. VITTORE": (45.4650, 9.1735, 9800),
}
TIPI = [(1, 35, 55), (2, 50, 75), (3, 70, 110), (4, 100, 150), (5, 130, 200)]
NOMI = {1: "Monolocale", 2: "Bilocale", 3: "Trilocale", 4: "Quadrilocale", 5: "Pentalocale"}
EXTRA = ["", "", "", "terrazzo", "box auto", "da ristrutturare", "ristrutturato", "giardino condominiale"]
MOTIVATO = ["", "", "", "", "", "trattabile", "vendita urgente per trasferimento"]
RISCHIO = [""] * 24 + ["nuda proprietà", "immobile occupato"]
SOURCES = ["idealista", "immobiliare", "casa.it"]


def generate(days: int = 75, n: int = 420, seed: int = 7):
    """Ritorna {data: [annunci visti quel giorno]} simulando inserimenti, ribassi e vendite."""
    rnd = random.Random(seed)
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    pool = []
    for i in range(n):
        q, (lat, lon, base) = rnd.choice(list(ZONE.items()))
        rooms, lo, hi = rnd.choice(TIPI)
        sqm = rnd.randint(lo, hi)
        extra, mot, risk = rnd.choice(EXTRA), rnd.choice(MOTIVATO), rnd.choice(RISCHIO)
        factor = rnd.gauss(1.0, 0.11) * (0.75 if "ristrutturare" in extra else 1.08 if "ristrutturato" in extra else 1)
        factor *= 0.6 if risk else 1
        if rnd.random() < 0.05:
            factor *= 0.8  # qualche vero affare
        price = round(base * sqm * factor, -3)
        appear = start + dt.timedelta(days=rnd.randint(0, days))
        life = rnd.randint(20, 200)
        drops = sorted(rnd.sample(range(10, 160), k=rnd.choice([0, 0, 0, 1, 1, 2, 3])))
        desc = ", ".join(x for x in [f"{NOMI[rooms]} di {sqm} m²", extra, mot, risk] if x)
        pool.append({
            "base": {
                "source": rnd.choice(SOURCES), "source_id": f"demo{i:04d}", "url": None,
                "title": f"{NOMI[rooms]} {sqm} m² · {q.title()}", "sqm": float(sqm), "rooms": rooms,
                "bathrooms": 1 if rooms < 3 else 2, "floor": str(rnd.randint(0, 8)),
                "condition": "da ristrutturare" if "ristrutturare" in extra else "buono stato",
                "has_lift": rnd.choice([0, 1, 1]), "address": f"Indirizzo di esempio, {q.title()}",
                "lat": lat + rnd.uniform(-0.0045, 0.0045), "lon": lon + rnd.uniform(-0.0065, 0.0065),
                "quartiere_fonte": q, "description": f"ANNUNCIO DI ESEMPIO. {desc}.",
                "is_auction": 1 if rnd.random() < 0.03 else 0,
            },
            "price": price, "appear": appear, "end": appear + dt.timedelta(days=life),
            "drops": [(appear + dt.timedelta(days=d), rnd.uniform(0.03, 0.08)) for d in drops],
        })
    timeline = {}
    for k in range(days + 1):
        day = start + dt.timedelta(days=k)
        seen = []
        for p in pool:
            if p["appear"] <= day <= p["end"]:
                price = p["price"]
                for when, pct in p["drops"]:
                    if when <= day:
                        price = round(price * (1 - pct), -3)
                seen.append({**p["base"], "price": int(price)})
        timeline[day.isoformat()] = seen
    return timeline
