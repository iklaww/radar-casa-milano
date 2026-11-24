"""Uso:
    python -m radar run            raccoglie, calcola, notifica, aggiorna la dashboard
    python -m radar demo           crea dati di ESEMPIO per provare la dashboard
    python -m radar test-telegram  invia un messaggio di prova
"""
from __future__ import annotations

import sys

from . import db, geo, notify, omi, score, site
from .common import load_config, log, today
from .sources import csv_import, email_alerts, idealista

SOURCES = [("Idealista", idealista.fetch), ("Email", email_alerts.fetch), ("CSV", csv_import.fetch)]


def accept(item: dict, cfg: dict) -> bool:
    ric = cfg.get("ricerca", {})
    p, mq = item.get("price"), item.get("sqm")
    if not p:
        return False
    if ric.get("prezzo_max") and p > ric["prezzo_max"] * 1.15:  # un po' di margine per i ribassi futuri
        return False
    if ric.get("prezzo_min") and p < ric["prezzo_min"]:
        return False
    if mq and ric.get("mq_min") and mq < ric["mq_min"] * 0.85:
        return False
    return True


def run() -> None:
    cfg = load_config()
    day = today()
    con = db.connect()
    changes: dict[str, str] = {}
    for name, fetch in SOURCES:
        try:
            items = fetch(cfg)
        except Exception as exc:  # una fonte che non funziona non blocca le altre
            log(f"{name}: errore, salto la fonte →", exc)
            continue
        for it in items:
            if accept(it, cfg):
                st = db.upsert(con, it, day)
                if st != "seen":
                    changes[f"{it['source']}:{it['source_id']}"] = st
        con.commit()
    expired = db.expire_old(con, day, int(cfg.get("generale", {}).get("giorni_scadenza", 45)))
    geo.enrich_locations(con, cfg)
    dups = geo.mark_duplicates(con)
    values = omi.load_values()
    score.compute(con, cfg, day, values)
    con.commit()
    sent = notify.run(con, cfg, day, changes)
    site.export(con, cfg, day, values)
    con.commit()
    log(f"Fatto: {sum(s == 'new' for s in changes.values())} nuovi, "
        f"{sum(s == 'price_change' for s in changes.values())} variazioni di prezzo, "
        f"{expired} scaduti, {dups} doppioni, {sent} messaggi Telegram")


def demo() -> None:
    from . import demo as demo_data
    cfg = load_config()
    path = db.ROOT / "data" / "demo.sqlite"
    path.unlink(missing_ok=True)
    con = db.connect(path)
    timeline = demo_data.generate()
    days = list(timeline)
    for i, day in enumerate(days):
        for it in timeline[day]:
            db.upsert(con, it, day)
        db.expire_old(con, day, 3)
        con.execute("UPDATE listings SET quartiere=UPPER(quartiere_fonte) WHERE quartiere IS NULL")
        if i % 7 == 0 or i == len(days) - 1:
            geo.mark_duplicates(con)
            score.compute(con, cfg, day, {})
    con.commit()
    site.export(con, cfg, days[-1], {}, demo=True)
    log(f"Demo creata: {con.execute('SELECT COUNT(*) FROM listings WHERE active=1').fetchone()[0]} annunci attivi "
        "(dati inventati). Apri docs/index.html con un server locale.")


def main(argv: list[str]) -> None:
    cmd = argv[1] if len(argv) > 1 else "run"
    if cmd == "run":
        run()
    elif cmd == "demo":
        demo()
    elif cmd == "test-telegram":
        ok = notify.send("✅ Radar casa Milano: le notifiche funzionano!")
        log("Messaggio inviato" if ok else "Invio non riuscito: controlla TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID")
        sys.exit(0 if ok else 1)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
