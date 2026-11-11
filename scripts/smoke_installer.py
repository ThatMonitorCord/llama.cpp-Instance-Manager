"""Install, upgrade, and uninstall the built setup in an isolated workspace folder."""
from pathlib import Path
import os
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from manager.config import Store, next_port
from manager.platform import hidden_process
from manager.transport import request


def main():
    if os.name!="nt":
        raise RuntimeError("Windows installer test")
    import winreg
    destination=ROOT/".test-data/installed-app"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{5E8A15A3-7C9C-47A5-A577-16CE0B45B43B}_is1") as key:
            installed=winreg.QueryValueEx(key,"InstallLocation")[0]
            if Path(installed).resolve()!=destination.resolve():
                raise RuntimeError("An existing user installation is present; refusing to replace it during testing.")
    except FileNotFoundError:
        pass
    setup=next((ROOT/"dist").glob("*-setup.exe"))
    args=[str(setup),"/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/NOICONS","/MERGETASKS=!desktopicon",f"/DIR={destination}",f"/LOG={ROOT/'.test-data/installer.log'}"]
    subprocess.run(args,check=True,timeout=180,**hidden_process())
    exe=destination/"LlamaInstanceManager.exe"
    assert exe.is_file()
    for binary in ("runtimes/python/python.exe","runtimes/git/cmd/git.exe","runtimes/node/node.exe"):
        assert (destination/binary).is_file(),binary
    print("PASS: clean setup includes the manager and all portable prerequisites",flush=True)
    store=Store(ROOT/".test-data/installed-profile")
    port=next_port(16239)
    store.change(lambda data:data.update(port=port,name="Upgrade persistence",configured=True,login_start=False))
    marker=store.directory/"models/keep.gguf"
    marker.parent.mkdir(exist_ok=True)
    marker.write_text("preserve test data")
    child=None
    try:
        for iteration in range(2):
            child=subprocess.Popen([str(exe),"--background","--data-dir",str(store.directory),"--no-discovery"],**hidden_process())
            ready=False
            for _ in range(40):
                try:
                    info=request(f"http://127.0.0.1:{port}/api/info",timeout=1)
                    ready=info["name"]=="Upgrade persistence"
                    if ready:
                        break
                except (OSError,ValueError):
                    time.sleep(.25)
            assert ready,"Installed application did not start"
            assert "llama.cpp Instance Manager" in request(f"http://127.0.0.1:{port}/",text=True)
            subprocess.run([str(exe),"--quit","--background","--data-dir",str(store.directory)],check=True,timeout=15,**hidden_process())
            child.wait(timeout=15)
            if iteration==0:
                subprocess.run(args,check=True,timeout=180,**hidden_process())
                assert marker.read_text()=="preserve test data"
                assert Store(store.directory).read()["name"]=="Upgrade persistence"
        print("PASS: installed app starts, upgrades, preserves settings/models, and starts again",flush=True)
    finally:
        if child and child.poll() is None:
            child.terminate();child.wait(timeout=15)
        uninstall=destination/"unins000.exe"
        if uninstall.exists():
            subprocess.run([str(uninstall),"/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART"],check=True,timeout=120,**hidden_process())
    assert marker.exists()
    print("PASS: uninstall preserves instance data",flush=True)


if __name__=="__main__":
    main()
