"""Manager HTTP server, local snapshots, direct peer aggregation, and setup."""
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import logging
from logging.handlers import RotatingFileHandler
import mimetypes
import os
from pathlib import Path
import socket
import threading
import time
import urllib.parse
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import VERSION
from .config import Store, REPOSITORY, data_directory, label, next_port, port_available, port_number, suggest_ports
from .discovery import Discovery
from .instances import Instances, process_for
from .platform import login_start
from .transport import manager_url, request

WEB = Path(__file__).resolve().parent / "web"


class Manager:
    def __init__(self, store):
        self.store = store
        self.instances = Instances(store)
        self.discovery = Discovery(self.info)
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.server = None
        self.rebind = False
        self.local = {**self.info(), "instances": [], "system": None, "sampled_at": 0}
        self.peers = []

    def info(self):
        config = self.store.read()
        return {"product": "llama.cpp-instance-manager", "api_version": 1, "version": VERSION,
                "id": config["id"], "name": config["name"], "port": config["port"]}

    def start(self):
        self.discovery.start()
        threading.Thread(target=self.poll_local, daemon=True).start()
        threading.Thread(target=self.poll_peers, daemon=True).start()
        for row in self.store.read()["instances"]:
            if row.get("install_state") == "installing":
                self.store.update_instance(row["id"], install_state="error", install_error="Installation was interrupted. Retry to continue.")
            if row.get("auto_start") and row.get("install_state") == "ready":
                self.instances.job(f"Start {row['name']}", lambda progress, identity=row["id"]: self.instances.control(identity, "start"))

    def poll_local(self):
        while not self.stop_event.is_set():
            try:
                snapshot = {**self.info(), **self.instances.snapshot(), "sampled_at": time.time(), "online": True}
                with self.lock:
                    self.local = snapshot
            except Exception:
                logging.exception("Local snapshot failed")
            self.stop_event.wait(2)

    def peer_sample(self, peer):
        try:
            data = request(peer["url"] + "/api/state", timeout=4)
            if data.get("product") != "llama.cpp-instance-manager" or data.get("api_version") != 1 or data.get("id") != peer["id"]:
                raise ValueError("This address is not the connected manager or uses an incompatible version.")
            return {**data, "url": peer["url"], "online": True}
        except (OSError, ValueError, AttributeError) as exc:
            return {**peer, "online": False, "instances": [], "system": None, "error": str(exc)}

    def poll_peers(self):
        while not self.stop_event.is_set():
            peers = self.store.read()["peers"]
            with ThreadPoolExecutor(max_workers=min(12, max(1, len(peers)))) as pool:
                rows = list(pool.map(self.peer_sample, peers))
            with self.lock:
                self.peers = rows
            self.stop_event.wait(2)

    def fleet(self):
        with self.lock:
            local = copy.deepcopy(self.local)
            local.update(self.info(), local=True)
            peers = copy.deepcopy(self.peers)
        # A connected peer reports only its local instances: never recurse.
        connected = {p["id"] for p in self.store.read()["peers"]}
        seen = {local["id"]}
        servers = [local]
        for peer in peers:
            if peer["id"] in connected and peer["id"] not in seen:
                servers.append(peer)
                seen.add(peer["id"])
        return {"servers": servers, "jobs": self.instances.job_list()}

    def connect(self, address):
        url = manager_url(address)
        info = request(url + "/api/info")
        if info.get("product") != "llama.cpp-instance-manager" or info.get("api_version") != 1:
            raise ValueError("No compatible instance manager was found at this address.")
        if info["id"] == self.info()["id"]:
            raise ValueError("This is your local manager.")
        def save(config):
            config["peers"] = [row for row in config["peers"] if row["id"] != info["id"]]
            config["peers"].append({"id": info["id"], "name": info["name"], "url": url})
        self.store.change(save)
        return info

    def settings(self, body):
        current = self.store.read()
        name = label(body.get("name", current["name"]), "Server name")
        port = port_number(body.get("port", current["port"]))
        enabled = body.get("login_start", current["login_start"])
        if not isinstance(enabled, bool):
            raise ValueError("Invalid login startup setting.")
        if port != current["port"]:
            if any(port in (row["gui_port"], row["api_port"]) for row in current["instances"]) or not port_available(port):
                raise ValueError(f"Manager port {port} is already in use or assigned to an instance.")
        login_start(enabled, self.store.directory)
        self.store.change(lambda config: config.update(name=name, port=port, login_start=enabled))
        if port != current["port"]:
            self.rebind = True
        return {"ok": True, "port": port}

    def setup(self, body):
        # Validate everything before writing settings or starting downloads.
        current = self.store.read()
        if current["configured"]:
            raise ValueError("Setup is already complete. Use Add instances.")
        target_port = port_number(body.get("port"))
        rows = body.get("instances")
        if isinstance(rows, list) and any(target_port in (int(row.get("gui_port", 0)), int(row.get("api_port", 0))) for row in rows):
            raise ValueError("The manager and instances must have different ports.")
        self.instances.plan(rows, body.get("directory", ""))
        shared = str(body.get("models_dir", "")).strip()
        if shared and not Path(shared).is_absolute():
            raise ValueError("Choose an absolute shared models folder.")
        self.settings(body)
        result = self.instances.install(rows, body["directory"], shared)
        self.store.change(lambda config: config.update(configured=True))
        return {**result, "port": target_port}

    def action(self, body):
        server_id = body.get("server_id", self.info()["id"])
        identity, action = body.get("instance_id"), body.get("action")
        if action not in ("start", "stop", "restart", "panel", "retry"):
            raise ValueError("Unknown instance action.")
        if server_id != self.info()["id"]:
            if action not in ("start", "stop", "restart"):
                raise ValueError("Open the remote instance for additional controls.")
            peer = next((row for row in self.store.read()["peers"] if row["id"] == server_id), None)
            if not peer:
                raise ValueError("Manager is not connected.")
            result = request(peer["url"] + "/api/action", {"instance_id": identity, "action": action}, timeout=6)
            # Track the remote job so failure details appear in the initiating UI.
            def follow(progress):
                for _ in range(360):
                    jobs = request(peer["url"] + "/api/jobs", timeout=5)
                    job = next((row for row in jobs if row["id"] == result["job"]), None)
                    if job:
                        progress(job["message"])
                        if job["state"] == "error":
                            raise ValueError(job["message"])
                        if job["state"] == "complete":
                            return {"ok": True}
                    time.sleep(1)
                raise ValueError("Remote operation timed out. Check the remote manager.")
            return self.instances.job(f"{action.title()} remote instance", follow)
        instance = self.store.instance(identity)
        if action == "retry":
            with self.instances.guard:
                if self.instances.active_install:
                    raise ValueError("An installation is already running.")
                self.instances.active_install = True
            def retry(progress):
                try:
                    self.instances.install_one(instance, instance.get("models_dir", ""), progress)
                except Exception as exc:
                    self.store.update_instance(identity, install_state="error", install_error=str(exc))
                    raise
                finally:
                    with self.instances.guard:
                        self.instances.active_install = False
            return self.instances.job("Retry installation", retry)
        return self.instances.job(f"{action.title()} {instance['name']}", lambda progress: self.instances.control(identity, action))

    def startup(self, body):
        instance = self.store.instance(body.get("instance_id"))
        preset = str(body.get("preset", ""))
        if preset and preset not in [row["name"] for row in self.instances.presets(instance)]:
            raise ValueError("Saved server preset not found.")
        auto = body.get("auto_start", False)
        if not isinstance(auto, bool) or (auto and not preset):
            raise ValueError("Choose a saved model/server preset before enabling auto-start.")
        self.store.update_instance(instance["id"], preset=preset, auto_start=auto)
        return {"ok": True}

    def logs(self, identity, server_id=None):
        if server_id and server_id != self.info()["id"]:
            peer = next((row for row in self.store.read()["peers"] if row["id"] == server_id), None)
            if not peer:
                raise ValueError("Manager is not connected.")
            return request(peer["url"] + "/api/logs?instance_id=" + urllib.parse.quote(identity))
        instance = self.store.instance(identity)
        if process_for(instance):
            return self.instances.api(instance, "/api/output")
        path = Path(instance["path"]).parent / "logs/control-panel.log"
        if not path.exists():
            return {"lines": []}
        with path.open("rb") as handle:
            handle.seek(max(0, path.stat().st_size - 32000))
            return {"lines": handle.read().decode("utf-8", errors="replace").splitlines()[-200:]}

    def update(self):
        req = urllib.request.Request(f"https://api.github.com/repos/{REPOSITORY}/releases/latest", headers={"User-Agent": "llama.cpp-Instance-Manager"})
        with urllib.request.urlopen(req, timeout=15) as response:
            release = json.load(response)
        installer = next((asset for asset in release.get("assets", []) if asset["name"].endswith("-setup.exe")), None)
        return {"current": VERSION, "latest": release["tag_name"].lstrip("v"), "url": release["html_url"],
                "download": installer["browser_download_url"] if installer else None}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def manager(self):
        return self.server.manager

    def log_message(self, format, *args):
        logging.debug(format, *args)

    def send(self, value, status=200, content_type="application/json"):
        data = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        query = {key: values[0] for key, values in urllib.parse.parse_qs(parsed.query).items()}
        app = self.manager
        try:
            if parsed.path == "/api/info":
                return self.send(app.info())
            if parsed.path == "/api/config":
                return self.send(app.store.read())
            if parsed.path == "/api/fleet":
                return self.send(app.fleet())
            if parsed.path == "/api/state":
                with app.lock:
                    data = copy.deepcopy(app.local)
                data.update(app.info())
                return self.send(data)
            if parsed.path == "/api/jobs":
                return self.send(app.instances.job_list())
            if parsed.path == "/api/discovery":
                return self.send({"managers": app.discovery.scan(), "error": app.discovery.error})
            if parsed.path == "/api/ports":
                config = app.store.read()
                used = [port for row in config["instances"] for port in (row["gui_port"], row["api_port"])]
                return self.send(suggest_ports(query.get("count", 1), config["port"], used))
            if parsed.path == "/api/presets":
                instance = app.store.instance(query.get("instance_id"))
                return self.send([row["name"] for row in app.instances.presets(instance)])
            if parsed.path == "/api/logs":
                return self.send(app.logs(query.get("instance_id"), query.get("server_id")))
            if parsed.path == "/api/update":
                return self.send(app.update())
            if parsed.path.startswith("/api/"):
                return self.send({"error": "Endpoint not found"}, 404)
            relative = urllib.parse.unquote(parsed.path).lstrip("/") or "index.html"
            target = (WEB / relative).resolve()
            if not target.is_relative_to(WEB.resolve()) or not target.is_file():
                return self.send({"error": "Not found"}, 404)
            mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            return self.send(target.read_bytes(), content_type=mime + ("; charset=utf-8" if mime.startswith("text/") else ""))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            logging.debug("GET failed: %s", exc)
            self.send({"error": str(exc)}, 400)

    def do_POST(self):
        try:
            self.connection.settimeout(15)
            if self.headers.get("Transfer-Encoding"):
                self.close_connection = True
                return self.send({"error": "Transfer-Encoding is not supported"}, 400)
            length = int(self.headers.get("Content-Length", 0))
            if not 0 <= length <= 1024 * 1024:
                self.close_connection = True
                return self.send({"error": "Request too large"}, 413)
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object.")
            app = self.manager
            routes = {"/api/setup": app.setup, "/api/settings": app.settings, "/api/action": app.action,
                      "/api/startup": app.startup, "/api/connect": lambda data: app.connect(data.get("url")),
                      "/api/install": lambda data: app.instances.install(data.get("instances"), data.get("directory", ""), data.get("models_dir", ""))}
            if self.path in routes:
                result = routes[self.path](body)
            elif self.path == "/api/disconnect":
                app.store.change(lambda config: config.update(peers=[row for row in config["peers"] if row["id"] != body.get("id")]))
                result = {"ok": True}
            elif self.path == "/api/remove":
                instance = app.store.instance(body.get("instance_id"))
                if process_for(instance) or instance.get("install_state") in ("pending", "installing"):
                    raise ValueError("Stop the instance and wait for installation to finish before removing it.")
                app.store.change(lambda config: config.update(instances=[row for row in config["instances"] if row["id"] != instance["id"]]))
                result = {"ok": True}
            else:
                return self.send({"error": "Endpoint not found"}, 404)
            self.send(result)
            if app.rebind:
                threading.Timer(1, app.server.shutdown).start()
        except (ValueError, KeyError, TypeError, OSError) as exc:
            self.send({"error": str(exc)}, 400)
        except Exception:
            logging.exception("Manager request failed")
            self.send({"error": "Operation failed. See manager.log for details."}, 500)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=data_directory())
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--port", type=int)
    parser.add_argument("--no-discovery", action="store_true", help="For isolated test servers")
    args = parser.parse_args()
    store = Store(args.data_dir)
    logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(store.directory / "manager.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")], format="%(asctime)s %(levelname)s %(message)s")
    config = store.read()
    if args.port:
        store.change(lambda data: data.update(port=port_number(args.port)))
        config = store.read()
    if not port_available(config["port"]):
        try:
            existing = request(f"http://127.0.0.1:{config['port']}/api/info", timeout=2)
            if existing.get("id") == config["id"]:
                if not args.background:
                    webbrowser.open(f"http://127.0.0.1:{config['port']}")
                return
        except (OSError, ValueError):
            logging.info("Configured port is occupied by another application")
        if config["configured"]:
            message = f"Manager port {config['port']} is in use. Close the other application or change the port in {store.path}."
            logging.error(message)
            if os.name == "nt" and not args.background:
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, message, "llama.cpp Instance Manager", 0x10)
            return
        store.change(lambda data: data.update(port=next_port(config["port"])))
    app = Manager(store)
    if args.no_discovery:
        app.discovery.start = lambda: None
    app.start()
    opened = args.background
    try:
        while not app.stop_event.is_set():
            app.rebind = False
            port = store.read()["port"]
            server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
            server.daemon_threads = True
            server.manager = app
            app.server = server
            if not opened:
                webbrowser.open(f"http://127.0.0.1:{port}")
                opened = True
            server.serve_forever(poll_interval=0.3)
            server.server_close()
            if not app.rebind:
                break
    except KeyboardInterrupt:
        logging.info("Manager stopped")
    finally:
        app.stop_event.set()
        app.discovery.close()


if __name__ == "__main__":
    main()
