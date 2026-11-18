"""
Prognosegüte: speichert die täglichen Modellprognosen und vergleicht sie später
mit den echten Börsenpreisen.

- snapshot():           speichert die aktuelle Modellprognose (nur Stunden ohne Spotpreis)
- aktualisiere_ist():   holt die echten Day-Ahead-Preise und speichert sie lokal
- guete():              Kennzahlen für 7 Tage, 1 Monat, 6 Monate, 1 Jahr + Warnungen

Alle Fehler in ct/kWh brutto (netto × 1,19 MwSt.), damit sie zur Ladeplanung passen.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from prognose import TZ

HIER = Path(__file__).resolve().parent
DB = HIER / "prognose_log.sqlite"
WARN_LOG = HIER / "warnungen.log"

MWST = 1.19
FENSTER = [("7 Tage", 7), ("1 Monat", 30), ("6 Monate", 182), ("1 Jahr", 365)]

# Schwellen für Warnungen (ct/kWh brutto)
WARN_MAE_7T = 10.0      # mittlerer Fehler der letzten 7 Tage
WARN_BIAS_7T = 5.0      # systematische Abweichung der letzten 7 Tage (in beide Richtungen)
WARN_TAG = 15.0         # einzelner Tag mit mittlerem Fehler über diesem Wert


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS prognosen (
        erstellt TEXT NOT NULL, zeit INTEGER NOT NULL, netto_ct REAL NOT NULL,
        PRIMARY KEY (erstellt, zeit))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS ist (
        zeit INTEGER PRIMARY KEY, netto_ct REAL NOT NULL)""")
    return conn


def snapshot() -> int:
    """Speichert die heutige Modellprognose. Gibt die Anzahl Stunden zurück."""
    import planer  # lokal importieren, um Zirkelbezug zu vermeiden

    df = planer.lade_preisdaten(7)
    modell = df[df["quelle"].str.startswith("Wettermodell")]
    if modell.empty:
        raise RuntimeError("Keine Modellprognose verfügbar (Wetter- oder Modelldatei prüfen).")
    stunden = modell.set_index("zeit")["spot_netto_ct"].resample("1h").mean().dropna()

    heute = datetime.now(TZ).date().isoformat()
    zeilen = [(heute, int(ts.timestamp()), float(v)) for ts, v in stunden.items()]
    with _db() as conn:
        conn.executemany("INSERT OR REPLACE INTO prognosen VALUES (?,?,?)", zeilen)
    return len(zeilen)


def aktualisiere_ist(tage: int = 400) -> int:
    """Holt die echten Day-Ahead-Preise der letzten Tage (Energy-Charts)."""
    import train  # lädt Preise als stündliche Reihe in EUR/MWh

    ende = date.today()
    start = ende - timedelta(days=tage)
    serie = train.hole_preise(start.isoformat(), ende.isoformat())
    zeilen = [(int(ts.timestamp()), float(v) / 10.0) for ts, v in serie.items()]
    with _db() as conn:
        conn.executemany("INSERT OR REPLACE INTO ist VALUES (?,?)", zeilen)
    return len(zeilen)


def _paare(jetzt: datetime) -> pd.DataFrame:
    """Alle Prognose-Stunden, für die der echte Preis schon bekannt ist."""
    jetzt_ts = int(jetzt.timestamp())
    with _db() as conn:
        rows = conn.execute("""
            SELECT p.erstellt, p.zeit, p.netto_ct, i.netto_ct
            FROM prognosen p JOIN ist i ON i.zeit = p.zeit
            WHERE p.zeit <= ? AND p.zeit >= ?""",
            (jetzt_ts, jetzt_ts - 366 * 86400)).fetchall()
    df = pd.DataFrame(rows, columns=["erstellt", "zeit", "prognose", "ist"])
    if df.empty:
        return df
    df["zeit_lokal"] = pd.to_datetime(df["zeit"], unit="s", utc=True).dt.tz_convert(TZ)
    df["fehler"] = (df["prognose"] - df["ist"]) * MWST  # brutto, + = zu teuer geschätzt
    return df


def _kennzahlen(df: pd.DataFrame, tage: int) -> dict:
    sub = df[df["zeit_lokal"] >= df["zeit_lokal"].max() - pd.Timedelta(days=tage)] if not df.empty else df
    if sub.empty:
        return {"stunden": 0, "tage_mit_daten": 0, "mae_brutto_ct": None, "bias_brutto_ct": None,
                "korrelation": None, "vollstaendig": False}
    tage_mit_daten = int(sub["zeit_lokal"].dt.date.nunique())
    return {
        "stunden": int(len(sub)),
        "tage_mit_daten": tage_mit_daten,
        "mae_brutto_ct": round(float(sub["fehler"].abs().mean()), 2),
        "bias_brutto_ct": round(float(sub["fehler"].mean()), 2),
        "korrelation": round(float(np.corrcoef(sub["prognose"], sub["ist"])[0, 1]), 3)
        if len(sub) >= 24 else None,
        "vollstaendig": tage_mit_daten >= tage * 0.8,
    }


def guete(jetzt: datetime | None = None) -> dict:
    """Kennzahlen für alle Fenster plus aktuelle Warnungen. Liest nur die lokale Datenbank."""
    jetzt = jetzt or datetime.now(TZ)
    df = _paare(jetzt)

    fenster = {name: _kennzahlen(df, tage) for name, tage in FENSTER}

    warnungen = []
    if not df.empty:
        letzte7 = df[df["zeit_lokal"] >= df["zeit_lokal"].max() - pd.Timedelta(days=7)]
        if len(letzte7) >= 24:
            mae7 = float(letzte7["fehler"].abs().mean())
            bias7 = float(letzte7["fehler"].mean())
            if mae7 > WARN_MAE_7T:
                warnungen.append(f"7-Tage-Fehler {mae7:.1f} ct brutto (Grenze {WARN_MAE_7T:.0f})")
            if abs(bias7) > WARN_BIAS_7T:
                richtung = "zu niedrig" if bias7 < 0 else "zu hoch"
                warnungen.append(f"Prognose seit 7 Tagen systematisch {richtung}: "
                                 f"{bias7:+.1f} ct brutto im Mittel")
            tage = letzte7.groupby(letzte7["zeit_lokal"].dt.date)["fehler"].apply(lambda s: s.abs().mean())
            for tag, wert in tage.items():
                if wert > WARN_TAG:
                    warnungen.append(f"Starke Abweichung am {tag.strftime('%d.%m.')}: "
                                     f"Ø {wert:.1f} ct brutto")

    return {
        "stand": jetzt.strftime("%d.%m.%Y %H:%M"),
        "fenster": fenster,
        "warnungen": warnungen,
        "datenbasis_seit": (df["zeit_lokal"].min().strftime("%d.%m.%Y") if not df.empty else None),
        "grenzen": {"mae_7t": WARN_MAE_7T, "bias_7t": WARN_BIAS_7T, "tag": WARN_TAG},
    }


def protokolliere_warnungen(ergebnis: dict) -> None:
    if not ergebnis["warnungen"]:
        return
    zeit = datetime.now(TZ).strftime("%d.%m.%Y %H:%M")
    with WARN_LOG.open("a", encoding="utf-8") as f:
        for w in ergebnis["warnungen"]:
            f.write(f"{zeit}  {w}\n")
