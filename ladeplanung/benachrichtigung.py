"""
Einstellungen und Benachrichtigung „Heute Nacht anstecken?“.

- Einstellungen werden in DATA_DIR/einstellungen.json gespeichert (bleibt im Add-on erhalten).
- Entscheidung: Die Nacht lohnt sich, wenn die günstigen Stunden den eingestellten
  Energiebedarf (kWh) decken.
- Versand über den Home-Assistant-Supervisor an einen Notify-Dienst, z. B. notify.mobile_app_iphone.
- Ein Hintergrund-Thread prüft jede halbe Minute, ob die eingestellte Uhrzeit erreicht ist.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import requests

from planer import berechne_plan
from prognose import TZ, DATA_DIR

EINSTELLUNGEN_DATEI = DATA_DIR / "einstellungen.json"
SUPERVISOR_URL = "http://supervisor/core/api/services/notify/{dienst}"

STANDARD_EINSTELLUNGEN = {
    "benachrichtigung_aktiv": False,
    "uhrzeit": "18:00",          # wann die Nachricht kommt (HH:MM, lokale Zeit)
    "bedarf_kwh": 10.0,          # Energie, die über Nacht geladen werden soll
    "notify_dienst": "",         # z. B. "mobile_app_iphone"
    # Planungsparameter (gleiche Bedeutung wie in der Oberfläche)
    "ladeleistung_kw": 11.0,
    "preisgrenze_ct": 36.0,
    "sockel_ct": 19.5,
    "fenster_start": 22,
    "fenster_ende": 6,
    "tage": 7,
    # Zustand
    "zuletzt_gesendet": "",      # Datum der letzten Nachricht (YYYY-MM-DD)
}

_sperre = threading.Lock()


class EinstellungsFehler(ValueError):
    pass


def lade_einstellungen() -> dict:
    einst = dict(STANDARD_EINSTELLUNGEN)
    if EINSTELLUNGEN_DATEI.exists():
        try:
            einst.update(json.loads(EINSTELLUNGEN_DATEI.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass  # defekte Datei: Standardwerte verwenden
    return einst


def speichere_einstellungen(eingabe: dict) -> dict:
    """Prüft die Eingaben und speichert sie. Gibt die gespeicherten Einstellungen zurück."""
    einst = lade_einstellungen()
    erlaubt = set(STANDARD_EINSTELLUNGEN) - {"zuletzt_gesendet"}
    for schluessel, wert in eingabe.items():
        if schluessel not in erlaubt:
            continue
        einst[schluessel] = wert

    einst["benachrichtigung_aktiv"] = bool(einst["benachrichtigung_aktiv"])
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(einst["uhrzeit"])):
        raise EinstellungsFehler("Uhrzeit muss im Format HH:MM stehen, z. B. 18:00.")
    try:
        einst["bedarf_kwh"] = float(str(einst["bedarf_kwh"]).replace(",", "."))
        einst["ladeleistung_kw"] = float(str(einst["ladeleistung_kw"]).replace(",", "."))
        einst["preisgrenze_ct"] = float(str(einst["preisgrenze_ct"]).replace(",", "."))
        einst["sockel_ct"] = float(str(einst["sockel_ct"]).replace(",", "."))
        einst["fenster_start"] = int(einst["fenster_start"])
        einst["fenster_ende"] = int(einst["fenster_ende"])
        einst["tage"] = int(einst["tage"])
    except (TypeError, ValueError) as exc:
        raise EinstellungsFehler("Eine Zahl ist ungültig.") from exc
    if einst["bedarf_kwh"] <= 0:
        raise EinstellungsFehler("Der Energiebedarf muss größer als 0 kWh sein.")
    if not 1 <= einst["tage"] <= 7:
        raise EinstellungsFehler("Anzahl Nächte muss zwischen 1 und 7 liegen.")
    if einst["benachrichtigung_aktiv"] and not str(einst["notify_dienst"]).strip():
        raise EinstellungsFehler("Bitte den Benachrichtigungsdienst angeben, z. B. mobile_app_iphone.")
    einst["notify_dienst"] = str(einst["notify_dienst"]).strip().removeprefix("notify.")

    with _sperre:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        EINSTELLUNGEN_DATEI.write_text(json.dumps(einst, indent=2, ensure_ascii=False), encoding="utf-8")
    return einst


def planparameter(einst: dict) -> dict:
    return {k: einst[k] for k in ("ladeleistung_kw", "preisgrenze_ct", "sockel_ct",
                                  "fenster_start", "fenster_ende", "tage")}


def entscheidung(einst: dict | None = None) -> dict:
    """Lohnt sich das Anstecken heute Nacht? Gibt Begründung und Zahlen zurück."""
    einst = einst or lade_einstellungen()
    plan = berechne_plan(**planparameter(einst))
    heute = datetime.now(TZ).date().isoformat()
    nacht = plan["naechte"][0]
    if nacht["datum"] != heute:
        return {"lohnt": False, "grund": "Keine Nacht heute in der Planung.", "heute_kwh": 0.0,
                "bedarf_kwh": einst["bedarf_kwh"], "nacht": nacht["label"], "plan": plan}

    kwh = float(nacht["ladbar_kwh"])
    bedarf = float(einst["bedarf_kwh"])
    lohnt = kwh >= bedarf
    if lohnt:
        grund = (f"Heute Nacht sind {kwh:.1f} kWh günstig ladbar "
                 f"(Bedarf {bedarf:.1f} kWh).")
    else:
        grund = (f"Heute Nacht nur {kwh:.1f} kWh günstig ladbar "
                 f"(Bedarf {bedarf:.1f} kWh). Lohnt sich nicht.")
    return {"lohnt": lohnt, "grund": grund, "heute_kwh": round(kwh, 2),
            "bedarf_kwh": bedarf, "nacht": nacht["label"],
            "ladebloecke": nacht["ladebloecke"], "plan": plan}


def sende(titel: str, nachricht: str, dienst: str) -> None:
    """Schickt eine Nachricht über den Home-Assistant-Notify-Dienst."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise RuntimeError("Kein SUPERVISOR_TOKEN – läuft die App nicht als Home-Assistant-Add-on?")
    resp = requests.post(
        SUPERVISOR_URL.format(dienst=dienst),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"title": titel, "message": nachricht},
        timeout=15,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"Home Assistant antwortet mit {resp.status_code}: {resp.text[:200]}")


def pruefe_und_benachrichtige() -> str:
    """Wird zur eingestellten Zeit ausgeführt. Gibt einen Statustext für das Protokoll zurück."""
    einst = lade_einstellungen()
    if not einst["benachrichtigung_aktiv"]:
        return "inaktiv"
    jetzt = datetime.now(TZ)
    heute = jetzt.date().isoformat()
    if einst["zuletzt_gesendet"] == heute:
        return "heute bereits gesendet"

    erg = entscheidung(einst)
    if not erg["lohnt"]:
        return f"nicht gesendet: {erg['grund']}"

    bloecke = ", ".join(f"{b['von']}–{b['bis']}" for b in erg["ladebloecke"]) or "siehe App"
    sende(
        "Auto heute Nacht anstecken",
        f"{erg['grund']} Günstige Zeiten: {bloecke}.",
        einst["notify_dienst"],
    )
    einst["zuletzt_gesendet"] = heute
    with _sperre:
        EINSTELLUNGEN_DATEI.write_text(json.dumps(einst, indent=2, ensure_ascii=False), encoding="utf-8")
    return f"gesendet: {erg['grund']}"


def _schleife() -> None:
    while True:
        try:
            jetzt = datetime.now(TZ)
            einst = lade_einstellungen()
            if einst["benachrichtigung_aktiv"] and jetzt.strftime("%H:%M") == einst["uhrzeit"]:
                ergebnis = pruefe_und_benachrichtige()
                print(f"[{jetzt:%d.%m.%Y %H:%M}] Benachrichtigung: {ergebnis}", flush=True)
        except Exception as exc:  # Schleife darf nie stehen bleiben
            print(f"Benachrichtigungs-Fehler: {exc}", flush=True)
        time.sleep(30)


def starte_hintergrund() -> None:
    threading.Thread(target=_schleife, daemon=True, name="benachrichtigung").start()
