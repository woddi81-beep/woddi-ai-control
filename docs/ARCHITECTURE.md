# Architektur

`woddi-ai-control` ist eine neue Schwester-App fuer den vorhandenen `woddi-ai`-Stack.

## Bausteine

- `app/main.py`
  FastAPI, Chat, Health, Admin-API, Reload/Restart-Endpunkte
- `app/mcp.py`
  Registry fuer:
  - mehrere Docs-MCPs aus `config/docs_sources.json`
  - einen Files-MCP aus `config/files_sources.json`
  - einen NetBox-MCP
- `app/chat.py`
  Chat-Orchestrierung mit Scope-Auswahl fuer `docs`, `files`, `netbox`
- `web/`
  Weboberflaeche fuer Chat, MCP-Steuerung, Quellenverwaltung und Operations

## Konfiguration

- `config/runtime.json`
  App-, LLM-, Docs-, Files- und NetBox-Parameter
- `config/docs_sources.json`
  einzelne Dokuquellen
- `config/files_sources.json`
  lokale Repo-/Datei-Roots fuer den Files-MCP

## Zielbild

Die Anwendung soll nicht den alten Core ersetzen, sondern als bedienbare MCP-Konsole die vorhandenen `woddi-ai`-Repos und Satelliten zusammenziehen.
