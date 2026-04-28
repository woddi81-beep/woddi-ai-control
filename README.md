# woddi-ai-control

Webbasierte MCP-Zentrale mit neutralem Startzustand. Standardmaessig sind keine MCPs vorkonfiguriert.

## Kernidee

`woddi-ai-control` trennt Vorlagen von echten Betriebsdaten:

- Vorlagen: `config/`
- Live-MCPs: `mcps.local.json`
- Live-User/Gruppen: `passwd.json`
- Live-Personas: `personas/*.md`

Damit bleiben lokale Anpassungen bei `git pull` erhalten. Nach einem frischen Start ist `mcps.local.json` leer, damit die Instanz kein eingebautes Wissen und keine direkt verfuegbaren Integrationen mitbringt.

## Weboberflaeche

Die UI unter `http://127.0.0.1:8095/` bietet:

- Login mit Admin-/User-Trennung
- Chat mit pro User erlaubten MCPs
- Betriebsdoku direkt im Browser
- MCP-Manager fuer externe MCPs via HTTP
- Gefuehrter MCP-Guide zum Hinzufuegen, Validieren und Testen neuer MCPs
- Unterstuetzt Standard-MCP-HTTP und Satellite-Execute-Adapter, z. B. fuer NetBox-Satellites
- Remote-MCP-Handshake
- Pflege von `passwd.json` und `personas/*.md`
- Runtime- und LLM-Verwaltung
- Logs, Performance und direkte MCP-Calls

## Persistente Live-Dateien

- `passwd.json`
  User, Gruppen, Rollen, erlaubte MCPs, Persona-Zuordnung
- `mcps.local.json`
  aktive MCP-Definitionen, standardmaessig leer
- `personas/default.md`
  Standardverhalten
- `personas/network-ops.md`
  optionale Beispiel-Persona

Beim ersten Start werden diese Dateien aus `config/` erzeugt, falls sie noch fehlen. Die erzeugten MCP- und User-Dateien enthalten keine nutzbaren Default-Integrationen.

## Struktur

```text
woddi-ai-control/
  app/                 FastAPI, Chat, MCP-Registry, CLI
  config/              getrackte Vorlagen und Defaults
  docs/                Doku, in der Weboberflaeche lesbar
  personas/            lokale, menschenlesbare Live-Personas
  mcps.local.json      aktive MCP-Konfiguration
  passwd.json          aktive User-/Gruppenverwaltung
  web/                 Admin- und Chat-Oberflaeche
  systemd/             systemd Template fuer den Dienst
  scripts/             lokaler Start
  logs/                App- und Service-Logs
```

## Schnellstart

```bash
cd /srv/http/woddi-ai-control
./check
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
chmod +x woddi-ai-control
./woddi-ai-control start
```

## Ubuntu und Arch/CachyOS

- Ubuntu: `./scripts/ubuntu-first-setup.sh`
- Arch/CachyOS: `./scripts/arch-first-setup.sh`
- Vor dem ersten Start: `./check`

## Erstes Login

Es gibt keine eingebauten Default-Zugangsdaten mehr.

- Beim ersten Aufruf erscheint ein Initial-Setup fuer das erste Admin-Konto.
- Passwort-Hashes werden lokal mit PBKDF2 gespeichert.
- Secrets wie API-Keys, Tokens und Passwort-Hashes werden nicht mehr an die Web-UI zurueckgegeben.

## Betrieb

```bash
./woddi-ai-control --help
./woddi-ai-control check-prerequisites
./woddi-ai-control start
./woddi-ai-control service start
./woddi-ai-control service status
./woddi-ai-control install --systemd user
```
