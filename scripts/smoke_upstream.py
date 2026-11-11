"""Opt-in Windows integration: install two real upstream copies in .test-data.

Downloads dependencies and a tiny CPU test model. Does not alter login startup or
firewall settings. All test processes are stopped on exit; artifacts are retained.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from manager.config import Store, suggest_ports, UPSTREAM
from manager.instances import Instances
import manager.instances as module
from manager.transport import request


def main():
    module.APP_ROOT = ROOT / "build"
    directory = ROOT / ".test-data" / "upstream-smoke"
    store = Store(directory)
    controller = Instances(store)
    rows = store.read()["instances"]
    if not rows:
        rows = controller.plan(suggest_ports(2, 5239), str(directory / "instances"))
        store.change(lambda config: config["instances"].extend(rows))
    try:
        for row in rows:
            if row.get("install_state") != "ready":
                controller.install_one(row, "", lambda message: print(message, flush=True))
            else:
                controller.control(row["id"], "panel")
        rows = store.read()["instances"]
        snapshot = controller.snapshot()
        assert len(snapshot["instances"]) == 2 and all(row["online"] for row in snapshot["instances"]), snapshot
        print("PASS: two independent upstream control panels are online", flush=True)
        for row in rows:
            git = str(Path(row["path"]).parent / "runtime/git/cmd/git.exe")
            status = subprocess.check_output([git, "-C", row["path"], "status", "--porcelain"], text=True)
            origin = subprocess.check_output([git, "-C", row["path"], "remote", "get-url", "origin"], text=True).strip()
            assert not status, status
            assert origin == UPSTREAM, origin
        print("PASS: both upstream checkouts are clean and retain their update origins", flush=True)
        for row in rows:
            status = controller.api(row, "/api/status")
            if not status["installed"]:
                releases = controller.api(row, "/api/releases?backend=cpu", timeout=60)
                tag = releases[0]["tag"]
                print(f"Installing CPU backend {tag} in {row['name']}", flush=True)
                controller.api(row, "/api/install", {"tag":tag,"backend":"cpu"})
                deadline = time.monotonic() + 300
                while time.monotonic() < deadline:
                    status = controller.api(row, "/api/status")
                    if status["installed"]:
                        break
                    time.sleep(2)
                else:
                    raise RuntimeError(controller.api(row, "/api/download-progress"))
            model = Path(row["path"]) / "models/stories260K.gguf"
            if not model.exists():
                urllib.request.urlretrieve("https://huggingface.co/ggml-org/tiny-llamas/resolve/main/stories260K.gguf", model)
            preset = {"tool":"llama-server","model":model.name,"flags":{
                "port":row["api_port"],"host":"0.0.0.0","ctx_size":512,"fit":"off","gpu_layers":"0",
                "parallel":1,"cache_ram":0,"metrics":True,"slots_endpoint":True,"threads":2}}
            controller.api(row, "/api/presets", {"name":"Integration smoke","data":preset})
            store.update_instance(row["id"], preset="Integration smoke")
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda row: controller.control(row["id"], "start"), rows))
        print("PASS: two models started from saved presets using upstream flag compilers", flush=True)
        for row in rows:
            response = request(f"http://127.0.0.1:{row['api_port']}/completion", {"prompt":"Once upon a time", "n_predict":16}, timeout=30)
            assert "content" in response, response
        snapshot = controller.snapshot()
        assert all("llamacpp:tokens_predicted_total" in row.get("metrics", "") for row in snapshot["instances"]), snapshot
        assert all(row["loaded_preset"] == "Integration smoke" for row in snapshot["instances"])
        print("PASS: inference output, metrics, slots, and loaded preset identities", flush=True)
        controller.control(rows[0]["id"], "restart")
        assert controller.api(rows[1], "/api/status")["running"]
        print("PASS: restart one instance without affecting the other", flush=True)
    finally:
        for row in store.read()["instances"]:
            try:
                controller.control(row["id"], "stop")
            except Exception as exc:
                print(f"Cleanup failed for {row['name']}: {exc}", flush=True)


if __name__ == "__main__":
    main()
