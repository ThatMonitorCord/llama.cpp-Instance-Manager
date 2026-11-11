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
