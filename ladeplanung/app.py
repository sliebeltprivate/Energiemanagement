"""
Webapp für die Ladeplanung. Start:  python app.py
Erreichbar auf dem Mac unter http://localhost:5055 und im gleichen WLAN vom iPhone
unter http://<IP-des-Macs>:5055 (siehe README.md).
"""

from __future__ import annotations

import argparse

import requests

from flask import Flask, jsonify, render_template, request

from planer import DatenFehler, STANDARD, berechne_plan
import benachrichtigung as bm

app = Flask(__name__)


def _zahl(name: str, typ, standard):
    roh = request.args.get(name)
    if roh is None or roh == "":
        return standard
    return typ(roh.replace(",", "."))


@app.get("/")
def index():
    return render_template("index.html", std={**STANDARD, **bm.planparameter(bm.lade_einstellungen())})


@app.get("/api/plan")
def api_plan():
    gespeichert = bm.planparameter(bm.lade_einstellungen())
    try:
        parameter = {
            "ladeleistung_kw": _zahl("ladeleistung_kw", float, gespeichert["ladeleistung_kw"]),
            "preisgrenze_ct": _zahl("preisgrenze_ct", float, gespeichert["preisgrenze_ct"]),
            "sockel_ct": _zahl("sockel_ct", float, gespeichert["sockel_ct"]),
            "fenster_start": _zahl("fenster_start", int, gespeichert["fenster_start"]),
            "fenster_ende": _zahl("fenster_ende", int, gespeichert["fenster_ende"]),
            "tage": _zahl("tage", int, gespeichert["tage"]),
        }
    except ValueError:
        return jsonify(fehler="Ungültige Eingabe – bitte nur Zahlen verwenden."), 400

    if not (0 <= parameter["fenster_start"] <= 23 and 0 <= parameter["fenster_ende"] <= 23):
        return jsonify(fehler="Fensterzeiten müssen zwischen 0 und 23 Uhr liegen."), 400
    if not 1 <= parameter["tage"] <= 7:
        return jsonify(fehler="Anzahl Nächte muss zwischen 1 und 7 liegen."), 400
    if parameter["ladeleistung_kw"] <= 0:
        return jsonify(fehler="Ladeleistung muss größer als 0 kW sein."), 400

    try:
        return jsonify(berechne_plan(**parameter))
    except DatenFehler as exc:
        return jsonify(fehler=str(exc)), 502


@app.get("/api/einstellungen")
def api_einstellungen_lesen():
    return jsonify(bm.lade_einstellungen())


@app.post("/api/einstellungen")
def api_einstellungen_speichern():
    daten = request.get_json(silent=True) or {}
    try:
        return jsonify(bm.speichere_einstellungen(daten))
    except bm.EinstellungsFehler as exc:
        return jsonify(fehler=str(exc)), 400


@app.get("/api/entscheidung")
def api_entscheidung():
    try:
        erg = bm.entscheidung()
    except DatenFehler as exc:
        return jsonify(fehler=str(exc)), 502
    erg.pop("plan", None)
    return jsonify(erg)


@app.post("/api/benachrichtigung/test")
def api_test():
    einst = bm.lade_einstellungen()
    if not einst["notify_dienst"]:
        return jsonify(fehler="Bitte zuerst einen Benachrichtigungsdienst eintragen."), 400
    try:
        bm.sende("Ladeplanung – Test", "Die Benachrichtigung funktioniert.", einst["notify_dienst"])
    except (RuntimeError, requests.RequestException) as exc:
        return jsonify(fehler=str(exc)), 502
    return jsonify(ok=True)


@app.get("/api/guete")
def api_guete():
    """Prognosegüte aus der lokalen Datenbank (kein externer Abruf)."""
    import guete
    return jsonify(guete.guete())


def main() -> None:
    parser = argparse.ArgumentParser(description="Ladeplanung Webapp")
    parser.add_argument("--host", default="0.0.0.0", help="0.0.0.0 = auch im WLAN erreichbar")
    parser.add_argument("--port", type=int, default=5055)
    args = parser.parse_args()
    bm.starte_hintergrund()
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
