"""Install and control independent upstream checkouts. Never edit upstream code."""
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid

import psutil

from .config import UPSTREAM, label, port_available, port_number
from .platform import hidden_process
from .transport import request

APP_ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
RESOURCES = Path(__file__).resolve().parent


def tool(name):
    bundled = APP_ROOT / "runtimes" / name
    if name == "git":
        bundled = bundled / "cmd" / "git.exe"
    elif name == "python":
        bundled = bundled / "python.exe"
    elif name == "node":
        bundled = bundled / "node.exe"
    if bundled.exists():
        return str(bundled)
    found = shutil.which(name)
    if found:
        return found
    raise ValueError(f"{name} is unavailable. Reinstall the manager using the Windows setup executable.")


def venv_python(root):
    return Path(root) / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def process_for(instance):
    expected = os.path.normcase(str(venv_python(instance["path"]).resolve()))
    script = os.path.normcase(str((Path(instance["path"]) / "server.py").resolve()))
    for process in psutil.process_iter(["exe", "cmdline"]):
        try:
            command = process.info["cmdline"] or []
            executable = os.path.normcase(process.info["exe"] or "")
            # Windows venv launchers can expose the base executable; command[0]
            # still identifies this instance's interpreter.
            interpreter = os.path.normcase(command[0]) if command else ""
            if expected in (executable, interpreter) and any(os.path.normcase(arg) == script for arg in command[1:]):
                return process
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


class Instances:
    def __init__(self, store):
        self.store = store
        self.locks = {}
        self.guard = threading.Lock()
        self.errors = {}
        self.children = {}
        self.jobs = {}
        self.active_install = False
        self.launches = {}

    def lock(self, identity):
        with self.guard:
            return self.locks.setdefault(identity, threading.Lock())

    def api(self, instance, route, body=None, **kwargs):
        return request(f"http://127.0.0.1:{instance['gui_port']}{route}", body, **kwargs)

    def job(self, title, function):
        identity = str(uuid.uuid4())
        with self.guard:
            self.jobs[identity] = {"id": identity, "title": title, "state": "running", "message": "Starting…"}
            for key in list(self.jobs)[:-30]:
                if self.jobs[key]["state"] != "running":
                    self.jobs.pop(key)
        def progress(message):
            with self.guard:
                self.jobs[identity]["message"] = str(message)[-3000:]
        def run():
            try:
                result = function(progress)
                with self.guard:
                    self.jobs[identity].update(state="complete", message="Complete", result=result)
            except Exception as exc:
                logging.exception("%s failed", title)
                with self.guard:
                    self.jobs[identity].update(state="error", message=str(exc))
        threading.Thread(target=run, daemon=True).start()
        return {"job": identity}

    def job_list(self):
        with self.guard:
            return [dict(row) for row in self.jobs.values()]

    def plan(self, rows, directory):
        if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
            raise ValueError("Choose between 1 and 100 instances.")
        destination = Path(directory).expanduser()
        if not destination.is_absolute():
            raise ValueError("Choose an absolute installation folder.")
        config = self.store.read()
        used = {config["port"]}
        for instance in config["instances"]:
            used.update((instance["gui_port"], instance["api_port"]))
        instances = []
        for row in rows:
            name = label(row.get("name"), "Instance name")
            gui, api = port_number(row.get("gui_port")), port_number(row.get("api_port"))
            for port in (gui, api):
                if port in used:
                    raise ValueError(f"Port {port} is assigned more than once.")
                if not port_available(port):
                    raise ValueError(f"Port {port} is unavailable. Choose another port.")
                used.add(port)
            identity = str(uuid.uuid4())
            instances.append({"id": identity, "name": name, "gui_port": gui, "api_port": api,
                              "path": str(destination.resolve() / identity[:8] / "LLama-GUI"),
                              "preset": "", "auto_start": False, "install_state": "pending"})
        return instances

    def install(self, rows, directory, models_dir=""):
        with self.guard:
            if self.active_install:
                raise ValueError("An installation is already in progress.")
            planned = self.plan(rows, directory)
            if models_dir and not Path(models_dir).is_absolute():
                raise ValueError("Choose an absolute shared models folder.")
            self.active_install = True
        def register(config):
            config["instances"].extend(planned)
            config["instances_dir"] = str(Path(directory).resolve())
        try:
            self.store.change(register)
        except Exception:
            with self.guard:
                self.active_install = False
            raise
        def run(progress):
            try:
                if models_dir:
                    Path(models_dir).mkdir(parents=True, exist_ok=True)
                failures = []
                for instance in planned:
                    try:
                        self.install_one(instance, models_dir, progress)
                    except Exception as exc:
                        logging.exception("Instance installation failed")
                        self.store.update_instance(instance["id"], install_state="error", install_error=str(exc), models_dir=models_dir)
                        failures.append(f"{instance['name']}: {exc}")
                if failures:
                    raise ValueError("\n".join(failures))
                return {"instances": [row["id"] for row in planned]}
            finally:
                with self.guard:
                    self.active_install = False
        return self.job("Install llama.cpp instances", run)

    def command(self, args, cwd, progress, env=None):
        completed = subprocess.run([str(arg) for arg in args], cwd=cwd, env=env, capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", timeout=900, **hidden_process())
        if completed.returncode:
            raise ValueError((completed.stderr or completed.stdout or "Command failed")[-3000:])
        progress("Dependencies installed" if "pip" in args else "Preparing instance")

    def install_one(self, instance, models_dir, progress):
        root = Path(instance["path"])
        root.parent.mkdir(parents=True, exist_ok=True)
        self.store.update_instance(instance["id"], install_state="installing", install_error="", models_dir=models_dir)
        progress(f"{instance['name']}: downloading upstream LLama-GUI")
        if not (root / "server.py").is_file():
            # Git can leave its metadata behind after an interrupted clone.
            # Resume only a checkout that still points to the intended upstream.
            if (root / ".git").exists():
                existing = subprocess.run([tool("git"), "-C", str(root), "remote", "get-url", "origin"],
                                          capture_output=True, text=True, timeout=20, **hidden_process())
                if existing.returncode or existing.stdout.strip() != UPSTREAM:
                    raise ValueError("The incomplete checkout does not point to upstream LLama-GUI.")
                self.command([tool("git"), "fetch", "origin", "main"], root, progress)
                self.command([tool("git"), "checkout", "-B", "main", "origin/main"], root, progress)
        if not (root / ".git").exists():
            if root.exists() and any(root.iterdir()):
                raise ValueError(f"Incomplete checkout at {root}. Choose a new instance folder or clear the incomplete checkout before retrying.")
            self.command([tool("git"), "clone", "--", UPSTREAM, str(root)], root.parent, progress)
        # Each instance owns its runtime files too. No links to another instance.
        for name in ("python", "git"):
            source = APP_ROOT / "runtimes" / name
            destination = root.parent / "runtime" / name
            if source.exists():
                progress(f"{instance['name']}: copying its {name} runtime")
                shutil.copytree(source, destination, dirs_exist_ok=True)
        base = root.parent / "runtime/python/python.exe"
        python = str(base) if base.exists() else tool("python")
        interpreter = venv_python(root)
        pip_ready = interpreter.exists() and subprocess.run([str(interpreter), "-m", "pip", "--version"],
            capture_output=True, timeout=20, **hidden_process()).returncode == 0
        if not pip_ready:
            progress(f"{instance['name']}: creating its Python environment")
            self.command([python, "-m", "venv", str(root / ".venv")], root, progress)
        progress(f"{instance['name']}: installing dependencies")
        self.command([str(interpreter), "-m", "pip", "install", "-r", "requirements.txt"], root, progress, self.environment(instance))
        # These are normal user settings, not patches to application files.
        config_file = root / "config.json"
        settings = json.loads(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
        if models_dir:
            settings["models_dir"] = str(Path(models_dir).resolve())
        config_file.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        presets = root / "presets"
        presets.mkdir(exist_ok=True)
        defaults = presets / "Manager defaults.json"
        if not defaults.exists():
            defaults.write_text(json.dumps({"tool": "llama-server", "model": "", "flags": {
                "port": instance["api_port"], "host": "0.0.0.0", "metrics": True, "slots_endpoint": True}}, indent=2), encoding="utf-8")
        self.write_launcher(instance)
        self.store.update_instance(instance["id"], install_state="ready", install_error="")
        progress(f"{instance['name']}: opening its control panel")
        self.control(instance["id"], "panel")

    def environment(self, instance):
        env = os.environ.copy()
        git = Path(instance["path"]).parent / "runtime/git/cmd"
        env["PATH"] = str(git) + os.pathsep + str(Path(tool("git")).parent) + os.pathsep + env.get("PATH", "")
        env.update(LLAMA_GUI_HOST="0.0.0.0", LLAMA_GUI_PORT=str(instance["gui_port"]),
                   LLAMA_GUI_ALLOWED_HOSTS=f"{socket.gethostname()},{socket.gethostname()}.local",
                   LLAMA_GUI_SUPERVISED="0", PYTHONIOENCODING="utf-8")
        env.pop("PYTHONHOME", None)
        env.pop("PYTHONPATH", None)
        return env

    def write_launcher(self, instance):
        # Stored beside the checkout so upstream git status/update stays clean.
        if os.name != "nt":
            return
        root = Path(instance["path"])
        content = f'''@echo off
setlocal
cd /d "%~dp0LLama-GUI"
set "LLAMA_GUI_HOST=0.0.0.0"
set "LLAMA_GUI_PORT={instance['gui_port']}"
set "LLAMA_GUI_ALLOWED_HOSTS={socket.gethostname()},{socket.gethostname()}.local"
set "PATH=%~dp0runtime\\git\\cmd;%PATH%"
start "" ".venv\\Scripts\\pythonw.exe" "%~dp0LLama-GUI\\server.py"
start "" "http://127.0.0.1:{instance['gui_port']}/?preset=Manager%%20defaults"
'''
        (root.parent / "Open instance.cmd").write_text(content, encoding="utf-8")

    def panel(self, instance):
        if process_for(instance):
            return self.wait_ready(instance)
        if not port_available(instance["gui_port"]):
            raise ValueError(f"Control-panel port {instance['gui_port']} is in use by another process.")
        root = Path(instance["path"])
        if not venv_python(root).exists():
            raise ValueError("Instance installation is incomplete. Use Retry installation.")
        log_dir = root.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        with (log_dir / "control-panel.log").open("a", encoding="utf-8") as log:
            child = subprocess.Popen([str(venv_python(root)), str(root / "server.py")], cwd=root,
                                     env=self.environment(instance), stdout=log, stderr=log, **hidden_process())
        self.children[instance["id"]] = child
        return self.wait_ready(instance, child)

    def wait_ready(self, instance, child=None):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if child and child.poll() is not None:
                raise ValueError(f"Control panel exited ({child.returncode}). See {Path(instance['path']).parent / 'logs/control-panel.log'}")
            try:
                status = self.api(instance, "/api/status", timeout=2)
                if "running" in status and "models_dir" in status:
                    return status
            except (OSError, ValueError) as exc:
                logging.debug("Waiting for %s: %s", instance["name"], exc)
            time.sleep(0.4)
        raise ValueError("The control panel did not become ready within 60 seconds.")

    def presets(self, instance):
        root = Path(instance["path"]) / "presets"
        rows = []
        if root.exists():
            for path in sorted(root.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if data.get("tool") == "llama-server" and isinstance(data.get("flags"), dict):
                        rows.append({"name": path.stem, "data": data})
                except (OSError, ValueError, AttributeError) as exc:
                    logging.debug("Skipped preset %s: %s", path, exc)
        return rows

    def compile_preset(self, instance, status):
        preset = next((row for row in self.presets(instance) if row["name"] == instance["preset"]), None)
        if not preset:
            raise ValueError("Select a saved model/server preset in Startup settings first.")
        data = {"root": instance["path"], "status": status, "preset": preset["data"]}
        completed = subprocess.run([tool("node"), str(RESOURCES / "preset_bridge.cjs")], input=json.dumps(data),
                                   capture_output=True, text=True, encoding="utf-8", timeout=20, **hidden_process())
        if completed.returncode:
            raise ValueError("Could not load the saved preset: " + completed.stderr[-1500:])
        launch = json.loads(completed.stdout)
        launch["fingerprint_data"] = preset["data"]
        args = launch["args"]
        if not any(arg in ("-m", "--model", "-hf", "--hf-repo", "-mu", "--model-url") or arg.startswith(("--model=", "--hf-repo=", "--model-url=")) for arg in args):
            raise ValueError("Choose a model in the instance and save a model/server preset first.")
        # Preserve the saved preset's actual port, including custom launch args.
        port = 8080
        for index, arg in enumerate(args):
            if arg == "--port" and index + 1 < len(args):
                port = port_number(args[index + 1])
            elif arg.startswith("--port="):
                port = port_number(arg.split("=", 1)[1])
        if not port_available(port):
            raise ValueError(f"Preset inference port {port} is in use. Change the port in the instance's saved preset.")
        return launch

    def control(self, instance_id, action):
        if action not in ("panel", "start", "stop", "restart", "retry"):
            raise ValueError("Unknown instance action.")
        with self.lock(instance_id):
            instance = self.store.instance(instance_id)
            try:
                if action == "retry":
                    # install_one opens the panel; avoid recursively taking this lock.
                    raise ValueError("Use the installation retry endpoint.")
                if action in ("stop", "restart"):
                    if process_for(instance):
                        self.api(instance, "/api/shutdown", {}, timeout=20)
                        deadline = time.monotonic() + 25
                        while process_for(instance) and time.monotonic() < deadline:
                            time.sleep(0.3)
                        if process_for(instance):
                            raise ValueError("Instance did not stop. Open its control panel to check the process.")
                    self.launches.pop(instance_id, None)
                    self.store.update_instance(instance_id, last_launch=None)
                    if action == "stop":
                        self.errors.pop(instance_id, None)
                        return {"stopped": True}
                status = self.panel(instance)
                if action != "panel" and not status["running"]:
                    launch = self.compile_preset(instance, status)
                    self.api(instance, "/api/launch/preflight", launch, timeout=30)
                    started = self.api(instance, "/api/launch", launch, timeout=30)
                    process = process_for(instance)
                    self.launches[instance_id] = {"generation": started.get("active_runtime", {}).get("generation"),
                                                 "pid": process.pid if process else None, "preset": instance["preset"]}
                    self.store.update_instance(instance_id, last_launch=self.launches[instance_id])
                    deadline = time.monotonic() + 300
                    while time.monotonic() < deadline:
                        health = self.api(instance, "/api/llama/health", timeout=5)
                        if health.get("ready"):
                            break
                        if health.get("state") in ("stopped", "error"):
                            raise ValueError(health.get("message") or "Model failed to start.")
                        time.sleep(1)
                    else:
                        raise ValueError("Model is still loading after five minutes. Open the instance to inspect its output.")
                self.errors.pop(instance_id, None)
                return {"ok": True}
            except Exception as exc:
                self.errors[instance_id] = str(exc)
                raise

    def sample(self, instance):
        result = {**instance, "online": False, "running": False, "error": self.errors.get(instance["id"], "")}
        process = process_for(instance)
        if not process:
            return result
        result["pid"] = process.pid
        try:
            status = self.api(instance, "/api/status", timeout=2)
            result.update(online=True, running=bool(status.get("running")), status=status)
            runtime = status.get("active_runtime") or {}
            launch = self.launches.get(instance["id"]) or instance.get("last_launch") or {}
            result["loaded_preset"] = runtime.get("preset") or (launch.get("preset") if launch.get("pid") == process.pid and launch.get("generation") == runtime.get("generation") else None)
            if status.get("running") and status.get("active_process_tool") == "llama-server":
                for route, key, is_text in (("metrics", "metrics", True), ("slots", "slots", False)):
                    try:
                        result[key] = self.api(instance, "/api/llama/" + route, text=is_text, timeout=2)
                    except (OSError, ValueError) as exc:
                        logging.debug("%s unavailable: %s", key, exc)
            result["sampled_at"] = time.time()
        except (OSError, ValueError) as exc:
            result["error"] = str(exc)
        return result

    def snapshot(self):
        rows = self.store.read()["instances"]
        with ThreadPoolExecutor(max_workers=min(12, max(1, len(rows)))) as pool:
            instances = list(pool.map(self.sample, rows))
        system = None
        for row in instances:
            if row["online"]:
                try:
                    system = self.api(row, "/api/system-stats", timeout=3)
                    break
                except (OSError, ValueError) as exc:
                    logging.debug("Hardware sample unavailable: %s", exc)
        return {"instances": instances, "system": system}
