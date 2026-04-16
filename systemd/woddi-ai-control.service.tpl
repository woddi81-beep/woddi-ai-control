[Unit]
Description=woddi-ai-control
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
__WODDI_MONO_USER_LINE__
__WODDI_MONO_GROUP_LINE__
WorkingDirectory=__WODDI_MONO_WORKDIR__
EnvironmentFile=-__WODDI_MONO_WORKDIR__/.env
ExecStart=__WODDI_MONO_WORKDIR__/woddi-ai-control start
Restart=on-failure
RestartSec=5
TimeoutStopSec=20
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths=__WODDI_MONO_WORKDIR__/logs __WODDI_MONO_WORKDIR__/config __WODDI_MONO_WORKDIR__/data

[Install]
WantedBy=__WODDI_MONO_WANTED_BY__
