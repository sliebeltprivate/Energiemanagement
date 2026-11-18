"""
Trainiert das Wetter-Preismodell und speichert es in modell.json.

Aufruf (im Ordner ladeplanung/):
    .venv/bin/python train.py            # Standard: letzte ca. 13 Monate
    .venv/bin/python train.py 2025-10-01 2026-11-17

Am besten alle paar Wochen neu ausführen, damit das Modell aktuell bleibt.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

import pandas as pd
import requests

import prognose

PREIS_URL = "https://api.energy-charts.info/v2/price"


def hole_preise(start: str, ende: str) -> pd.Series:
    """EPEX Day-Ahead DE-LU, 15-Min-Werte in EUR/MWh, als stündlicher Mittelwert."""
    resp = requests.get(PREIS_URL, params={"bzn": "DE-LU", "start": start, "end": ende}, timeout=60)
    resp.raise_for_status()
    daten = resp.json()["data"]
    zeit = pd.to_datetime([d["timestamp"] for d in daten], utc=True).tz_convert(prognose.TZ)
    werte = [d["values"].get("day_ahead_price") for d in daten]
    serie = pd.Series(werte, index=zeit, dtype="float64").dropna()
    return prognose.stuendlich(serie)


def main() -> None:
    if len(sys.argv) == 3:
        start, ende = sys.argv[1], sys.argv[2]
    else:
        ende_d = date.today() - timedelta(days=2)  # Archiv hat wenige Tage Verzögerung
        start = (ende_d - timedelta(days=395)).isoformat()
        ende = ende_d.isoformat()

    print(f"Lade Wetterhistorie {start} bis {ende} ...")
    wetter = prognose.hole_wetter_historie(start, ende)
    print(f"  {len(wetter)} Stunden Wetter")

    print("Lade Börsenpreise (Energy-Charts) ...")
    preis = hole_preise(start, ende)
    print(f"  {len(preis)} Stunden Preise, Ø {preis.mean():.1f} EUR/MWh")

    modell = prognose.fitte_modell(wetter, preis)
    modell["zeitraum"] = {"start": start, "ende": ende}
    modell["backtest"] = prognose.backtest(wetter, preis)
    prognose.speichere_modell(modell)
    print("\nBacktest (4 Testfenster à 14 Tage, Mittel):")
    print(f"  Modell mit Wetter: {modell['backtest']['mittel_eur_mwh']['mae_wetter']} EUR/MWh")
    print(f"  Nur Stundenform:   {modell['backtest']['mittel_eur_mwh']['mae_stundenform']} EUR/MWh")
    print(f"  Nur Niveau:        {modell['backtest']['mittel_eur_mwh']['mae_flach']} EUR/MWh")

    print("\nModell gespeichert:", prognose.MODELL_DATEI)
    print(f"  Trainingsstunden:      {modell['trainingsstunden']}")
    print(f"  Test-MAE (14 Tage):    {modell['test_mae_eur_mwh']} EUR/MWh (Modell mit Wetter)")
    print(f"  Test-MAE Stundenform:  {modell['test_mae_stundenform_eur_mwh']} EUR/MWh (ohne Wetter)")
    print(f"  Test-MAE flach:        {modell['test_mae_flach_eur_mwh']} EUR/MWh (nur Niveau)")
    print(f"  Korrelation (Test):    {modell['test_korrelation']}")


if __name__ == "__main__":
    main()
