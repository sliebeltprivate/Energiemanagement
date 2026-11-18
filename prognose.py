"""
Eigenes 7-Tage-Preismodell auf Basis von Wetterdaten (Open-Meteo).

Idee:
- Wetter (Wind in 100 m, Solarstrahlung) an mehreren deutschen Standorten mitteln
- daraus einen normierten Wind- und Solar-Index (0..1) berechnen
- Börsenpreis (EPEX Day-Ahead, Energy-Charts) per linearer Regression erklären:
  Stunde des Tages, Wochenende, Wind-Index, Solar-Index
- Bias-Korrektur über die letzten 7 Tage, damit das Preisniveau zur aktuellen Lage passt

Die Koeffizienten liegen in modell.json (erzeugt von train.py).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

TZ = ZoneInfo("Europe/Berlin")
HIER = Path(__file__).resolve().parent
MODELL_DATEI = HIER / "modell.json"
CACHE_DIR = HIER / "daten"

# Wetter-Standorte, verteilt über Wind- und Solargebiete Deutschlands
STANDORTE = {
    "Bremerhaven": (53.55, 8.58),
    "Rostock": (54.09, 12.13),
    "Quickborn": (53.73, 9.87),
    "Berlin": (52.52, 13.40),
    "Frankfurt": (50.11, 8.68),
    "Muenchen": (48.14, 11.58),
}

WETTER_VARIABLEN = "wind_speed_100m,shortwave_radiation"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIV_URL = "https://archive-api.open-meteo.com/v1/archive"


class ModellFehler(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Wetter -> Index
# ---------------------------------------------------------------------------

def wind_index(v100: pd.Series) -> pd.Series:
    """Vereinfachte Windkraftkennlinie: 0 unter 3 m/s, 1 ab 12 m/s, 0 über 25 m/s."""
    v = v100.astype(float)
    idx = ((v - 3.0) / 9.0) ** 3
    idx = idx.clip(lower=0.0, upper=1.0)
    idx[(v >= 25.0)] = 0.0
    return idx


def solar_index(strahlung: pd.Series) -> pd.Series:
    """Solarstrahlung in W/m² grob auf 0..1 normiert (1000 W/m² = Volllast)."""
    return (strahlung.astype(float) / 1000.0).clip(lower=0.0, upper=1.0)


def _wetter_von_standort(url: str, params: dict) -> pd.DataFrame:
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    h = resp.json()["hourly"]
    df = pd.DataFrame({
        "zeit": pd.to_datetime(h["time"]),
        "wind100": h["wind_speed_100m"],
        "strahlung": h["shortwave_radiation"],
    })
    df["zeit"] = df["zeit"].dt.tz_localize(TZ, ambiguous="NaT", nonexistent="shift_forward")
    df = df.dropna(subset=["zeit"])
    return df.set_index("zeit")


def _mittel_aller_standorte(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Mittelt Wind und Strahlung über alle Standorte und bildet die Indizes."""
    gesamt = pd.concat(frames, keys=range(len(frames)), names=["ort", "zeit"])
    mittel = gesamt.groupby(level="zeit").mean()
    mittel["wind_idx"] = wind_index(mittel["wind100"])
    mittel["solar_idx"] = solar_index(mittel["strahlung"])
    return mittel[["wind100", "strahlung", "wind_idx", "solar_idx"]]


def hole_wetter_prognose() -> pd.DataFrame:
    """Stündliche Wetterprognose ca. 8 Tage voraus, gemittelt über alle Standorte."""
    frames = []
    for name, (lat, lon) in STANDORTE.items():
        params = {
            "latitude": lat, "longitude": lon,
            "hourly": WETTER_VARIABLEN, "forecast_days": 8, "past_days": 7,
            "timezone": "Europe/Berlin",
        }
        try:
            frames.append(_wetter_von_standort(FORECAST_URL, params))
        except (requests.RequestException, KeyError, ValueError) as exc:
            raise ModellFehler(f"Wetterprognose für {name} nicht verfügbar: {exc}") from exc
    return _mittel_aller_standorte(frames)


def hole_wetter_historie(start: str, ende: str) -> pd.DataFrame:
    """Stündliches Wetter aus dem Archiv (für Training). Ergebnis wird gecacht."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache = CACHE_DIR / f"wetter_{start}_{ende}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)

    frames = []
    for name, (lat, lon) in STANDORTE.items():
        params = {
            "latitude": lat, "longitude": lon,
            "start_date": start, "end_date": ende,
            "hourly": WETTER_VARIABLEN, "timezone": "Europe/Berlin",
        }
        resp = requests.get(ARCHIV_URL, params=params, timeout=60)
        resp.raise_for_status()
        h = resp.json()["hourly"]
        df = pd.DataFrame({
            "zeit": pd.to_datetime(h["time"]).tz_localize(TZ, ambiguous="NaT", nonexistent="shift_forward"),
            "wind100": h["wind_speed_100m"],
            "strahlung": h["shortwave_radiation"],
        }).dropna(subset=["zeit"]).set_index("zeit")
        frames.append(df)

    mittel = _mittel_aller_standorte(frames)
    mittel.to_parquet(cache)
    return mittel


# ---------------------------------------------------------------------------
# Merkmale und Modell
# ---------------------------------------------------------------------------

def merkmale(df: pd.DataFrame) -> pd.DataFrame:
    """Baut die Regressionsmerkmale aus einem stündlichen Index-DataFrame."""
    x = pd.DataFrame(index=df.index)
    stunde = df.index.hour
    for h in range(24):
        x[f"h{h:02d}"] = (stunde == h).astype(float)
    wochentag = df.index.dayofweek
    x["wochenende"] = (wochentag >= 5).astype(float)
    x["wind"] = df["wind_idx"].values
    x["solar"] = df["solar_idx"].values
    x["wind_wochenende"] = x["wind"] * x["wochenende"]
    return x


LEVEL_STUNDEN = 168  # gleitendes Niveau = Mittel der letzten 7 Tage


def niveau(preis: pd.Series) -> float:
    """Aktuelles Preisniveau: Mittel der letzten 7 Tage (EUR/MWh)."""
    return float(preis.dropna().iloc[-LEVEL_STUNDEN:].mean())


def fitte_modell(wetter: pd.DataFrame, preis_stündlich: pd.Series, tage_test: int = 14) -> dict:
    """Lernt die Form des Preisverlaufs (Abweichung vom gleitenden Niveau).

    Test: Das Niveau wird am Beginn des Testzeitraums eingefroren, genau wie im
    Betrieb (dort kennt man nur die Vergangenheit).
    """
    preis_stündlich = preis_stündlich.dropna()
    gleitend = preis_stündlich.rolling(LEVEL_STUNDEN, min_periods=LEVEL_STUNDEN // 2).mean()
    daten = wetter.join(preis_stündlich.rename("preis"), how="inner").dropna(subset=["preis"])
    daten["niveau"] = gleitend.reindex(daten.index)
    daten = daten.dropna(subset=["niveau"])
    if len(daten) < 24 * 30:
        raise ModellFehler(f"Zu wenige Trainingsdaten ({len(daten)} Stunden).")
    daten["abweichung"] = daten["preis"] - daten["niveau"]

    grenze = daten.index.max() - pd.Timedelta(days=tage_test)
    train = daten[daten.index < grenze]
    test = daten[daten.index >= grenze]

    def loese(d: pd.DataFrame) -> np.ndarray:
        koef, *_ = np.linalg.lstsq(merkmale(d).values, d["abweichung"].values, rcond=None)
        return koef

    koef_test = loese(train)
    niveau_eingefroren = float(gleitend[gleitend.index < test.index.min()].iloc[-1])
    prognose_test = niveau_eingefroren + merkmale(test).values @ koef_test
    mae = float(np.mean(np.abs(prognose_test - test["preis"].values)))

    # Vergleich: eingefrorenes Niveau + reine Stundenform (ohne Wetter)
    form = train.groupby(train.index.hour)["abweichung"].mean()
    naiv = niveau_eingefroren + test.index.hour.map(form).values
    mae_naiv = float(np.mean(np.abs(naiv - test["preis"].values)))
    # Vergleich 2: nur eingefrorenes Niveau (flache Prognose)
    mae_flach = float(np.mean(np.abs(niveau_eingefroren - test["preis"].values)))

    koef = loese(daten)  # finale Koeffizienten auf allen Daten
    return {
        "koeffizienten": dict(zip(merkmale(daten.head(1)).columns, map(float, koef))),
        "trainiert_bis": str(daten.index.max()),
        "trainingsstunden": int(len(daten)),
        "test_mae_eur_mwh": round(mae, 2),
        "test_mae_stundenform_eur_mwh": round(mae_naiv, 2),
        "test_mae_flach_eur_mwh": round(mae_flach, 2),
        "test_korrelation": round(float(np.corrcoef(prognose_test, test["preis"].values)[0, 1]), 3),
    }


def backtest(wetter: pd.DataFrame, preis_stündlich: pd.Series, fenster: int = 4, tage: int = 14) -> dict:
    """Mehrere 14-Tage-Testfenster in die Vergangenheit: robustere Fehlerangabe."""
    ende = wetter.index.max()
    zeilen = []
    for k in range(fenster):
        bis = ende - pd.Timedelta(days=k * 30)
        m = fitte_modell(wetter[wetter.index <= bis], preis_stündlich[preis_stündlich.index <= bis], tage_test=tage)
        zeilen.append({
            "bis": str(bis.date()),
            "mae_wetter": m["test_mae_eur_mwh"],
            "mae_stundenform": m["test_mae_stundenform_eur_mwh"],
            "mae_flach": m["test_mae_flach_eur_mwh"],
        })
    mittel = {k: round(float(np.mean([z[k] for z in zeilen])), 2)
              for k in ("mae_wetter", "mae_stundenform", "mae_flach")}
    return {"fenster": zeilen, "mittel_eur_mwh": mittel}


def speichere_modell(modell: dict) -> None:
    MODELL_DATEI.write_text(json.dumps(modell, indent=2, ensure_ascii=False), encoding="utf-8")


def lade_modell() -> dict:
    if not MODELL_DATEI.exists():
        raise ModellFehler("modell.json fehlt – bitte zuerst train.py ausführen.")
    return json.loads(MODELL_DATEI.read_text(encoding="utf-8"))


def vorhersage(wetter: pd.DataFrame, modell: dict, preis_bisher: pd.Series) -> pd.Series:
    """Prognostizierter Netto-Spotpreis in ct/kWh je Stunde (ab dem Wetter-Index).

    preis_bisher: stündliche Ist-Preise (EUR/MWh) bis heute; daraus wird das aktuelle Niveau.
    """
    koef = pd.Series(modell["koeffizienten"])
    x = merkmale(wetter)[koef.index]
    abweichung = x.values @ koef.values  # EUR/MWh relativ zum Niveau
    basis = niveau(preis_bisher)
    return pd.Series((basis + abweichung) / 10.0, index=wetter.index)  # ct/kWh netto


def stuendlich(df: pd.Series) -> pd.Series:
    """Viertelstunden-Preise auf Stundenmittel bringen."""
    return df.resample("1h").mean()
