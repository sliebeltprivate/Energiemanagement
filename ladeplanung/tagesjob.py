"""
Tagesjob: speichert die Prognose, holt echte Preise nach und prüft die Güte.

Aufruf (im Ordner ladeplanung/):
    .venv/bin/python tagesjob.py

Exit-Code 0 = alles in Ordnung, 2 = Warnung (starke Abweichung), 1 = Fehler.
Warnungen stehen zusätzlich in warnungen.log.
"""

from __future__ import annotations

import sys
from datetime import datetime

import guete


def main() -> int:
    print(f"Tagesjob {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    try:
        n = guete.snapshot()
        print(f"  Prognose gespeichert: {n} Stunden")
    except Exception as exc:  # Job soll laut scheitern, nicht still
        print(f"  FEHLER beim Speichern der Prognose: {exc}")
        return 1
    try:
        m = guete.aktualisiere_ist()
        print(f"  Echte Preise aktualisiert: {m} Stunden")
    except Exception as exc:
        print(f"  FEHLER beim Abruf der echten Preise: {exc}")
        return 1

    ergebnis = guete.guete()
    print("\nPrognosegüte (Fehler in ct/kWh brutto, + = zu teuer geschätzt):")
    for name, k in ergebnis["fenster"].items():
        if k["mae_brutto_ct"] is None:
            print(f"  {name:>9}: noch keine Daten")
            continue
        hinweis = "" if k["vollstaendig"] else f"  (nur {k['tage_mit_daten']} Tage Daten)"
        print(f"  {name:>9}: MAE {k['mae_brutto_ct']:5.2f}  Bias {k['bias_brutto_ct']:+6.2f}  "
              f"Korr {k['korrelation'] if k['korrelation'] is not None else '–'}  "
              f"Stunden {k['stunden']}{hinweis}")

    if ergebnis["warnungen"]:
        print("\nWARNUNG:")
        for w in ergebnis["warnungen"]:
            print(f"  - {w}")
        guete.protokolliere_warnungen(ergebnis)
        return 2
    print("\nKeine Warnung.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
