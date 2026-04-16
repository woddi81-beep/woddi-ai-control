from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings, load_settings


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VENV = PROJECT_ROOT / ".venv"
APP_CMD = "woddi-ai-control"
UNIT_NAME = "woddi-ai-control.service"
SYSTEMD_TEMPLATE = PROJECT_ROOT / "systemd/woddi-ai-control.service.tpl"
LOCAL_PID = PROJECT_ROOT / "logs/woddi-ai-control.pid"
LOCAL_STDOUT = PROJECT_ROOT / "logs/woddi-ai-control-service.log"


def _preferred_python_bin() -> str | None:
    return shutil.which("python3") or shutil.which("python")


def _venv_python(venv_path: Path) -> Path:
    return venv_path / "bin/python"


def _venv_pip(venv_path: Path) -> Path:
    return venv_path / "bin/pip"


def _status_icon(status: str) -> str:
    return {
        "pass": "[pass]",
        "warn": "[warn]",
        "fail": "[fail]",
        "info": "[info]",
    }.get(status, "[info]")


def _check_item(name: str, status: str, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "message": message,
        "data": data or {},
    }


def _print_checks(report: dict[str, Any], title: str) -> None:
    print(title)
    for item in report.get("checks", []):
        print(f"{_status_icon(str(item.get('status', 'info')))} {item.get('name')}: {item.get('message')}")
    summary = report.get("summary", {})
    print(
        f"summary: pass={summary.get('passed', 0)} warn={summary.get('warnings', 0)} fail={summary.get('failed', 0)}"
    )


def _parse_env_text(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip().strip('"').strip("'")
    return parsed


def _build_prerequisite_report(args: argparse.Namespace) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    py_ok = sys.version_info >= (3, 10)
    checks.append(
        _check_item(
            "python_version",
            "pass" if py_ok else "fail",
            f"Python {sys.version.split()[0]} (min 3.10)",
        )
    )

    runtime_bin = _preferred_python_bin()
    checks.append(
        _check_item(
            "python_runtime",
            "pass" if runtime_bin else "fail",
            f"Python Runtime gefunden: {runtime_bin}" if runtime_bin else "python3/python fehlt.",
        )
    )

    has_venv = False
    if runtime_bin:
        try:
            subprocess.run(
                [runtime_bin, "-c", "import venv"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            has_venv = True
        except subprocess.CalledProcessError:
            has_venv = False
    checks.append(
        _check_item(
            "python_venv_module",
            "pass" if has_venv else "fail",
            "Python Modul venv verfuegbar." if has_venv else "Python Modul venv fehlt.",
        )
    )

    checks.append(
        _check_item(
            "command_systemctl",
            "pass" if shutil.which("systemctl") else "warn",
            "systemctl gefunden." if shutil.which("systemctl") else "systemctl fehlt (relevant fuer --systemd).",
        )
    )

    if getattr(args, "systemd", "none") in {"user", "system"}:
        checks.append(
            _check_item(
                "systemd_template",
                "pass" if SYSTEMD_TEMPLATE.exists() else "fail",
                f"Template {'vorhanden' if SYSTEMD_TEMPLATE.exists() else 'fehlt'}: {SYSTEMD_TEMPLATE}",
            )
        )
    if getattr(args, "systemd", "none") == "system":
        checks.append(
            _check_item(
                "system_mode_permissions",
                "pass" if os.geteuid() == 0 else "fail",
                "Root-Rechte fuer --systemd system vorhanden." if os.geteuid() == 0 else "Root-Rechte fehlen fuer --systemd system.",
            )
        )

    required_files = [
        PROJECT_ROOT / "pyproject.toml",
        PROJECT_ROOT / "app/main.py",
        PROJECT_ROOT / "app/cli.py",
        PROJECT_ROOT / "config/runtime.json",
        PROJECT_ROOT / "config/docs_sources.json",
        PROJECT_ROOT / "config/files_sources.json",
        PROJECT_ROOT / "config/mcps.json",
        PROJECT_ROOT / "config/users.json",
        PROJECT_ROOT / "config/personas/default.md",
        PROJECT_ROOT / "mcps.local.json",
        PROJECT_ROOT / "passwd.json",
        PROJECT_ROOT / "personas/default.md",
        PROJECT_ROOT / "web/index.html",
    ]
    for path in required_files:
        checks.append(
            _check_item(
                f"file_{path.name}",
                "pass" if path.exists() else "fail",
                f"Datei {'vorhanden' if path.exists() else 'fehlt'}: {path}",
            )
        )

    env_file = PROJECT_ROOT / ".env"
    checks.append(
        _check_item(
            "env_file",
            "pass" if env_file.exists() else "warn",
            ".env vorhanden." if env_file.exists() else ".env fehlt (install kopiert .env.example).",
        )
    )

    for directory in (PROJECT_ROOT / "logs", PROJECT_ROOT / "data/cache", PROJECT_ROOT / "config"):
        try:
            directory.mkdir(parents=True, exist_ok=True)
            writable = os.access(directory, os.W_OK)
        except Exception:
            writable = False
        checks.append(
            _check_item(
                f"dir_{directory.name}",
                "pass" if writable else "fail",
                f"Schreibbar: {directory}" if writable else f"Nicht schreibbar: {directory}",
            )
        )

    runtime_json = PROJECT_ROOT / "config/runtime.json"
    try:
        parsed_runtime = json.loads(runtime_json.read_text(encoding="utf-8"))
        runtime_ok = isinstance(parsed_runtime, dict)
    except Exception:
        runtime_ok = False
    checks.append(
        _check_item(
            "runtime_json",
            "pass" if runtime_ok else "fail",
            "runtime.json ist valides JSON." if runtime_ok else "runtime.json ist ungueltig.",
        )
    )

    docs_sources_json = PROJECT_ROOT / "config/docs_sources.json"
    try:
        parsed_sources = json.loads(docs_sources_json.read_text(encoding="utf-8"))
        sources_ok = isinstance(parsed_sources, dict) and isinstance(parsed_sources.get("sources"), list)
    except Exception:
        sources_ok = False
    checks.append(
        _check_item(
            "docs_sources_json",
            "pass" if sources_ok else "fail",
            "docs_sources.json ist valide." if sources_ok else "docs_sources.json ist ungueltig.",
        )
    )

    summary = {
        "passed": sum(1 for item in checks if item["status"] == "pass"),
        "warnings": sum(1 for item in checks if item["status"] == "warn"),
        "failed": sum(1 for item in checks if item["status"] == "fail"),
    }
    return {"checks": checks, "summary": summary}


def cmd_check_prerequisites(args: argparse.Namespace) -> int:
    report = _build_prerequisite_report(args)
    if bool(args.json):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_checks(report, "woddi-ai-control prerequisites")
    return 2 if report["summary"]["failed"] > 0 else 0


def _run(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd or PROJECT_ROOT), check=check, text=True)


def _render_systemd_unit(
    template_path: Path,
    output_path: Path,
    *,
    workdir: Path,
    wanted_by: str,
    user_line: str,
    group_line: str,
) -> None:
    content = template_path.read_text(encoding="utf-8")
    content = content.replace("__WODDI_MONO_WORKDIR__", str(workdir))
    content = content.replace("__WODDI_MONO_WANTED_BY__", wanted_by)
    content = content.replace("__WODDI_MONO_USER_LINE__", user_line)
    content = content.replace("__WODDI_MONO_GROUP_LINE__", group_line)
    output_path.write_text(content, encoding="utf-8")


def _install_systemd_unit(systemd_mode: str, *, enable: bool, start: bool) -> int:
    if systemd_mode == "none":
        return 0
    if shutil.which("systemctl") is None:
        print("[install][error] systemctl fehlt.")
        return 2
    if not SYSTEMD_TEMPLATE.exists():
        print(f"[install][error] Template fehlt: {SYSTEMD_TEMPLATE}")
        return 2

    if systemd_mode == "user":
        unit_dir = Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "systemd/user"
        wanted_by = "default.target"
        user_line = "# user-managed unit"
        group_line = "# user-managed unit"
        systemctl_cmd = ["systemctl", "--user"]
    else:
        if os.geteuid() != 0:
            print("[install][error] --systemd system braucht root.")
            return 2
        service_user = os.getenv("WODDI_MONO_SERVICE_USER", os.getenv("SUDO_USER", "root")).strip() or "root"
        service_group = os.getenv("WODDI_MONO_SERVICE_GROUP", service_user).strip() or service_user
        unit_dir = Path("/etc/systemd/system")
        wanted_by = "multi-user.target"
        user_line = f"User={service_user}"
        group_line = f"Group={service_group}"
        systemctl_cmd = ["systemctl"]

    try:
        unit_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"[install][error] Unit-Verzeichnis nicht beschreibbar: {unit_dir} ({exc})")
        return 2
    unit_path = unit_dir / UNIT_NAME
    try:
        _render_systemd_unit(
            template_path=SYSTEMD_TEMPLATE,
            output_path=unit_path,
            workdir=PROJECT_ROOT,
            wanted_by=wanted_by,
            user_line=user_line,
            group_line=group_line,
        )
    except OSError as exc:
        print(f"[install][error] Unit konnte nicht geschrieben werden: {unit_path} ({exc})")
        return 2
    print(f"[install][info] Unit geschrieben: {unit_path}")
    try:
        _run([*systemctl_cmd, "daemon-reload"])
        if enable:
            _run([*systemctl_cmd, "enable", UNIT_NAME])
        if start:
            _run([*systemctl_cmd, "restart", UNIT_NAME])
    except subprocess.CalledProcessError as exc:
        if systemd_mode == "user" and "daemon-reload" in " ".join(exc.cmd):
            print(f"[install][warn] systemctl --user daemon-reload fehlgeschlagen: {exc}")
            print("[install][warn] Unit wurde trotzdem geschrieben. Reload/Enable/Start spaeter in echter User-Session ausfuehren.")
            return 0
        print(f"[install][error] systemd Aktion fehlgeschlagen: {exc}")
        return 2
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    report = _build_prerequisite_report(args)
    _print_checks(report, "woddi-ai-control install: preflight")
    if report["summary"]["failed"] > 0 and not bool(args.force):
        print("[install][error] Preflight hat harte Fehler. Nutze --force, um trotzdem fortzufahren.")
        return 2

    venv_path = Path(args.venv_path).expanduser() if str(args.venv_path).strip() else DEFAULT_VENV
    if not venv_path.is_absolute():
        venv_path = PROJECT_ROOT / venv_path

    python_bin = _preferred_python_bin()
    if not python_bin:
        print("[install][error] python3/python fehlt.")
        return 2

    try:
        _run([python_bin, "-m", "venv", str(venv_path)])
    except subprocess.CalledProcessError as exc:
        print(f"[install][error] Virtualenv konnte nicht erstellt werden: {exc}")
        return 2

    pip_bin = _venv_pip(venv_path)
    python_venv = _venv_python(venv_path)
    if not pip_bin.exists():
        print(f"[install][error] pip fehlt in {venv_path}")
        return 2
    if not python_venv.exists():
        print(f"[install][error] python fehlt in {venv_path}")
        return 2

    setuptools_ok = subprocess.run(
        [str(python_venv), "-c", "import setuptools, wheel"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    if not setuptools_ok:
        try:
            _run([str(pip_bin), "install", "setuptools", "wheel"])
        except subprocess.CalledProcessError as exc:
            print(f"[install][error] Build-Tooling fehlt und konnte nicht installiert werden: {exc}")
            return 2

    try:
        if not bool(args.no_upgrade_toolchain):
            try:
                _run([str(pip_bin), "install", "--upgrade", "pip", "setuptools", "wheel"])
            except subprocess.CalledProcessError:
                print("[install][warn] Toolchain-Upgrade fehlgeschlagen. Fahre mit bestehender Toolchain fort.")
        _run([str(pip_bin), "install", "--no-build-isolation", "-e", str(PROJECT_ROOT)])
        _run([str(pip_bin), "check"])
    except subprocess.CalledProcessError as exc:
        print(f"[install][error] Python-Installation fehlgeschlagen: {exc}")
        return 2

    env_file = PROJECT_ROOT / ".env"
    env_example = PROJECT_ROOT / ".env.example"
    if not env_file.exists() and env_example.exists():
        env_file.write_text(env_example.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"[install][info] .env aus .env.example erstellt: {env_file}")

    for directory in (
        PROJECT_ROOT / "logs",
        PROJECT_ROOT / "data/cache",
    ):
        directory.mkdir(parents=True, exist_ok=True)

    rc = _install_systemd_unit(
        args.systemd,
        enable=not bool(args.no_enable),
        start=not bool(args.no_start),
    )
    if rc != 0:
        return rc

    print("[install][info] Fertig.")
    print(f"[install][info] Tests: ./{APP_CMD} check-prerequisites")
    print(f"[install][info] Start: ./{APP_CMD} start")
    return 0


def _load_pid() -> int | None:
    if not LOCAL_PID.exists():
        return None
    try:
        return int(LOCAL_PID.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _local_python_for_service() -> str:
    venv_python = _venv_python(DEFAULT_VENV)
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _spawn_local_service(host: str, port: int) -> subprocess.Popen[str]:
    LOCAL_PID.parent.mkdir(parents=True, exist_ok=True)
    stdout = LOCAL_STDOUT.open("a", encoding="utf-8")
    return subprocess.Popen(
        [
            _local_python_for_service(),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=str(PROJECT_ROOT),
        stdout=stdout,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _service_mode(args: argparse.Namespace) -> str:
    requested = str(getattr(args, "mode", "auto") or "auto").strip().lower()
    if requested in {"local", "user", "system"}:
        return requested
    if shutil.which("systemctl") is not None:
        user_unit = subprocess.run(
            ["systemctl", "--user", "status", UNIT_NAME],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if user_unit.returncode in {0, 3, 4}:
            return "user"
        system_unit = subprocess.run(
            ["systemctl", "status", UNIT_NAME],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if system_unit.returncode in {0, 3, 4}:
            return "system"
    return "local"


def _systemctl_cmd(mode: str) -> list[str]:
    return ["systemctl", "--user"] if mode == "user" else ["systemctl"]


def _local_start() -> int:
    pid = _load_pid()
    if pid and _pid_running(pid):
        print(f"[service][info] Bereits aktiv (pid={pid})")
        return 0
    current_settings = load_settings()
    host = current_settings.host
    port = current_settings.port
    process = _spawn_local_service(host, port)
    time.sleep(1.0)
    if process.poll() is not None and host == "0.0.0.0":
        process = _spawn_local_service("127.0.0.1", port)
        time.sleep(1.0)
        if process.poll() is None:
            LOCAL_PID.write_text(f"{process.pid}\n", encoding="utf-8")
            print(f"[service][warn] 0.0.0.0 nicht bindbar, fallback auf 127.0.0.1 (pid={process.pid}, log={LOCAL_STDOUT})")
            return 0
    if process.poll() is not None:
        LOCAL_PID.unlink(missing_ok=True)
        if LOCAL_STDOUT.exists():
            tail_lines = LOCAL_STDOUT.read_text(encoding="utf-8", errors="replace").splitlines()[-4:]
            if tail_lines:
                print("[service][error] Start fehlgeschlagen. Letzte Logzeilen:")
                for line in tail_lines:
                    print(line)
                return 2
        print(f"[service][error] Start fehlgeschlagen. Siehe Log: {LOCAL_STDOUT}")
        return 2
    LOCAL_PID.write_text(f"{process.pid}\n", encoding="utf-8")
    print(f"[service][info] Gestartet (pid={process.pid}, log={LOCAL_STDOUT})")
    return 0


def _local_stop() -> int:
    pid = _load_pid()
    if not pid:
        print("[service][warn] Kein lokaler PID gefunden.")
        return 0
    if not _pid_running(pid):
        LOCAL_PID.unlink(missing_ok=True)
        print("[service][warn] Prozess laeuft nicht mehr.")
        return 0
    os.kill(pid, signal.SIGTERM)
    for _ in range(30):
        if not _pid_running(pid):
            LOCAL_PID.unlink(missing_ok=True)
            print(f"[service][info] Gestoppt (pid={pid})")
            return 0
        time.sleep(0.2)
    os.kill(pid, signal.SIGKILL)
    LOCAL_PID.unlink(missing_ok=True)
    print(f"[service][warn] Prozess hart beendet (pid={pid})")
    return 0


def _local_status() -> int:
    pid = _load_pid()
    if not pid:
        print("[service][info] Lokal: nicht gestartet")
        return 3
    if not _pid_running(pid):
        LOCAL_PID.unlink(missing_ok=True)
        print("[service][info] Lokal: nicht gestartet (stale pid entfernt)")
        return 3
    print(f"[service][info] Lokal aktiv (pid={pid}, log={LOCAL_STDOUT})")
    return 0


def cmd_service(args: argparse.Namespace) -> int:
    mode = _service_mode(args)
    action = str(args.service_action).strip().lower()
    if mode in {"user", "system"}:
        cmd = _systemctl_cmd(mode)
        unit = UNIT_NAME
        try:
            if action == "start":
                _run([*cmd, "start", unit])
            elif action == "stop":
                _run([*cmd, "stop", unit])
            elif action == "restart":
                _run([*cmd, "restart", unit])
            elif action == "status":
                result = subprocess.run([*cmd, "--no-pager", "--full", "status", unit], check=False)
                return result.returncode
            else:
                print(f"[service][error] Unbekannte Action: {action}")
                return 2
        except subprocess.CalledProcessError as exc:
            print(f"[service][error] systemctl fehlgeschlagen: {exc}")
            return 2
        print(f"[service][info] {action} ueber systemd ({mode}) ausgefuehrt.")
        return 0

    if action == "start":
        return _local_start()
    if action == "stop":
        return _local_stop()
    if action == "restart":
        _local_stop()
        return _local_start()
    if action == "status":
        return _local_status()
    print(f"[service][error] Unbekannte Action: {action}")
    return 2


def cmd_start(args: argparse.Namespace) -> int:
    import uvicorn

    settings = load_settings()
    host = str(args.host or settings.host)
    port = int(args.port or settings.port)
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="woddi-ai-control")
    parser.add_argument("--status", action="store_true", help="Zeigt Kurzstatus und endet.")
    subparsers = parser.add_subparsers(dest="command")

    start_parser = subparsers.add_parser("start", help="Startet den Monolithen im Vordergrund.")
    start_parser.add_argument("--host", default="")
    start_parser.add_argument("--port", type=int, default=0)

    service_parser = subparsers.add_parser("service", help="Start/Stop/Status fuer Hintergrundbetrieb.")
    service_parser.add_argument("service_action", choices=["start", "stop", "restart", "status"])
    service_parser.add_argument("--mode", default="auto", choices=["auto", "local", "user", "system"])

    install_parser = subparsers.add_parser("install", help="Installiert venv, Python-Dependencies und optional systemd.")
    install_parser.add_argument("--venv-path", default=str(DEFAULT_VENV))
    install_parser.add_argument("--systemd", default="none", choices=["none", "user", "system"])
    install_parser.add_argument("--no-enable", action="store_true")
    install_parser.add_argument("--no-start", action="store_true")
    install_parser.add_argument("--no-upgrade-toolchain", action="store_true")
    install_parser.add_argument("--force", action="store_true")

    prereq_parser = subparsers.add_parser("check-prerequisites", help="Prueft lokale Voraussetzungen.")
    prereq_parser.add_argument("--systemd", default="none", choices=["none", "user", "system"])
    prereq_parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if bool(args.status) and not args.command:
        return cmd_service(argparse.Namespace(service_action="status", mode="auto"))

    if args.command == "start":
        return cmd_start(args)
    if args.command == "service":
        return cmd_service(args)
    if args.command == "install":
        return cmd_install(args)
    if args.command == "check-prerequisites":
        return cmd_check_prerequisites(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
