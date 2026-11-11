"""Small LAN broadcast discovery. HTTP is used for all management traffic."""
import json
import logging
import socket
import threading
import time
from .config import DISCOVERY_PORT

PROTOCOL = "llama-instance-manager/1"


class Discovery:
    def __init__(self, info):
        self.info = info
        self.lock = threading.Lock()
        self.seen = {}
        self.stop_event = threading.Event()
        self.socket = None
        self.error = None

    def start(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("", DISCOVERY_PORT))
            sock.settimeout(1)
            self.socket = sock
            threading.Thread(target=self.run, daemon=True).start()
        except OSError as exc:
            self.error = str(exc)
            logging.warning("LAN discovery unavailable: %s", exc)

    def packet(self, kind):
        return json.dumps({"protocol": PROTOCOL, "kind": kind, **self.info()}).encode()

    def scan(self):
        if self.socket:
            try:
                self.socket.sendto(self.packet("discover"), ("255.255.255.255", DISCOVERY_PORT))
            except OSError as exc:
                logging.debug("Discovery broadcast failed: %s", exc)
        return self.results()

    def accept(self, packet, address):
        if packet.get("protocol") != PROTOCOL or packet.get("id") == self.info()["id"]:
            return
        if packet.get("kind") not in ("discover", "announce"):
            return
        port = packet.get("port")
        if not isinstance(port, int) or not 1024 <= port <= 65535:
            return
        identity = str(packet.get("id", ""))[:100]
        if not identity:
            return
        with self.lock:
            self.seen[identity] = {"id": identity, "name": str(packet.get("name", address[0]))[:100],
                                   "url": f"http://{address[0]}:{port}", "seen": time.time()}
        if packet["kind"] == "discover" and self.socket:
            self.socket.sendto(self.packet("announce"), address)

    def results(self):
        with self.lock:
            return [dict(row) for row in self.seen.values() if time.time() - row["seen"] < 35]

    def run(self):
        next_scan = 0
        while not self.stop_event.is_set():
            if time.monotonic() >= next_scan:
                self.scan()
                next_scan = time.monotonic() + 10
            try:
                data, address = self.socket.recvfrom(4096)
                self.accept(json.loads(data), address)
            except socket.timeout:
                continue
            except (OSError, ValueError, TypeError, AttributeError) as exc:
                logging.debug("Ignored discovery packet: %s", exc)

    def close(self):
        self.stop_event.set()
        if self.socket:
            self.socket.close()
