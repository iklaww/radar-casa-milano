"""Test offline: python -m unittest discover tests"""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from radar import db, score
from radar.common import parse_price, parse_sqm, parse_rooms, to_int
from radar.sources.email_alerts import parse_alert_html

ALERT = """<html><body>
<table><tr><td><a href="https://www.immobiliare.it/annunci/123456789/?utm_source=alert"><img src="https://pwm.im-cdn.it/image/1.jpg"></a></td>
<td><a href="https://www.immobiliare.it/annunci/123456789/">Trilocale via Paolo Sarpi, Milano</a>
<p>€ 450.000</p><p>3 locali · 85 m² · 2 bagni</p></td></tr>
<tr><td><a href="https://www.idealista.it/immobile/987654/">Bilocale in viale Monza 120, NoLo, Milano</a>
<p>320.000 €</p><p>62 m2</p></td></tr>
<tr><td><a href="https://www.immobiliare.it/cerca/">Vedi tutti</a></td></tr></table></body></html>"""


class TestParsing(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(parse_price("Prezzo € 1.250.000 trattabili"), 1250000)
        self.assertEqual(parse_price("350.000 €"), 350000)
        self.assertEqual(parse_sqm("superficie 85 m²"), 85)
        self.assertEqual(parse_rooms("Trilocale luminoso"), 3)
        self.assertEqual(to_int("350.000"), 350000)

    def test_email_alert(self):
        items = {i["source_id"]: i for i in parse_alert_html(ALERT, resolve=False)}
        self.assertEqual(set(items), {"123456789", "987654"})
        a = items["123456789"]
        self.assertEqual((a["source"], a["price"], a["sqm"], a["rooms"]), ("immobiliare", 450000, 85, 3))
        self.assertIn("Sarpi", a["title"])
        b = items["987654"]
        self.assertEqual((b["source"], b["price"], b["sqm"]), ("idealista", 320000, 62))


class TestScoring(unittest.TestCase):
    def test_cheap_listing_scores_high(self):
        con = db.connect(Path(tempfile.mkdtemp()) / "t.sqlite")
        cfg = {"punteggio": {"parole_motivato": ["urgente"], "parole_rischio": ["nuda proprietà"], "parole_info": []}}
        for i in range(10):
            db.upsert(con, {"source": "x", "source_id": str(i), "price": 600000 + i * 5000, "sqm": 100.0,
                            "quartiere_fonte": "ISOLA"}, "2026-01-01")
        db.upsert(con, {"source": "x", "source_id": "cheap", "price": 450000, "sqm": 100.0}, "2026-01-01")
        db.upsert(con, {"source": "x", "source_id": "np", "price": 300000, "sqm": 100.0,
                        "description": "nuda proprietà"}, "2026-01-01")
        con.execute("UPDATE listings SET quartiere='ISOLA'")
        score.compute(con, cfg, "2026-01-01", {})
        s = {r["uid"]: r["score"] for r in con.execute("SELECT uid, score FROM listings")}
        self.assertGreater(s["x:cheap"], 50)
        self.assertLess(s["x:0"], 20)
        self.assertLess(s["x:np"], s["x:cheap"])  # nuda proprietà: prezzo basso ma penalizzato

    def test_price_history_only_on_change(self):
        con = db.connect(Path(tempfile.mkdtemp()) / "t.sqlite")
        item = {"source": "x", "source_id": "1", "price": 100000, "sqm": 50.0}
        self.assertEqual(db.upsert(con, item, "2026-01-01"), "new")
        self.assertEqual(db.upsert(con, item, "2026-01-02"), "seen")
        self.assertEqual(db.upsert(con, {**item, "price": 95000}, "2026-01-03"), "price_change")
        self.assertEqual(db.history(con, "x:1"), [("2026-01-01", 100000), ("2026-01-03", 95000)])


if __name__ == "__main__":
    unittest.main()
