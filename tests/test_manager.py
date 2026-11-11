import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from manager.app import Handler, Manager
from manager.config import Store, port_available, suggest_ports
from manager.discovery import Discovery, PROTOCOL
from manager.transport import manager_url, request


class ConfigTests(unittest.TestCase):
    def test_port_allocator_skips_busy_and_reserved(self):
        with patch("manager.config.port_available", side_effect=lambda port: port not in (5240, 9931)):
            rows = suggest_ports(3, reserved=[5242])
        ports = [port for row in rows for port in (row["gui_port"], row["api_port"])]
        self.assertEqual(len(set(ports)), 6)
        self.assertFalse(set(ports) & {5240, 5242, 9931, 5239})

    def test_real_busy_socket_is_unavailable(self):
        with socket.socket() as sock:
            sock.bind(("0.0.0.0", 0))
            sock.listen()
            self.assertFalse(port_available(sock.getsockname()[1]))

    def test_store_persists_and_rolls_back_failed_change(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.change(lambda value: value.update(name="Office"))
            self.assertEqual(Store(directory).read()["name"], "Office")
            def broken(value):
                value["name"] = "Broken"
                raise ValueError("failed")
            with self.assertRaises(ValueError):
                store.change(broken)
            self.assertEqual(store.read()["name"], "Office")

    def test_manager_addresses(self):
        self.assertEqual(manager_url("192.168.1.20"), "http://192.168.1.20:5239")
        for address in ("https://box:5239", "http://box:5239/api/state", "http://user@box", "http://box:70000"):
            with self.assertRaises(ValueError):
                manager_url(address)

    def test_discovery_uses_sender_address_and_deduplicates(self):
        discovery = Discovery(lambda: {"id": "local"})
        packet = {"protocol": PROTOCOL, "kind": "announce", "id": "peer", "name": "GPU box", "port": 5249}
        discovery.accept(packet, ("192.168.1.3", 5238))
        discovery.accept(packet, ("192.168.1.3", 5238))
        self.assertEqual(len(discovery.results()), 1)
        self.assertEqual(discovery.results()[0]["url"], "http://192.168.1.3:5249")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.app = Manager(self.store)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.manager = self.app
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def test_live_api_local_state_never_includes_connected_peers(self):
        with self.app.lock:
            self.app.peers = [{"id": "remote", "instances": []}]
        state = request(self.url + "/api/state")
        self.assertNotIn("peers", state)
        self.assertEqual(state["id"], self.store.read()["id"])

    def test_invalid_setup_does_not_persist_settings(self):
        with self.assertRaises(ValueError):
            request(self.url + "/api/setup", {"name": "changed", "port": 5239, "directory": self.temp.name,
                "instances": [{"name": "one", "gui_port": 5500, "api_port": 5500}]})
        self.assertFalse(self.store.read()["configured"])
        self.assertNotEqual(self.store.read()["name"], "changed")

    def test_peer_connect_is_explicit_and_duplicate_identity_is_updated(self):
        peer = {"product": "llama.cpp-instance-manager", "api_version": 1, "id": "peer", "name": "Workshop"}
        with patch("manager.app.request", return_value=peer):
            self.app.connect("192.168.1.22")
            self.app.connect("192.168.1.23")
        self.assertEqual(len(self.store.read()["peers"]), 1)
        self.assertEqual(self.store.read()["peers"][0]["url"], "http://192.168.1.23:5239")

    def test_remote_control_does_not_forward_configuration_actions(self):
        with self.assertRaisesRegex(ValueError, "Open the remote"):
            self.app.action({"server_id": "remote", "instance_id": "anything", "action": "panel"})

    def test_remove_preserves_instance_files(self):
        path = Path(self.temp.name) / "instance"
        path.mkdir()
        marker = path / "model.gguf"
        marker.write_text("preserve")
        self.store.change(lambda config: config["instances"].append({"id": "one", "path": str(path), "install_state": "ready"}))
        with patch("manager.app.process_for", return_value=None):
            self.assertTrue(request(self.url + "/api/remove", {"instance_id": "one"})["ok"])
        self.assertTrue(marker.exists())


if __name__ == "__main__":
    unittest.main()
