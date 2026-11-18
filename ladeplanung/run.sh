#!/bin/sh
# Startet die Webapp im Add-on. Daten liegen in /data (persistent).
set -e
mkdir -p /data/daten
cd /app
exec python app.py --host 0.0.0.0 --port 5055
