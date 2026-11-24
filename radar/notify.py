"""Notifiche Telegram. Secret: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID."""
from __future__ import annotations

import html
import json
import os

from .common import http_request, log


def fmt_eur(v) -> str:
    return "€ " + f"{int(v):,}".replace(",", ".") if v else "—"


def send(text: str) -> bool:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        log("Telegram non configurato. Messaggio:\n" + text)
        return False
    payload = json.dumps({"chat_id": chat, "text": text, "parse_mode": "HTML",
                          "disable_web_page_preview": False}).encode()
    try:
        http_request(f"https://api.telegram.org/bot{token}/sendMessage", data=payload,
                     headers={"Content-Type": "application/json"}, method="POST")
        return True
    except RuntimeError as exc:
        log("Telegram: invio non riuscito", exc)
        return False


def _card(r, d, dash: str, headline: str) -> str:
    e = html.escape
    lines = [f"<b>{headline}</b>",
             f"{e(r['title'] or r['address'] or 'Annuncio')}",
             f"📍 {e(r['quartiere'] or 'quartiere n.d.')} · {int(r['sqm']) if r['sqm'] else '?'} m²"
             + (f" · {r['rooms']} locali" if r['rooms'] else ""),
             f"💶 {fmt_eur(r['price'])}" + (f" ({fmt_eur(d.get('ppsqm'))}/m²)" if d.get("ppsqm") else "")]
    if d.get("sconto_zona_pct") is not None:
        word = "sotto" if d["sconto_zona_pct"] >= 0 else "sopra"
        lines.append(f"📊 {abs(d['sconto_zona_pct'])}% {word} la mediana di zona ({fmt_eur(d['ref_ppsqm'])}/m²)")
    if d.get("ribasso_pct"):
        lines.append(f"📉 Ribassato del {d['ribasso_pct']}% (era {fmt_eur(d['prezzo_max'])})")
    flags = d.get("flags", {})
    if flags.get("rischio"):
        lines.append("⚠️ " + e(", ".join(flags["rischio"])))
    if flags.get("motivato"):
        lines.append("🔥 " + e(", ".join(flags["motivato"])))
    lines.append(f"⭐ Punteggio {r['score']:.0f}/100" if r["score"] is not None else "")
    links = []
    if r["url"]:
        links.append(f'<a href="{e(r["url"])}">Apri annuncio</a>')
    if dash:
        links.append(f'<a href="{e(dash)}#{e(r["uid"])}">Dashboard</a>')
    lines.append(" · ".join(links))
    return "\n".join(l for l in lines if l)


def _matches(r, cfg) -> bool:
    ric, tg = cfg.get("ricerca", {}), cfg.get("telegram", {})
    if r["dup_of"]:
        return False
    if ric.get("prezzo_max") and r["price"] and r["price"] > ric["prezzo_max"]:
        return False
    if ric.get("prezzo_min") and r["price"] and r["price"] < ric["prezzo_min"]:
        return False
    if ric.get("mq_min") and r["sqm"] and r["sqm"] < ric["mq_min"]:
        return False
    if ric.get("mq_max") and r["sqm"] and r["sqm"] > ric["mq_max"]:
        return False
    if ric.get("locali_min") and r["rooms"] and r["rooms"] < ric["locali_min"]:
        return False
    qs = [q.upper() for q in tg.get("quartieri", [])]
    if qs and (r["quartiere"] or "").upper() not in qs:
        return False
    return True


def _once(con, uid, kind, key, day) -> bool:
    """True se questa notifica non è ancora stata inviata."""
    if con.execute("SELECT 1 FROM notified WHERE uid=? AND kind=? AND key=?", (uid, kind, key)).fetchone():
        return False
    con.execute("INSERT INTO notified (uid, kind, key, date) VALUES (?,?,?,?)", (uid, kind, key, day))
    return True


def run(con, cfg: dict, day: str, changes: dict[str, str]) -> int:
    tg = cfg.get("telegram", {})
    if not tg.get("attiva", True):
        return 0
    dash = cfg.get("generale", {}).get("dashboard_url", "")
    if "TUO-UTENTE" in dash:
        dash = ""
    preferiti = set(tg.get("preferiti", []))
    soglia = float(tg.get("soglia_nuovi", 70))
    soglia_rib = float(tg.get("soglia_ribasso_pct", 3))
    first_run = con.execute("SELECT COUNT(*) FROM notified").fetchone()[0] == 0 and \
        con.execute("SELECT COUNT(DISTINCT first_seen) FROM listings").fetchone()[0] <= 1
    messages: list[tuple[float, str]] = []

    for uid, status in changes.items():
        r = con.execute("SELECT * FROM listings WHERE uid=?", (uid,)).fetchone()
        if r is None or r["score"] is None:
            continue
        d = json.loads(r["score_detail"] or "{}")
        watched = uid in preferiti
        if not (watched or _matches(r, cfg)):
            continue
        if status == "new" and r["score"] >= soglia and not first_run:
            if _once(con, uid, "nuovo", "1", day):
                messages.append((r["score"], _card(r, d, dash, "🏠 Nuova occasione")))
        elif status == "price_change":
            hist = con.execute("SELECT price FROM price_history WHERE uid=? ORDER BY date DESC LIMIT 2", (uid,)).fetchall()
            if len(hist) == 2 and hist[0]["price"] < hist[1]["price"]:
                pct = 100 * (1 - hist[0]["price"] / hist[1]["price"])
                if (pct >= soglia_rib or watched) and _once(con, uid, "ribasso", str(hist[0]["price"]), day):
                    head = f"📉 Ribasso del {pct:.1f}%" + (" (preferito)" if watched else "")
                    messages.append((100 + r["score"], _card(r, d, dash, head)))

    messages.sort(key=lambda m: -m[0])
    limit = int(tg.get("max_messaggi", 15))
    sent = sum(1 for _, text in messages[:limit] if send(text))

    if tg.get("riepilogo_giornaliero", True) and _once(con, "*", "riepilogo", day, day):
        top = [r for r in con.execute(
            "SELECT * FROM listings WHERE active=1 AND dup_of IS NULL AND score IS NOT NULL ORDER BY score DESC LIMIT 60")
            if _matches(r, cfg)][:5]
        if top:
            e = html.escape
            n_new = sum(1 for s in changes.values() if s == "new")
            n_drop = sum(1 for s in changes.values() if s == "price_change")
            lines = [f"<b>☀️ Radar casa · {day}</b>", f"{n_new} nuovi annunci · {n_drop} variazioni di prezzo", "",
                     "<b>Le 5 migliori occasioni ora</b>"]
            for i, r in enumerate(top, 1):
                label = e((r["title"] or r["address"] or "Annuncio")[:60])
                link = f'<a href="{e(r["url"])}">{label}</a>' if r["url"] else label
                lines.append(f"{i}. {link}\n   {e(r['quartiere'] or '')} · {fmt_eur(r['price'])} · ⭐ {r['score']:.0f}")
            if dash:
                lines += ["", f'<a href="{e(dash)}">Apri la dashboard</a>']
            sent += send("\n".join(lines))
    if first_run and changes:
        log("Primo avvio: non invio un messaggio per ogni annuncio, solo il riepilogo")
    return sent
