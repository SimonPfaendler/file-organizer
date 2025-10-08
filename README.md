# 🗂️ File Organizer (Python)

Ein leichtgewichtiges CLI-Tool, das Dateien nach **Typ** und optional **Datum (Jahr/Monat)** sortiert.  
Unterstützt **JSON-Regeln** und ein **Manifest** für Undo.

Du kannst das Skript mit folgendem Befehl ausführen:  


Powershell 
py .\file_organizer.py . $HOME\Sortiert --recursive --mode move --rules .\rules.json --by-date


## Features
- Sortieren nach Dateiendungen (PDF, Bilder, Videos, …)
- Optional: nach Jahr/Monat ablegen (`--by-date`)
- Eigene Regeln per `rules.json`
- Undo via Manifest (`--undo`): py .\file_organizer.py --undo "$HOME\Sortiert\manifest_YYYY-MM-DDTHH-MM-SS.json"
