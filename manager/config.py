"""Atomic manager settings and port allocation."""
import copy
import json
import os
from pathlib import Path
import socket
import threading
import uuid

DEFAULT_PORT = 5239
DISCOVERY_PORT = 5238
UPSTREAM = "https://github.com/thomas9120/LLama-GUI.git"
REPOSITORY = "ThatMonitorCord/llama.cpp-Instance-Manager"


def data_directory():
    return Path(os.environ.get("LLAMA_MANAGER_DATA", str(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "llama.cpp Instance Manager")))


def port_number(value):
    if isinstance(value, bool):
        raise ValueError("Port must be a number from 1024 to 65535.")
    try:
        number = int(str(value))
    except (ValueError, TypeError):
        raise ValueError("Port must be a number from 1024 to 65535.") from None
    if not 1024 <= number <= 65535:
        raise ValueError("Port must be a number from 1024 to 65535.")
    return number


def port_available(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind(("0.0.0.0", port_number(port)))
            return True
        except OSError:
            return False


def next_port(start, used=()):
    for candidate in range(max(1024, start), 65536):
        if candidate not in used and port_available(candidate):
            return candidate
    raise ValueError("No available port was found. Choose another starting port.")


def suggest_ports(count, manager_port=DEFAULT_PORT, reserved=()):
    count = int(count)
    if not 1 <= count <= 100:
        raise ValueError("Choose between 1 and 100 instances.")
    used = set(reserved) | {manager_port}
    result = []
    for index in range(count):
        gui = next_port(5240, used)
        used.add(gui)
        api = next_port(9931, used)
        used.add(api)
        result.append({"name": f"llama.cpp instance {index + 1}", "gui_port": gui, "api_port": api})
    return result


def label(value, field="Name"):
    value = str(value or "").strip()
    if not value or len(value) > 100 or any(ord(c) < 32 for c in value):
        raise ValueError(f"{field} must contain 1–100 printable characters.")
    return value


class Store:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "manager.json"
        self.lock = threading.RLock()
        if self.path.exists():
            self.value = json.loads(self.path.read_text(encoding="utf-8"))
            if self.value.get("schema") != 1:
                raise ValueError("Unsupported manager settings version.")
        else:
            self.value = {"schema": 1, "id": str(uuid.uuid4()), "name": socket.gethostname(),
                          "port": DEFAULT_PORT, "configured": False, "login_start": True,
                          "instances_dir": str(self.directory / "instances"), "instances": [], "peers": []}
            self.save()

    def read(self):
        with self.lock:
            return copy.deepcopy(self.value)

    def save(self):
        with self.lock:
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.value, indent=2), encoding="utf-8")
            temporary.replace(self.path)

    def change(self, callback):
        with self.lock:
            before = copy.deepcopy(self.value)
            try:
                result = callback(self.value)
                self.save()
                return result
            except Exception:
                self.value = before
                raise

    def instance(self, instance_id):
        for instance in self.read()["instances"]:
            if instance["id"] == instance_id:
                return instance
        raise ValueError("Instance not found.")

    def update_instance(self, instance_id, **values):
        def update(config):
            instance = next(item for item in config["instances"] if item["id"] == instance_id)
            instance.update(values)
        self.change(update)
