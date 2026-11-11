"""Windows login startup and console-free process options."""
import os
from pathlib import Path
import subprocess
import sys


def hidden_process():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def executable_command():
    if getattr(sys, "frozen", False):
        return [sys.executable]
    interpreter = Path(sys.executable)
    if os.name == "nt" and interpreter.with_name("pythonw.exe").exists():
        interpreter = interpreter.with_name("pythonw.exe")
    return [str(interpreter), str(Path(__file__).resolve().parents[1] / "run_manager.py")]


def login_start(enabled, directory):
    if os.name != "nt":
        return
    import winreg
    command = subprocess.list2cmdline(executable_command() + ["--background", "--data-dir", str(directory)])
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        if enabled:
            winreg.SetValueEx(key, "LlamaCppInstanceManager", 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, "LlamaCppInstanceManager")
            except FileNotFoundError:
                pass


def configure_firewall(store):
    """Ask Windows to allow the selected LAN ports on private networks."""
    if os.name != "nt":
        return {"ok": True}
    config = store.read()
    ports = sorted({config["port"]} | {port for row in config["instances"] for port in (row["gui_port"], row["api_port"])})
    group = "LlamaCppManager-" + str(__import__("uuid").UUID(config["id"]))
    script = store.directory / "configure-firewall.ps1"
    script.write_text("$ErrorActionPreference = 'Stop'\n"
        + f"Get-NetFirewallRule -Group '{group}' -ErrorAction SilentlyContinue | Remove-NetFirewallRule\n"
        + f"New-NetFirewallRule -DisplayName 'llama.cpp Instance Manager TCP' -Group '{group}' -Direction Inbound -Action Allow -Protocol TCP -LocalPort {','.join(str(int(p)) for p in ports)} -Profile Private -RemoteAddress LocalSubnet | Out-Null\n"
        + f"New-NetFirewallRule -DisplayName 'llama.cpp Manager discovery' -Group '{group}' -Direction Inbound -Action Allow -Protocol UDP -LocalPort 5238 -Profile Private -RemoteAddress LocalSubnet | Out-Null\n", encoding="utf-8")
    arguments = subprocess.list2cmdline(["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)])
    escaped = arguments.replace("'", "''")
    command = f"$p = Start-Process powershell.exe -ArgumentList '{escaped}' -Verb RunAs -WindowStyle Hidden -Wait -PassThru; exit $p.ExitCode"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=120, **hidden_process())
    if result.returncode:
        raise ValueError("Windows Firewall configuration was not completed. Use Allow LAN access in Settings to try again.")
    return {"ok": True}
