# Ladeplanung – Home-Assistant-Add-on

Zeigt die günstigsten Ladefenster für die Wallbox der nächsten Nächte und die Güte der eigenen Preisprognose.

**Diese Anwendung ist nur für Home Assistant gedacht.** Sie läuft als Add-on auf Home Assistant OS und ist über die Seitenleiste oder den Port 5055 erreichbar.

## Installation

1. Home Assistant → **Einstellungen → Apps → App-Store** (rechts unten: „App installieren“)
2. Menü (⋮) → **Repositories** → Hinzufügen: `https://github.com/sliebeltprivate/Energiemanagement`
3. Seite neu laden, **Ladeplanung** → **Installieren**
4. **Starten**, und **Im Seitenmenü anzeigen** aktivieren

Die Oberfläche öffnet sich dann in der Seitenleiste. Alternativ direkt unter `http://<IP-des-Geräts>:5055`.

## Bedienung

- **Einstellungen:** Ladeleistung, Preisgrenze (brutto), Sockel, Anzahl Nächte und Ladefenster lassen sich in der Oberfläche ändern. Nach „Neu berechnen“ rechnet die App mit den neuen Werten.
- **Ladeplan:** Pro Nacht stehen Ladeblöcke, Kosten und die Datenbasis (EPEX-Spotpreis oder Wettermodell).
- **Prognosegüte:** Fehler, Bias und Korrelation für 7 Tage, 1 Monat, 6 Monate und 1 Jahr. Bei starken Abweichungen erscheint eine rote Warnung.

## Datenquellen und Grenzen

- Die ersten Tage nutzen verbindliche EPEX-Spotpreise (Energy-Charts / Fraunhofer ISE).
- Danach schätzt ein eigenes Wettermodell die Preise aus Wind, Solar und Tageszeit (Open-Meteo). Der typische Fehler liegt bei etwa 6 ct/kWh brutto. Die Schätzung ist eine Orientierung, keine verlässliche Vorhersage. Das Modell kennt keine Gaspreise oder Ausfälle.
- Die Prognosen werden täglich gespeichert und mit den echten Preisen verglichen. Die Daten liegen im Add-on-Datenordner `/data` und bleiben bei Updates erhalten.
- Die Oberfläche hat keine Anmeldung. Im Heimnetz ist das üblich, eine Freigabe ins Internet ist nicht vorgesehen.

## Updates

Nach einer Änderung im Repository erhöht man `version` in `config.yaml`. Home Assistant zeigt dann ein Update an.

## Für Entwickler (nicht für die Installation)

Lokal auf dem Mac, nur zum Testen:

```bash
cd ladeplanung
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py          # http://localhost:5055
.venv/bin/python train.py        # Wettermodell neu trainieren
.venv/bin/python tagesjob.py     # Prognose speichern und Güte prüfen
```

Die Datenablage lässt sich mit der Umgebungsvariable `LADEPLANUNG_DATA` auf einen eigenen Ordner setzen.
