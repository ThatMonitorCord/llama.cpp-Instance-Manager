"""Exercise two packaged managers and real preset autostart/federation locally.

Run smoke_upstream.py first. All state stays in .test-data; no login/firewall changes.
"""
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from manager.config import Store, next_port
from manager.instances import Instances
from manager.platform import hidden_process
from manager.transport import request


def wait_until(callback, seconds=100):
    deadline = time.monotonic() + seconds
    last_error = "condition not met"
    while time.monotonic() < deadline:
        try:
            result = callback()
            if result:
                return result
        except (OSError, ValueError) as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise RuntimeError(last_error)


def action(url, body):
    result = request(url + "/api/action", body)
    def done():
        job = next((row for row in request(url + "/api/jobs") if row["id"] == result["job"]), None)
        if job and job["state"] == "error":
            raise RuntimeError(job["message"])
        return job and job["state"] == "complete"
    wait_until(done)


def main():
    source = Store(ROOT / ".test-data/upstream-smoke")
    rows = source.read()["instances"]
    if len(rows) != 2:
        raise RuntimeError("Run smoke_upstream.py first")
    exe = ROOT / "dist/LlamaInstanceManager/LlamaInstanceManager.exe"
    children, managers = [], []
    used = set()
    try:
        for index, row in enumerate(rows):
            directory = ROOT / f".test-data/packaged-{index}"
            store = Store(directory)
            port = next_port(15239, used)
            used.add(port)
            row = dict(row, auto_start=True, preset="Integration smoke")
            store.change(lambda data: data.update(configured=True, name=f"Test server {index+1}", port=port, login_start=False, instances=[row], peers=[]))
            child = subprocess.Popen([str(exe), "--background", "--data-dir", str(directory)], **hidden_process())
            children.append(child)
            url = f"http://127.0.0.1:{port}"
            managers.append((store,url))
            wait_until(lambda: request(url + "/api/info"))
            wait_until(lambda: any(instance.get("running") for instance in request(url + "/api/state")["instances"]))
        print("PASS: both packaged managers auto-started their upstream panels and saved models",flush=True)
        first,second = managers
        request(first[1]+"/api/connect", {"url":second[1]})
        fleet = wait_until(lambda: (data if len((data:=request(first[1]+"/api/fleet"))["servers"])==2 else None))
        assert sum(len(server["instances"]) for server in fleet["servers"]) == 2
        print("PASS: direct manager connection unifies two servers without recursion",flush=True)
        remote = {"server_id":second[0].read()["id"],"instance_id":rows[1]["id"]}
        action(first[1],dict(remote,action="stop"))
        wait_until(lambda: not request(second[1]+"/api/state")["instances"][0]["online"])
        action(first[1],dict(remote,action="start"))
        action(first[1],dict(remote,action="restart"))
        wait_until(lambda: request(second[1]+"/api/state")["instances"][0]["running"])
        print("PASS: remote stop/start/restart uses the same lifecycle as local instances",flush=True)
        for store,url in managers:
            state=request(url+"/api/state")
            assert state["instances"][0]["loaded_preset"]=="Integration smoke"
            assert request(url+"/",text=True).startswith("<!doctype html>")
        print("PASS: packaged assets and loaded-preset reporting",flush=True)
        discovered = request(first[1]+"/api/discovery")["managers"]
        print(f"Discovery on local test interfaces: {len(discovered)} manager(s)",flush=True)
    finally:
        for store,url in managers:
            for row in store.read()["instances"]:
                try:
                    action(url,{"instance_id":row["id"],"action":"stop"})
                except Exception as exc:
                    print(f"HTTP cleanup: {exc}",flush=True)
                    Instances(store).control(row["id"],"stop")
        for child in children:
            child.terminate()
            child.wait(timeout=15)


if __name__ == "__main__":
    main()
