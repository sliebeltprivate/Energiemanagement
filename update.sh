#!/usr/bin/env bash
# Aktualisiert die Ladeplanung auf dem Raspberry Pi (oder einem anderen Gerät).
# Holt den neuesten Stand aus GitHub, aktualisiert die Pakete und startet die Webapp neu.
# Datenbank und Cache bleiben unverändert (siehe .gitignore).
set -euo pipefail

cd "$(dirname "$0")"

echo "==> Hole neuesten Stand von GitHub"
git pull --ff-only

echo "==> Aktualisiere Python-Pakete"
.venv/bin/pip install -q -r requirements.txt

echo "==> Starte Webapp neu"
sudo systemctl restart ladeplanung-web.service

echo "==> Fertig: $(git log -1 --oneline)"
