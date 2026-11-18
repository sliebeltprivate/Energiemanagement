"""
Ladeplanung: Berechnet die günstigsten Ladefenster für die nächsten Nächte.

Logik übernommen aus dem ursprünglichen Script (Standort 25451 Quickborn / Rabot Energy):
- verbindliche EPEX-Spotpreise (Energy-Charts) für die nächsten 2 Tage
- 7-Tage-Prognose des EE-Anteils, daraus geschätzter Spotpreis
- Netto-Spotpreis + Sockel (Netzentgelte, Steuern, Umlagen, Marge) -> Brutto
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests

ZEITZONE = "Europe/Berlin"
MWST_FAKTOR = 1.19  # 19 % Umsatzsteuer auf den Börsenpreis
TZ = ZoneInfo(ZEITZONE)

# Standardwerte (können in der Oberfläche überschrieben werden)
STANDARD = {
    "ladeleistung_kw": 11.0,       # 2.3 kW (10A Ladeziegel) oder z.B. 11.0 kW (Wallbox)
    "preisgrenze_ct": 36.0,       # max. Ladekosten in ct/kWh brutto
    "sockel_ct": 19.5,            # fixe Netzentgelte, Steuern, Umlagen & Marge (brutto)
    "fenster_start": 22,          # Beginn Ladefenster (Stunde)
    "fenster_ende": 6,            # Ende Ladefenster (Stunde, Folgetag wenn kleiner)
    "tage": 7,                    # Anzahl Nächte
}

CACHE_SEKUNDEN = 30 * 60          # Energy-Charts-Daten max. 30 Min. zwischenspeichern
_cache: dict = {"zeit": 0.0, "df_spot": None, "df_prog": None, "key": None}
_status: dict = {"modell": False, "modell_fehler": None}

import prognose  # noqa: E402  (eigenes Wettermodell)


class DatenFehler(RuntimeError):
    """Wird geworfen, wenn die Preisdaten nicht geladen werden konnten."""


# ---------------------------------------------------------------------------
# Datenabruf
# ---------------------------------------------------------------------------

def lade_day_ahead_preise(start_dt: datetime, end_dt: datetime) -> pd.DataFrame:
    """Ruft die verbindlichen EPEX-Spot-Preise (15-Min-Takt) von Energy-Charts ab."""
    url = "https://api.energy-charts.info/price"
    params = {
        "bzn": "DE-LU",
        "start": start_dt.strftime("%Y-%m-%d"),
        "end": end_dt.strftime("%Y-%m-%d"),
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    df = pd.DataFrame({
        "zeit": pd.to_datetime(data["unix_seconds"], unit="s", utc=True).tz_convert(ZEITZONE),
        "spot_eur_mwh": data["price"],
    }).dropna(subset=["spot_eur_mwh"])

    # 100 EUR/MWh = 10.0 ct/kWh netto
    df["spot_netto_ct"] = df["spot_eur_mwh"] / 10.0
    df["quelle"] = "EPEX Spot (verbindlich)"
    return df[["zeit", "spot_netto_ct", "quelle"]]


PROGNOSE_URLS = [
    "https://api.energy-charts.info/v2/ren_share_forecast",
    "https://api.energy-charts.info/ren_share_forecast",  # Fallback, wenn v2 ausfällt
]


def lade_7_tage_prognose(start_dt: datetime, end_dt: datetime) -> pd.DataFrame:
    """Ruft die Prognose des EE-Anteils ab und schätzt daraus den Spotpreis."""
    params = {
        "country": "de",
        "start": start_dt.strftime("%Y-%m-%d"),
        "end": end_dt.strftime("%Y-%m-%d"),
    }
    letzter_fehler = None
    for url in PROGNOSE_URLS:
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            break
        except requests.RequestException as exc:
            letzter_fehler = exc
    else:
        raise letzter_fehler

    payload = data.get("data", data)
    timestamps = payload.get("unix_seconds") or payload.get("timestamps")
    ren_share = payload.get("ren_share") or payload.get("values")

    df = pd.DataFrame({
        "zeit": pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(ZEITZONE),
        "ee_anteil_pct": ren_share,
    }).dropna(subset=["ee_anteil_pct"])

    # Empirische Näherung (hoher EE-Anteil -> niedriger Spotpreis)
    # 100 % EE -> ~1.5 ct/kWh netto | 50 % EE -> ~10.5 | 20 % EE -> ~15.9
    df["spot_netto_ct"] = (19.5 - 0.18 * df["ee_anteil_pct"]).clip(lower=-2.0, upper=28.0)
    df["quelle"] = "EE-Wetterprognose (7-Tage)"
    return df[["zeit", "spot_netto_ct", "quelle"]]


def _prognose(df_spot: pd.DataFrame, heute: datetime, tage: int) -> pd.DataFrame:
    """Prognose für Stunden ohne Spotpreis: eigenes Wettermodell, sonst alte Näherung."""
    try:
        modell = prognose.lade_modell()
        wetter = prognose.hole_wetter_prognose()
        jetzt = datetime.now(TZ)
        ist = df_spot[df_spot["zeit"] <= jetzt].set_index("zeit")["spot_netto_ct"] * 10.0  # EUR/MWh
        ct_stunde = prognose.vorhersage(wetter, modell, prognose.stuendlich(ist))
        df = ct_stunde.resample("15min").ffill().rename("spot_netto_ct").reset_index()
        df.columns = ["zeit", "spot_netto_ct"]
        df["quelle"] = "Wettermodell (Open-Meteo)"
        _status["modell"] = True
        return df
    except (prognose.ModellFehler, KeyError, ValueError) as exc:
        _status["modell"] = False
        _status["modell_fehler"] = str(exc)
        return lade_7_tage_prognose(heute, heute + timedelta(days=tage + 1))


def lade_preisdaten(tage: int) -> pd.DataFrame:
    """Kombiniert Spotpreise und Prognose; echte Spotpreise haben Vorrang. Mit Cache."""
    heute = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    key = (heute.date(), tage)
    jetzt = time.time()

    if _cache["key"] != key or jetzt - _cache["zeit"] > CACHE_SEKUNDEN:
        try:
            # 8 Tage Vergangenheit, damit das Preisniveau für das Modell bekannt ist
            df_spot = lade_day_ahead_preise(heute - timedelta(days=8), heute + timedelta(days=2))
            df_prog = _prognose(df_spot, heute, tage)
        except requests.RequestException as exc:
            raise DatenFehler(f"Energy-Charts nicht erreichbar: {exc}") from exc
        except (KeyError, ValueError, TypeError) as exc:
            raise DatenFehler(f"Unerwartetes Antwortformat von Energy-Charts: {exc}") from exc
        _cache.update({"zeit": jetzt, "df_spot": df_spot, "df_prog": df_prog, "key": key})

    df_gesamt = pd.concat([_cache["df_spot"], _cache["df_prog"]])
    df_gesamt = df_gesamt.drop_duplicates(subset=["zeit"], keep="first")
    df_gesamt = df_gesamt.sort_values("zeit").reset_index(drop=True)
    if df_gesamt.empty:
        raise DatenFehler("Keine Preisdaten erhalten.")
    return df_gesamt


# ---------------------------------------------------------------------------
# Berechnung
# ---------------------------------------------------------------------------

def _gruppiere_fenster(intervalle: pd.DataFrame, delta_h: float) -> list[dict]:
    """Fasst zusammenhängende günstige Intervalle zu Ladeblöcken zusammen."""
    if intervalle.empty:
        return []
    bloecke = []
    start = prev = None
    for zeit in intervalle["zeit"]:
        if start is None:
            start = prev = zeit
            continue
        if (zeit - prev).total_seconds() / 3600.0 > delta_h * 1.5:
            bloecke.append((start, prev))
            start = zeit
        prev = zeit
    bloecke.append((start, prev))
    return [
        {
            "von": s.strftime("%H:%M"),
            "bis": (e + timedelta(hours=delta_h)).strftime("%H:%M"),
            "stunden": round(float((e - s).total_seconds() / 3600.0 + delta_h), 2),
        }
        for s, e in bloecke
    ]


def berechne_plan(
    ladeleistung_kw: float = STANDARD["ladeleistung_kw"],
    preisgrenze_ct: float = STANDARD["preisgrenze_ct"],
    sockel_ct: float = STANDARD["sockel_ct"],
    fenster_start: int = STANDARD["fenster_start"],
    fenster_ende: int = STANDARD["fenster_ende"],
    tage: int = STANDARD["tage"],
) -> dict:
    """Erstellt den Ladeplan. Gibt ein JSON-taugliches Dictionary zurück."""
    tage = int(tage)
    max_spot_netto = (preisgrenze_ct - sockel_ct) / MWST_FAKTOR
    fensterlaenge_h = (fenster_ende - fenster_start) % 24 or 24

    df = lade_preisdaten(tage)
    df["brutto_ct"] = sockel_ct + df["spot_netto_ct"] * MWST_FAKTOR

    # Intervalldauer dynamisch bestimmen (meist 0.25 h = 15 Min)
    delta_h = df["zeit"].diff().dt.total_seconds().median() / 3600.0
    if pd.isna(delta_h) or delta_h <= 0:
        delta_h = 0.25

    heute = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    naechte = []
    for tag_offset in range(tage):
        nacht_start = heute + timedelta(days=tag_offset, hours=fenster_start)
        nacht_ende = nacht_start + timedelta(hours=fensterlaenge_h)

        fenster = df[(df["zeit"] >= nacht_start) & (df["zeit"] < nacht_ende)]
        guenstig = fenster[fenster["brutto_ct"] < preisgrenze_ct]

        stunden = len(guenstig) * delta_h
        ladbar_kwh = stunden * ladeleistung_kw
        schnitt = guenstig["brutto_ct"].mean() if not guenstig.empty else None
        kosten = ladbar_kwh * schnitt / 100.0 if schnitt is not None else 0.0
        datenbasis = fenster["quelle"].iloc[0] if not fenster.empty else "Keine Daten"

        naechte.append({
            "datum": nacht_start.strftime("%Y-%m-%d"),
            "wochentag": nacht_start.strftime("%a"),
            "label": f"{nacht_start.strftime('%a %d.%m.')} → {nacht_ende.strftime('%d.%m.')}",
            "stunden_guenstig": round(stunden, 2),
            "ladbar_kwh": round(ladbar_kwh, 2),
            "schnitt_brutto_ct": round(schnitt, 1) if schnitt is not None else None,
            "kosten_eur": round(kosten, 2),
            "datenbasis": datenbasis,
            "daten_vorhanden": not fenster.empty,
            "ladebloecke": _gruppiere_fenster(guenstig, delta_h),
        })

    gesamt_std = sum(n["stunden_guenstig"] for n in naechte)
    gesamt_kwh = sum(n["ladbar_kwh"] for n in naechte)
    gesamt_eur = sum(n["kosten_eur"] for n in naechte)

    modell_info = {"aktiv": _status["modell"], "fehler": _status["modell_fehler"]}
    if _status["modell"]:
        modell = prognose.lade_modell()
        bt = modell.get("backtest", {}).get("mittel_eur_mwh", {})
        oos = modell.get("out_of_sample", {})
        if oos:
            # Ehrlichere Angabe: Test auf Zeitraum nach dem Training (historische Wetterprognose)
            modell_info["fehler_brutto_ct"] = round(oos["mae_eur_mwh_historische_prognose"] / 10.0 * MWST_FAKTOR, 1)
            modell_info["bias_brutto_ct"] = round(oos["bias_eur_mwh"] / 10.0 * MWST_FAKTOR, 1)
            modell_info["fehler_quelle"] = "Out-of-sample"
        if bt:
            # EUR/MWh netto -> ct/kWh brutto (×1,19 MwSt, ÷10)
            modell_info["fehler_backtest_brutto_ct"] = round(bt["mae_wetter"] / 10.0 * MWST_FAKTOR, 1)
            modell_info.setdefault("fehler_brutto_ct", modell_info["fehler_backtest_brutto_ct"])
            modell_info["fehler_ohne_wetter_brutto_ct"] = round(bt["mae_stundenform"] / 10.0 * MWST_FAKTOR, 1)
        modell_info["trainiert_bis"] = modell.get("trainiert_bis")

    return {
        "modell": modell_info,
        "erstellt": datetime.now(TZ).strftime("%d.%m.%Y %H:%M"),
        "parameter": {
            "ladeleistung_kw": ladeleistung_kw,
            "preisgrenze_ct": preisgrenze_ct,
            "sockel_ct": sockel_ct,
            "max_spot_netto_ct": round(max_spot_netto, 2),
            "fenster_start": fenster_start,
            "fenster_ende": fenster_ende,
            "tage": tage,
        },
        "naechte": naechte,
        "gesamt": {
            "stunden": round(gesamt_std, 1),
            "kwh": round(gesamt_kwh, 1),
            "kosten_eur": round(gesamt_eur, 2),
            # Ø Preis über alle geplanten Ladestunden, gewichtet nach kWh (ct/kWh brutto)
            "preis_ct": round(gesamt_eur / gesamt_kwh * 100, 1) if gesamt_kwh > 0 else None,
        },
        "intervall_min": round(delta_h * 60, 1),
    }
