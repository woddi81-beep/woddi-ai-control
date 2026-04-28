# Web UI und Persistenz

## Zielbild

`woddi-ai-control` trennt bewusst zwischen:

- getrackten Vorlagen unter `config/`
- echten Betriebsdaten im Projekt-Root
- menschenlesbaren Personas unter `personas/`

Damit bleiben lokale Anpassungen bei einem `git pull` erhalten.

## Live-Dateien

- `passwd.json`
  Admin-, User- und Gruppenverwaltung
- `mcps.local.json`
  alle aktiven lokalen und entfernten MCPs
- `personas/*.md`
  Verhalten, Tonalitaet und Fokus pro Persona

Die Dateien werden beim ersten Start aus den Vorlagen unter `config/` erzeugt, falls sie noch fehlen.

## Weboberflaeche

### Uebersicht

- Chat mit pro User erlaubten MCPs
- System-Readiness fuer Ubuntu und Arch/CachyOS
- Health und MCP-Status
- Performance und Systemstatus

### Doku

- README
- Architektur
- Operations
- weitere Markdown-Dateien aus `docs/`

### Konfiguration

- Docs-Quellen
- Files-Roots
- MCP-Manager mit Formularen fuer `docs`, `files`, `netbox`, `remote_http`
- MCP-Guide fuer neue `remote_http`-MCPs mit Validierung, Health-, Handshake- und Command-Checks
- Standard-MCP- und Satellite-Execute-Protokolle fuer externe Dienste wie NetBox
- Remote-MCP-Handshake
- `passwd.json` als Root-Verwaltung
- Persona-Editor fuer `personas/*.md`

## Remote-MCP-Handshake

Remote MCPs koennen zwei Dinge liefern:

1. `GET /health`
   fuer Erreichbarkeit und einfache Statusinformationen
2. `POST /execute` mit `action=handshake`
   fuer Capabilities, Version, Service-Name und unterstuetzte Actions

`woddi-ai-control` nutzt beides und zeigt die Antwort in der Weboberflaeche an.
