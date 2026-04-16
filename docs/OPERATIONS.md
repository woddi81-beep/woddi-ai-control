# Operations

## Start

```bash
cd /srv/http/woddi-ai-control
./woddi-ai-control start
```

## Service

```bash
./woddi-ai-control service start
./woddi-ai-control service status
./woddi-ai-control service stop
```

## Install

```bash
./woddi-ai-control check-prerequisites
./woddi-ai-control install --systemd user
```

## Wichtige Logs

- `logs/woddi-ai-control.log`
- `logs/woddi-ai-control-service.log`

## Web-Admin

Die Weboberflaeche verwaltet:

- `docs_sources.json`
- `files_sources.json`
- Runtime-Reload
- Restart/Shutdown
- direkte MCP-Calls
- LLM- und NetBox-Probe
