"""
Webapp für die Ladeplanung. Start:  python app.py
Erreichbar auf dem Mac unter http://localhost:5055 und im gleichen WLAN vom iPhone
unter http://<IP-des-Macs>:5055 (siehe README.md).
"""

from __future__ import annotations

import argparse

from flask import Flask, jsonify, render_template, request

from planer import DatenFehler, STANDARD, berechne_plan

app = Flask(__name__)


def _zahl(name: str, typ, standard):
    roh = request.args.get(name)
    if roh is None or roh == "":
        return standard
    return typ(roh.replace(",", "."))


@app.get("/")
def index():
    return render_template("index.html", std=STANDARD)


@app.get("/api/plan")
def api_plan():
    try:
        parameter = {
            "ladeleistung_kw": _zahl("ladeleistung_kw", float, STANDARD["ladeleistung_kw"]),
            "preisgrenze_ct": _zahl("preisgrenze_ct", float, STANDARD["preisgrenze_ct"]),
            "sockel_ct": _zahl("sockel_ct", float, STANDARD["sockel_ct"]),
            "fenster_start": _zahl("fenster_start", int, STANDARD["fenster_start"]),
            "fenster_ende": _zahl("fenster_ende", int, STANDARD["fenster_ende"]),
            "tage": _zahl("tage", int, STANDARD["tage"]),
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
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
