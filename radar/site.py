"""Esporta i dati per la dashboard (docs/data.json)."""
from __future__ import annotations

import json
import statistics

from .common import ROOT, days_between
from .db import history

OUT = ROOT / "docs" / "data.json"


def export(con, cfg: dict, day: str, omi_values: dict, demo: bool = False) -> dict:
    listings = []
    for r in con.execute("SELECT * FROM listings ORDER BY score DESC NULLS LAST").fetchall():
        if not r["active"] and days_between(r["last_seen"], day) > 30:
            continue
        d = json.loads(r["score_detail"] or "{}")
        listings.append({
            "uid": r["uid"], "src": r["source"], "url": r["url"], "t": r["title"], "addr": r["address"],
            "p": r["price"], "mq": r["sqm"], "loc": r["rooms"], "bagni": r["bathrooms"], "piano": r["floor"],
            "stato": r["condition"], "asc": r["has_lift"], "lat": r["lat"], "lon": r["lon"],
            "q": r["quartiere"], "zona": r["omi_zona"], "img": r["thumbnail"],
            "desc": (r["description"] or "")[:700], "asta": r["is_auction"],
            "first": r["first_seen"], "last": r["last_seen"], "att": r["active"], "dup": r["dup_of"],
            "s": r["score"], "d": d, "h": history(con, r["uid"]),
        })

    stats: dict[str, dict] = {}
    for s in con.execute("SELECT * FROM quartiere_stats ORDER BY date").fetchall():
        q = stats.setdefault(s["quartiere"], {"serie": []})
        q["serie"].append([s["date"], s["median_ppsqm"], s["n"]])
    for q, v in stats.items():
        active = [l for l in listings if l["q"] == q and l["att"] and not l["dup"] and l["p"] and l["mq"]]
        v["n"] = len(active)
        v["mediana"] = round(statistics.median([l["p"] / l["mq"] for l in active])) if active else None
        v["occasioni"] = sum(1 for l in active if (l["s"] or 0) >= cfg.get("telegram", {}).get("soglia_nuovi", 70))
        v["nuovi_7g"] = sum(1 for l in active if days_between(l["first"], day) <= 7)
        serie = v["serie"]
        old = next((x for x in serie if days_between(x[0], day) <= 90 and x[2] >= 8), None)
        v["trend_pct"] = round(100 * (serie[-1][1] / old[1] - 1), 1) if old and old[1] and old is not serie[-1] else None

    data = {
        "generato": day, "demo": demo, "listings": listings, "quartieri": stats,
        "omi": omi_values, "soglia": cfg.get("telegram", {}).get("soglia_nuovi", 70),
        "fonti": sorted({l["src"] for l in listings}),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return data
