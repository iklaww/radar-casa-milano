"""Quotazioni OMI dell'Agenzia delle Entrate.

Metti in data/omi/ il file *_VALORI.csv scaricato da
https://www1.agenziaentrate.gov.it/servizi/Consultazione/ricerca.htm (Forniture dati OMI, Milano)
e, per collegare gli annunci alle zone, il file KML delle zone OMI di Milano (GEOPOI).
"""
from __future__ import annotations

import csv

from .common import ROOT, log, to_float


def load_values() -> dict[str, dict]:
    """zona -> {'min': €/m², 'max': €/m², 'mid': €/m², 'descr': str}"""
    out: dict[str, dict] = {}
    for path in sorted((ROOT / "data" / "omi").glob("*.csv")):
        lines = path.read_text(encoding="latin-1").splitlines()
        start = next((i for i, l in enumerate(lines) if "Compr_min" in l), None)
        if start is None:
            continue
        for row in csv.DictReader(lines[start:], delimiter=";"):
            if "MILANO" not in (row.get("Comune_descrizione") or "").upper():
                continue
            tip = (row.get("Descr_Tipologia") or "").lower()
            if "abitazioni civili" not in tip:
                continue
            stato = (row.get("Stato") or "").upper()
            zona = (row.get("Zona") or "").strip()
            lo, hi = to_float(row.get("Compr_min")), to_float(row.get("Compr_max"))
            if not zona or not lo or not hi:
                continue
            # preferisci lo stato NORMALE; altrimenti tieni il primo trovato
            if zona in out and stato != "NORMALE":
                continue
            out[zona] = {"min": lo, "max": hi, "mid": (lo + hi) / 2, "stato": stato,
                         "descr": row.get("Zona_Descr") or row.get("LinkZona") or ""}
    if out:
        log(f"OMI: quotazioni per {len(out)} zone")
    return out
