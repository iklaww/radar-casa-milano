"""Punteggio "affare" (0–100) e statistiche per quartiere."""
from __future__ import annotations

import json
import statistics

from .common import days_between, norm_text
from .db import history

MAX_POINTS = {"prezzo_zona": 45, "omi": 15, "ribassi": 20, "tempo": 10, "motivato": 10}


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def keyword_flags(text: str, cfg: dict) -> dict:
    t = norm_text(text)
    p = cfg.get("punteggio", {})
    found = lambda words: sorted({w for w in words if norm_text(w) in t})
    return {"motivato": found(p.get("parole_motivato", [])),
            "rischio": found(p.get("parole_rischio", [])),
            "info": found(p.get("parole_info", []))}


def compute(con, cfg: dict, day: str, omi_values: dict) -> None:
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM listings WHERE active=1 AND price > 0 AND sqm >= 15").fetchall()]
    for r in rows:
        r["ppsqm"] = r["price"] / r["sqm"]
        r["flags"] = keyword_flags(f"{r['title'] or ''} {r['description'] or ''}", cfg)
        if r["is_auction"] and "asta" not in r["flags"]["info"]:
            r["flags"]["info"].append("asta")

    # comparabili: annunci unici, senza condizioni che falsano il prezzo
    comps_pool = [r for r in rows if not r["dup_of"] and not r["flags"]["rischio"] and not r["is_auction"]]
    by_q: dict[str, list] = {}
    for r in comps_pool:
        by_q.setdefault(r["quartiere"] or "?", []).append(r)
    city = [r["ppsqm"] for r in comps_pool]

    for r in rows:
        q_list = [c for c in by_q.get(r["quartiere"] or "?", []) if c["uid"] != r["uid"]] if r["quartiere"] else []
        similar = [c["ppsqm"] for c in q_list if 0.6 * r["sqm"] <= c["sqm"] <= 1.6 * r["sqm"]]
        if len(similar) >= 6:
            ref, scope, n = statistics.median(similar), "quartiere, metratura simile", len(similar)
        elif len(q_list) >= 4:
            ref, scope, n = statistics.median([c["ppsqm"] for c in q_list]), "quartiere", len(q_list)
        elif len(city) >= 10:
            ref, scope, n = statistics.median(city), "tutta Milano (pochi dati nel quartiere)", len(city)
        else:
            ref, scope, n = None, "dati insufficienti", 0

        pts, avail = {}, {}
        disc = 1 - r["ppsqm"] / ref if ref else None
        # da ristrutturare: uno sconto del 15% circa è normale (costo dei lavori), non è un affare
        renov = "da ristrutturare" in r["flags"]["info"] or (r["condition"] or "") == "da ristrutturare"
        disc_eff = disc - 0.15 if (disc is not None and renov) else disc
        if disc is not None:
            pts["prezzo_zona"] = _clamp((disc_eff + 0.05) / 0.30) * MAX_POINTS["prezzo_zona"]
            avail["prezzo_zona"] = MAX_POINTS["prezzo_zona"]

        omi = omi_values.get(r["omi_zona"]) if r["omi_zona"] else None
        disc_omi = 1 - r["ppsqm"] / omi["mid"] if omi else None
        if disc_omi is not None:
            pts["omi"] = _clamp((disc_omi + 0.15) / 0.40) * MAX_POINTS["omi"]
            avail["omi"] = MAX_POINTS["omi"]

        hist = history(con, r["uid"])
        peak = max((p for _, p in hist), default=r["price"])
        drop = 1 - r["price"] / peak if peak else 0
        n_drops = sum(1 for (_, a), (_, b) in zip(hist, hist[1:]) if b < a)
        pts["ribassi"] = _clamp(drop / 0.12) * MAX_POINTS["ribassi"]
        avail["ribassi"] = MAX_POINTS["ribassi"]

        days = days_between(r["first_seen"], day)
        pts["tempo"] = _clamp((days - 30) / 120) * MAX_POINTS["tempo"]
        avail["tempo"] = MAX_POINTS["tempo"]

        pts["motivato"] = MAX_POINTS["motivato"] if r["flags"]["motivato"] else 0
        avail["motivato"] = MAX_POINTS["motivato"]

        if r["flags"]["rischio"]:  # prezzo basso spiegato da nuda proprietà, occupato, ecc.
            for k in ("prezzo_zona", "omi"):
                if k in pts:
                    pts[k] *= 0.4

        score = round(100 * sum(pts.values()) / sum(avail.values()), 1) if avail else None
        fair = round(ref * r["sqm"], -3) if ref else None
        margin = 0.05 + (0.02 if days > 90 else 0) + (0.02 if n_drops >= 2 else 0)
        offer = round(min(r["price"], fair or r["price"]) * (1 - margin), -3)
        detail = {
            "ppsqm": round(r["ppsqm"]), "ref_ppsqm": round(ref) if ref else None, "ref_scope": scope, "n_comps": n,
            "sconto_zona_pct": round(disc * 100, 1) if disc is not None else None,
            "omi": {"zona": r["omi_zona"], **{k: omi[k] for k in ("min", "max", "mid")}} if omi else None,
            "sconto_omi_pct": round(disc_omi * 100, 1) if disc_omi is not None else None,
            "ribasso_pct": round(drop * 100, 1), "n_ribassi": n_drops, "prezzo_max": peak,
            "giorni": days, "ristrutturare": renov, "flags": r["flags"], "prezzo_riferimento": fair, "proposta": offer,
            "punti": {k: round(v, 1) for k, v in pts.items()},
        }
        con.execute("UPDATE listings SET score=?, score_detail=? WHERE uid=?", (score, json.dumps(detail), r["uid"]))

    # fotografia giornaliera per quartiere (per i grafici di andamento)
    for q, lst in by_q.items():
        if q == "?" or not lst:
            continue
        con.execute("INSERT OR REPLACE INTO quartiere_stats (date, quartiere, n, median_ppsqm) VALUES (?,?,?,?)",
                    (day, q, len(lst), round(statistics.median([c["ppsqm"] for c in lst]))))
