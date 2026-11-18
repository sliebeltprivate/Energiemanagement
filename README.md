# Ladeplanung – Webapp

Zeigt die günstigsten Ladefenster der nächsten Nächte. Alle Werte (Ladeleistung, Preisgrenze, Sockel, Fenster, Anzahl Nächte) stellst du direkt in der App unter **Einstellungen** ein – nichts muss im Code geändert werden.

## Einrichten (einmalig, im Terminal)

```bash
cd "/Users/sliebelt/Projects/Energiemanagement"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Starten

```bash
cd "/Users/sliebelt/Projects/Energiemanagement"
.venv/bin/python app.py
```

- **Auf dem Mac:** http://localhost:5055
- **Auf dem iPhone:** Mac und iPhone müssen im selben WLAN sein. Die IP des Macs findest du mit:

  ```bash
  ipconfig getifaddr en0
  ```

  Dann auf dem iPhone in Safari `http://<IP>:5055` öffnen (z. B. `http://192.168.178.93:5055`).
- **Als App auf dem iPhone:** In Safari unten auf Teilen → „Zum Home-Bildschirm“. Danach startet sie wie eine App.

Die App läuft nur, solange das Terminal mit `app.py` offen ist (bzw. der Mac nicht schläft).

## Wettermodell (7-Tage-Prognose)

Die Energy-Charts-Schnittstelle liefert keine echte 7-Tage-Preisprognose (siehe Recherche). Deshalb rechnet die App selbst:

1. Die ersten Tage nutzen die verbindlichen EPEX-Spotpreise.
2. Danach schätzt `prognose.py` die Preise aus der Wetterprognose (Open-Meteo): Wind in 100 m und Solarstrahlung, gemittelt über 6 deutsche Standorte, plus Tageszeit und Wochenende.
3. Das Preisniveau kommt aus den letzten 7 Tagen echter Börsenpreise.

**Genauigkeit** (Backtest, 4 Testfenster à 14 Tage):

| Verfahren | Ø Fehler |
|---|---|
| Wettermodell | ca. 39 EUR/MWh ≈ **4,7 ct/kWh brutto** |
| nur Tagesverlauf, ohne Wetter | ca. 49 EUR/MWh ≈ 5,8 ct |
| nur aktuelles Niveau | ca. 58 EUR/MWh |

**Out-of-sample-Test** (trainiert bis 31.10.2026, getestet 01.–17.11.2026, Wetter aus historischer Prognose):

- Fehler ca. **49 EUR/MWh ≈ 5,8 ct/kWh brutto** (flach: 66 EUR/MWh)
- Korrelation 0,56
- **Systematisch zu niedrig**: Ø −34 EUR/MWh (≈ −4 ct brutto). Der Grund: Das Preisniveau stieg im November stark, das 7-Tage-Mittel hinkt hinterher.

Die Backtest-Zahl (4,7 ct) ist daher zu optimistisch. Die App zeigt den Out-of-sample-Wert (5,8 ct). Die Schätzung ist eine grobe Orientierung. Für Nächte nahe der Preisgrenze ist sie nicht verlässlich. Sicherer ist die Planung nur mit echten Spotpreisen (die ersten 1–2 Tage).

**Modell neu trainieren** (z. B. alle paar Wochen, mit aktuellen Daten):

```bash
cd "/Users/sliebelt/Projects/Energiemanagement"
.venv/bin/python train.py
```

Das Ergebnis steht in `modell.json`, die Wetterhistorie im Ordner `daten/` (Cache).

**Einschränkungen**
- Das Modell kennt keine Gaspreise, Kraftwerksausfälle oder Importe. Preissprünge durch diese Faktoren fängt es nicht ab.
- Es rechnet stündlich; die Preise werden für den Plan auf 15 Minuten übertragen.
- Die Open-Meteo-Daten sind frei nutzbar für nicht-kommerzielle Zwecke. Die Nutzungsbedingungen bitte selbst prüfen.

## Prognosegüte überwachen

`tagesjob.py` speichert jeden Tag die Modellprognose (`prognose_log.sqlite`), holt die echten Börsenpreise nach und berechnet die Güte für **7 Tage, 1 Monat, 6 Monate und 1 Jahr**. Die Werte stehen in der App unter „Prognosegüte“.

Der Job warnt bei:
- 7-Tage-Fehler über 10 ct brutto
- systematischer Abweichung (Bias) über 5 ct brutto in 7 Tagen
- einem einzelnen Tag mit über 15 ct brutto Ø-Fehler

Warnungen stehen in `warnungen.log`, werden in der App rot angezeigt und ergeben Exit-Code 2.

**Einmal manuell ausführen:**

```bash
cd "/Users/sliebelt/Projects/Energiemanagement"
.venv/bin/python tagesjob.py
```

**Täglich automatisch (macOS, 15:00):** Die Datei `com.ladeplanung.tagesjob.plist` ist eine Vorlage. Sie wird mit diesen Befehlen eingerichtet:

```bash
cp "/Users/sliebelt/Projects/Energiemanagement/com.ladeplanung.tagesjob.plist" ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.ladeplanung.tagesjob.plist
```

Voraussetzung: Der Mac ist um 15:00 eingeschaltet (läuft er nicht, holt launchd den Lauf beim nächsten Aufwachen nach). Entfernen geht mit `launchctl unload` und dem Löschen der Kopie.

**Wichtig zur Güte:** Die 6-Monats- und 1-Jahres-Werte füllen sich erst mit der Zeit. Am Anfang zeigt die App den Hinweis „nur X Tage“. Die Auswertung nutzt alle Vorhersagen (1–8 Tage Vorlauf).

## Hinweise

- Die Oberfläche ist nur im lokalen Netz erreichbar und hat keine Anmeldung. Nicht ins Internet freigeben.
- Energy-Charts-Daten werden 30 Minuten zwischengespeichert.
- Ab dem 2. Tag sind die Preise nur eine Schätzung aus der EE-Prognose. Die Prognose-Schnittstelle liefert derzeit nur ca. 24 Stunden; für spätere Nächte zeigt die App „Keine Daten“.
- Der Prognose-Endpunkt `/v2/ren_share_forecast` war beim Test defekt; die App weicht dann automatisch auf `/ren_share_forecast` aus.

## Dateien

| Datei | Zweck |
|---|---|
| `planer.py` | Berechnungslogik (aus dem ursprünglichen Script übernommen) |
| `app.py` | Webserver (Flask) mit API `/api/plan` |
| `templates/index.html` | Oberfläche für Mac und iPhone |
| `requirements.txt` | Python-Pakete |
